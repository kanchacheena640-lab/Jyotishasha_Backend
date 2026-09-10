"""Draft authoring and live N2 preview. No sending/approval/scheduling imports."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import UUID
from sqlalchemy import update
from extensions import db
from modules.models_saved_audience import SavedAudience, SavedAudienceMember, AUDIENCE_TYPE_FIXED
from modules.services.saved_audience_criteria import validate_criteria, CriteriaValidationError
from notifications.campaign_models import NotificationCampaign
from notifications.saved_audience_recipient_resolver import resolve_saved_audience_recipients, RecipientResolutionError

APP_TARGETS = ('ASK_NOW','KUNDALI','REPORTS','SUBSCRIPTION','PROFILE','DASHBOARD')
WEBSITE_HOSTS = {'jyotishasha.com','www.jyotishasha.com'}
# Existing first-party Footer.tsx social link is the evidence for this exact URL.
YOUTUBE_URL = 'https://www.youtube.com/@jyotishasha'
UTM_KEYS = {'utm_source','utm_medium','utm_campaign'}


class CampaignError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def fail(code, message, status=400):
    raise CampaignError(code,message,status)


def positive_int(value, name):
    if type(value) is not int or value <= 0: fail('invalid_input',f'{name} must be a positive integer.')
    return value


def valid_url(value):
    if not isinstance(value,str): fail('invalid_url','Enter an approved HTTPS URL.')
    value=value.strip()
    if not value or len(value)>2048 or any(ord(c)<=32 or ord(c)==127 for c in value) or '\\' in value:
        fail('invalid_url','Invalid URL characters or length.')
    try:
        parsed=urlsplit(value)
        if parsed.scheme.lower()!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in (None,443): raise ValueError()
        host=parsed.hostname.lower()
    except ValueError: fail('invalid_url','Use an absolute HTTPS URL without credentials or a custom port.')
    if host not in WEBSITE_HOSTS:
        if value.rstrip('/') == YOUTUBE_URL: return YOUTUBE_URL
        fail('invalid_url','Use jyotishasha.com, www.jyotishasha.com, or the approved Jyotishasha YouTube channel.')
    # URL parser alone accepts malformed percent escapes; reject those explicitly.
    import re
    if re.search(r'%(?![0-9a-fA-F]{2})',value): fail('invalid_url','Malformed URL encoding.')
    pairs=parse_qsl(parsed.query,keep_blank_values=True)
    reserved=[key.lower() for key,_ in pairs if key.lower() in UTM_KEYS]
    if len(reserved)!=len(set(reserved)): fail('invalid_url','Duplicate campaign attribution parameters are not allowed.')
    # Attribution is generated separately, never repeatedly appended on edits.
    pairs=[(key,val) for key,val in pairs if key.lower() not in UTM_KEYS]
    return urlunsplit(('https',host,parsed.path or '/',urlencode(pairs),parsed.fragment))


def validate_action(action):
    if not isinstance(action,dict) or set(action)!={'type','target','parameters'}: fail('invalid_action','Action requires type, target and parameters only.')
    kind,target,parameters=action['type'],action['target'],action['parameters']
    if kind=='NONE' and target is None and parameters=={}: return dict(type=kind,target=None,parameters={})
    if kind=='APP_DEEP_LINK' and target in APP_TARGETS and parameters=={}: return dict(type=kind,target=target,parameters={})
    if kind=='WEB_URL' and target=='HTTPS_URL' and isinstance(parameters,dict) and set(parameters)=={'url'}:
        return dict(type=kind,target=target,parameters={'url':valid_url(parameters['url'])})
    fail('invalid_action','Choose an approved action and destination. Arbitrary routes are not supported.')


def audience_definition(audience_id, require_active=True):
    """Returns (row, criteria, digest) -- the ONE snapshot-building
    function every draft-save/approve/schedule/drift-check call site
    shares. Saved Audience V2: for a FIXED audience `criteria` is a
    freshly-queried snapshot of saved_audience_members (never
    row.criteria, which is NULL for a fixed row) --
    {"version": 2, "type": "fixed", "user_ids": [...]}. This is what
    campaign approval/scheduling freezes into NotificationCampaignExecution.
    approved_criteria (notifications/campaign_execution_service.py,
    campaign_schedule_service.py) and what save_campaign()'s own
    draft_criteria_hash drift-detection compares against -- so if a
    fixed audience's membership DOES shrink (the only way it can: a
    member's account being deleted, ON DELETE CASCADE) before a draft
    is approved, that is correctly detected as a definition change,
    same as any DYNAMIC criteria edit already is. A fixed audience's
    digest is otherwise stable, since membership has no edit endpoint."""
    positive_int(audience_id,'saved_audience_id')
    row=db.session.get(SavedAudience,audience_id)
    if row is None: fail('audience_missing','SavedAudience no longer exists.',422)
    if require_active and not row.is_active: fail('audience_inactive','Select an active SavedAudience.',422)
    if row.audience_type == AUDIENCE_TYPE_FIXED:
        member_ids = sorted(
            m.user_id for m in
            SavedAudienceMember.query.filter_by(saved_audience_id=row.id).all()
        )
        criteria = {'version': 2, 'type': 'fixed', 'user_ids': member_ids}
    else:
        try:
            if not isinstance(row.criteria,dict) or type(row.criteria.get('version')) is not int: raise ValueError()
            criteria={'version':row.criteria['version'],'filters':validate_criteria(row.criteria,authoring=False)}
        except (CriteriaValidationError,ValueError): fail('invalid_criteria','SavedAudience criteria are invalid.',422)
    digest=hashlib.sha256(json.dumps(criteria,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return row,criteria,digest


def get_campaign(campaign_id):
    try: campaign_id=str(UUID(str(campaign_id)))
    except ValueError: fail('not_found','Campaign not found.',404)
    row=db.session.get(NotificationCampaign,campaign_id)
    if row is None: fail('not_found','Campaign not found.',404)
    return row


def summarize(row):
    """Lightweight list-row projection (Admin campaign list). Deliberately
    skips audience_definition()'s live re-validation/hash comparison --
    same restraint saved_audience_service.list_audiences() already uses
    for its own list endpoint -- so a page of N campaigns costs O(1)
    queries, not N extra criteria re-validations. Detail view (serialize())
    remains the place audience_definition_changed is computed."""
    return dict(id=row.id,state=row.state,revision=row.revision,title=row.title,
        audience_mode=row.audience_mode,saved_audience_id=row.saved_audience_id,
        action_type=row.action['type'] if isinstance(row.action,dict) else None,
        created_at=row.created_at.isoformat(),updated_at=row.updated_at.isoformat())


def list_campaigns(*, page=1, page_size=20, search=None):
    """DRAFT-only list (N3's only durable state -- see the model's own
    CheckConstraint). No legacy NotificationJob rows are read/merged here;
    that table remains its own separate namespace per N1 Section 2/28.
    `page`/`page_size` are already-parsed ints (or None) from the route
    layer, same division of labor as preview_audience()'s own callers."""
    page=max(1,page if isinstance(page,int) else 1)
    page_size=min(max(1,page_size if isinstance(page_size,int) else 20),100)
    query=db.session.query(NotificationCampaign)
    if search is not None:
        if not isinstance(search,str): fail('invalid_input','search must be a string.')
        term=search.strip()
        if term: query=query.filter(NotificationCampaign.title.ilike(f'%{term}%'))
    total=query.order_by(None).count()
    rows=query.order_by(NotificationCampaign.created_at.desc(),NotificationCampaign.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return dict(campaigns=[summarize(r) for r in rows],
        pagination=dict(page=page,page_size=page_size,total_count=total,total_pages=max(1,-(-total//page_size)) if total else 1))


def serialize(row):
    audience=db.session.get(SavedAudience,row.saved_audience_id)
    source_status='missing' if audience is None else 'inactive' if not audience.is_active else 'active'
    changed=False
    try: _,_,digest=audience_definition(row.saved_audience_id,require_active=False);changed=digest!=row.draft_criteria_hash
    except CampaignError: source_status='invalid' if audience and audience.is_active else source_status
    # N4 -- a campaign no longer in DRAFT has an approved, IMMUTABLE
    # definition captured on its execution row (campaign_execution_
    # models.py), never this mutable draft_criteria_hash again.
    from notifications.campaign_execution_models import NotificationCampaignExecution
    execution = NotificationCampaignExecution.query.filter_by(campaign_id=row.id).first() if row.state != 'DRAFT' else None
    return dict(id=row.id,state=row.state,hold_reason=row.hold_reason,revision=row.revision,title=row.title,body=row.body,
        audience_mode=row.audience_mode,saved_audience_id=row.saved_audience_id,
        audience_name=audience.name if audience else None,audience_status=source_status,
        draft_criteria=row.draft_criteria,criteria_version=row.criteria_version,draft_criteria_hash=row.draft_criteria_hash,
        audience_definition_changed=changed,
        definition_status='APPROVED' if execution else 'UNAPPROVED_DRAFT',
        execution_id=execution.id if execution else None,
        action=row.action,action_registry_version=1,
        attribution={'utm_source':'jyotishasha_app','utm_medium':'push','utm_campaign':'nc_'+row.public_key},
        created_at=row.created_at.isoformat(),updated_at=row.updated_at.isoformat(),created_by=row.created_by,updated_by=row.updated_by)


def save_campaign(data, campaign_id=None, actor=None):
    if not isinstance(data,dict): fail('invalid_input','Expected a JSON object.')
    allowed={'title','body','audience_mode','saved_audience_id','action'}
    if campaign_id: allowed|={'revision','refresh_audience'}
    if set(data)-allowed: fail('unknown_fields','Unknown draft fields are not allowed.')
    row=get_campaign(campaign_id) if campaign_id else None
    if row and row.state!='DRAFT': fail('not_draft','Only drafts can be edited.',409)
    if row and positive_int(data.get('revision'),'revision')!=row.revision: fail('stale_revision','Draft changed in another tab. Reload before saving.',409)
    values={}
    for key,limit in [('title',200),('body',500)]:
        val=data.get(key,getattr(row,key,None))
        if not isinstance(val,str) or not val.strip() or len(val.strip())>limit: fail('invalid_content',f'{key} is required and must be at most {limit} characters.')
        values[key]=val.strip()
    mode=data.get('audience_mode',row.audience_mode if row else None)
    if mode!='SAVED_AUDIENCE': fail('invalid_audience_mode','Select SavedAudience explicitly.')
    audience_id=positive_int(data.get('saved_audience_id',row.saved_audience_id if row else None),'saved_audience_id')
    refresh=data.get('refresh_audience',False)
    if type(refresh) is not bool: fail('invalid_input','refresh_audience must be boolean.')
    if not row or audience_id!=row.saved_audience_id or refresh:
        _,criteria,digest=audience_definition(audience_id)
        values.update(draft_criteria=criteria,criteria_version=criteria['version'],draft_criteria_hash=digest)
    values.update(audience_mode=mode,saved_audience_id=audience_id,action=validate_action(data.get('action',row.action if row else None)))
    # Reserve 700 bytes for future N1 delivery envelope identifiers/metadata.
    if len(json.dumps({k:values[k] for k in ('title','body','action')},ensure_ascii=False).encode())>2800:
        fail('content_too_large','Content and action exceed the UTF-8 payload budget.')
    now=datetime.now(timezone.utc)
    if row:
        result=db.session.execute(update(NotificationCampaign).where(NotificationCampaign.id==row.id,NotificationCampaign.revision==data['revision'],NotificationCampaign.state=='DRAFT').values(**values,revision=row.revision+1,updated_at=now,updated_by=actor).execution_options(synchronize_session=False))
        if result.rowcount!=1: db.session.rollback();fail('stale_revision','Draft changed in another tab. Reload before saving.',409)
        db.session.commit();db.session.refresh(row)
    else:
        row=NotificationCampaign(**values,created_by=actor,updated_by=actor,created_at=now,updated_at=now)
        db.session.add(row);db.session.commit()
    return serialize(row)


def preview(data, campaign_id=None):
    if not isinstance(data,dict) or set(data)-{'saved_audience_id','revision','campaign_id'}: fail('invalid_input','Invalid preview request.')
    identity=campaign_id or data.get('campaign_id')
    row=get_campaign(identity) if identity else None
    if row and data.get('revision')!=row.revision: fail('stale_revision','Draft changed. Reload before preview.',409)
    audience_id=positive_int(data.get('saved_audience_id',row.saved_audience_id if row else None),'saved_audience_id')
    metadata=dict(campaign_id=row.id if row else None,revision=row.revision if row else None,
        saved_audience_id=audience_id,generated_at=datetime.now(timezone.utc).isoformat(),freshness_seconds=900)
    try:
        result=resolve_saved_audience_recipients(audience_id).admin_safe()
    except RecipientResolutionError as exc:
        if exc.code=='SAFETY_CEILING_EXCEEDED':
            return dict(**metadata,status='BLOCKED',error=exc.code,matched_user_count=exc.matched_user_count,
                eligible_recipient_count=None,excluded_recipient_count=None,exclusion_counts={},
                safety_ceiling_exceeded=True,absolute_ceiling=50000,large_audience=True,is_all_users=None)
        status=503 if exc.code=='RESOLUTION_UNAVAILABLE' else 422
        fail('preview_unavailable','Live recipient preview is unavailable. Check the selected audience and retry.',status)
    return {**result,**metadata,'status':'READY','large_audience':max(result['matched_user_count'],result['eligible_recipient_count'])>=1000}
