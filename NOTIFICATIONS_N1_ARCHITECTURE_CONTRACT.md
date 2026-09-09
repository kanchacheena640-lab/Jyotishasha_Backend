# NOTIFICATIONS N1 — ARCHITECTURE & CONTRACT FREEZE

Date: 2026-09-08. Authoritative discovery input: [NOTIFICATIONS_N0_DISCOVERY_AUDIT.md](NOTIFICATIONS_N0_DISCOVERY_AUDIT.md). Scope: Admin Campaign Notification v1 architecture. This document is not an implementation or activation approval.

Decision classification applies to every normative paragraph/table in its labeled block:

- **FROZEN**: required architectural invariant or technical contract for subsequent implementation; does not mean code already supports it.
- **FROZEN — PRODUCT OWNER APPROVED**: approved P1–P10 scope; each decision records APPROVED AS PROPOSED or APPROVED WITH MODIFICATION. No P1–P10 approval remains outstanding.
- **DEFERRED**: outside the initial implementation scope, with the stated prerequisite for reconsideration.

P1–P10 are **FROZEN — PRODUCT OWNER APPROVED**. This document is the authoritative scope/contract for separately authorized N2–N8 work. Approval does not mean implementation is complete and does not authorize N2+, Language Filter work, Firebase changes, real sending or production activation. No database/application startup, application code/model/migration/API/UI/Flutter changes, Firebase/production access, real sends, commit, push or deploy occurred in this consolidation. Only this document was updated; existing uncommitted work is preserved.

## 1. Scope and Non-Goals

**FROZEN.** Define the SavedAudience → campaign → preview → execution → delivery → action/attribution contract, and the N2–N8 implementation gates. Preserve frozen Users/SavedAudience semantics. N1 creates documentation only. N2 starts with recipient resolution and eligibility preview using synthetic/no-send tests; passing N2 cannot enable Firebase.

**DEFERRED.** Recurring campaigns, multi-channel messaging, experiments, automated audience optimization, device-level delivery receipts, multi-device fan-out and a general marketing automation platform. No automatic event/alert redesign is included.

## 2. Three-Pipeline Boundary

**FROZEN.** These business pipelines remain logically and operationally distinct:

| Source namespace | Business owner and trigger | Campaign v1 boundary |
|---|---|---|
| AUTOMATIC_EVENT | Existing morning/evening astrology/event and Panchang workflows | No changes to dates, trigger timing, builder selection or astrology calculations |
| PERSONALIZED_ALERT | Existing profile, entitlement, alert detection and selection | No changes to entitlement, selection, cooldown or attention policy |
| ADMIN_CAMPAIGN | Explicit Admin action against SavedAudience | New campaign/execution/delivery contracts in this document |

NotificationJob is the Admin campaign container. A or B must not be converted into NotificationJob records to make C work. Sharing a future transport interface is permitted only through a separately verified compatibility adapter; business selectors and scheduler ownership remain separate.

## 3. Terminology

**FROZEN.**

| Term | Exact meaning |
|---|---|
| SavedAudience | Versioned declarative criteria, dynamically resolved to canonical users.id; no stored membership |
| Campaign | One approved communication intent/content/action/audience definition, e.g. X1; represented by an extended NotificationJob |
| Execution | One durable resolution and sending lifecycle for that campaign, including retries of its frozen targets |
| Recipient/Delivery | One canonical user/profile and unique push target selected for an execution, with its own transport outcome |
| Notification UUID | Stable opaque UUID assigned to a delivery before sending, retained across its attempts |
| FCM accepted | Provider explicitly accepted the request; not proof of device receipt |
| Failed | Explicit unsuccessful outcome known not to be provider acceptance; retryable or final as classified |
| Suppressed | User excluded before targets freeze, or frozen target subsequently withheld without another send; reason is retained |
| Unknown | Attempt may have reached/been accepted by provider, but no conclusive durable outcome exists |
| Opened | Explicit FCM notification tap callback or separately identified Bell-item open; never inferred from receipt |
| Action Click | Actual explicit CTA interaction where one exists; direct notification navigation does not manufacture a CTA event |
| Destination Open | Destination acknowledges successful initial presentation following a direct actionable tap or actual CTA, where measurable; neither tap nor OS handoff alone is success |
| Conversion | Authoritative qualifying business event attached to a validated click-through attribution context |

UI/API/reporting must not call provider acceptance “device delivered” or present an acceptance rate as a delivery rate. Open/action/conversion are observations separate from transport state.

## 4. Identity Contract

**FROZEN.** Hierarchy: `NotificationJob.id → NotificationExecution.id → NotificationDelivery.id / notification_uuid`. Keep existing integer Job PK as internal campaign_id. Use UUIDs for new execution and delivery IDs; delivery's notification_uuid is globally unique and stable. Give each new campaign an independent opaque public campaign key for URLs. One execution per new v1 campaign, enforced by a unique campaign reference; later recurring execution support requires a new contract.

X1 and X2 have different Job IDs/public keys even with identical audience, title and payload. Retrying X1 reuses its execution and delivery UUIDs. “Send again” clones into a new DRAFT campaign and requires fresh preview/approval. Accepted/terminal X1 cannot be reopened for sending.

| Surface | Required identity |
|---|---|
| Database | Campaign PK/public key, execution UUID, delivery PK/notification UUID, source namespace, environment |
| FCM data | campaign_id as string, execution_id, notification_id, source=ADMIN_CAMPAIGN, contract_version |
| Flutter/Bell | Same campaign/execution/notification identities preserved verbatim; no ID reconstructed from content |
| Activity Events | notification_id, campaign_id, execution_id, source and interaction channel; validated against delivery ownership |
| WEB_URL | Jyotishasha website: opaque campaign public key via utm_campaign. Approved YouTube: validated destination URL; no website attribution/receipt assumed. No recipient UUID/UID/token in either URL |

The existing event notification_context only accepts notification_id/campaign_id/slot. execution_id and channel support need explicit versioned schema/producer changes; they must not be silently added to today's strict ingestion schema. Internal IDs in a payload are not authorization credentials.

## 5. SavedAudience Contract

**FROZEN.** New campaigns require `audience_mode=SAVED_AUDIENCE` and saved_audience_id. Missing/unknown mode, bad ID, unsupported criteria/version or unavailable required resolver returns a typed failure, never an all-users fallback. New endpoints must not invoke legacy audience JSON interpretation. Legacy jobs remain explicitly tagged legacy and are not converted by guessing JSON meaning.

Canonical membership remains users.id. No member IDs, token lists, notification history or campaign counters are stored on SavedAudience. Reuse stored-criteria validation with authoring=False and the frozen shared Users resolver; do not recreate astrology/interest/subscription filters.

**FROZEN — PRODUCT OWNER APPROVED (P2; APPROVED AS PROPOSED).** Save the audience reference, criteria JSON, canonical serialization SHA-256 hash and criteria schema version when creating a draft. Approval locks that snapshot. Later audience edits do not change approved/scheduled content or criteria; show “audience definition changed” in Admin. Draft refresh is explicit and invalidates preview. Membership still changes with live user data. An inactive/deactivated/missing audience blocks initial dispatch even with a retained snapshot. If this happens after targets freeze, stop future attempts and request cancellation; accepted sends cannot be undone. Missing audience blocks rather than replacing it with all users. Reapproval can resume a pre-freeze paused execution after reactivation; a cancelled campaign requires a new campaign.

## 6. Dynamic Membership Contract

**FROZEN — PRODUCT OWNER APPROVED (P2).** Frozen audience definition + dynamic live membership at execution time: X1 approved for Saturn Mahadasha with preview=40 evaluates the same Saturn criteria against current user data at dispatch and may resolve 46, subject to execution safety/count-drift policy (approved P7). If SavedAudience X is later edited to Jupiter Mahadasha, X1 retains its approved Saturn snapshot/hash; a future X2 may approve the new Jupiter definition. Retries after target freeze retain exactly that execution's targets and never add freshly matching members.

**FROZEN.** Monday preview=40 does not freeze Friday membership. Friday execution resolves the approved definition against current data and can match 55. Resolution occurs once for the successfully frozen target set, not on each send batch/retry. X2 resolves afresh. Store resolved_at, resolver contract version, criteria hash, counts and target set on execution records.

Target staging is non-sendable until an atomic targets_frozen_at transition. Use a consistent database snapshot for membership/bridge classification; shared global transit context is calculated once per resolution using the existing resolver. Do not hold a transaction open across FCM calls. Before freeze, an interrupted resolution may be discarded/recomputed within the same execution because no delivery was dispatchable. After freeze, restart/retry must use retained targets and never add members. Count-drift review happens before freeze; reapproval reruns resolution and its checks, not a stale preview list.

**DEFERRED.** Explicit schedule-time membership snapshot mode. Snapshotting approved criteria is not snapshotting user membership.

## 7. User → Push Target Contract

**FROZEN.** Resolve `users.id → users.firebase_uid → app_users.firebase_uid → app_users.id → app_users.fcm_token` by bulk joins/lookups. Never compare numeric User and AppUser IDs. AppUser is the delivery token authority; User/Firestore mirrors are not fallbacks. Null/blank UID is excluded; missing profile is excluded; multiple profiles for one non-null UID is an integrity failure and blocks resolution rather than choosing arbitrarily.

One AppUser token slot per UID is the v1 technical scope; no fan-out/device registry is added. Null/empty/whitespace token is missing. A locally known invalid token is ineligible. Otherwise token freshness cannot be inferred from existence. If the same token appears for distinct canonical identities, suppress the entire ambiguous token group as duplicate_target; do not attribute that device arbitrarily to the lowest user ID. This also prevents sending personal content across ambiguous ownership.

Freeze a keyed token fingerprint and a restricted encrypted token snapshot per eligible target. Before each attempt revalidate account/profile existence, preference and current token fingerprint. If ownership/token changes, mark target SUPPRESSED with reason TARGET_CHANGED; do not substitute a new device into X1. A later X2 can use the new token. Invalid-token cleanup must compare the failing token to the current stored value before clearing it, so an old failure never erases a refreshed token. Transport itself cannot commit that cleanup.

**FROZEN — PRODUCT OWNER APPROVED (P10; APPROVED AS PROPOSED).** One current authoritative AppUser token/device slot is the v1 target model; no promise of fan-out to every device. Duplicate/ambiguous ownership protections remain mandatory. Multi-device installation/token registry is **DEFERRED** until actual product/scale evidence justifies it; ambiguous groups are surfaced for repair, not silently merged.

## 8. Eligibility Contract

**FROZEN.** Classify each distinct matched user once, in this order. Counts use users, not attempts:

| Counter | Exclusive classification |
|---|---|
| matched_users | All distinct users.id from approved criteria at resolution |
| missing_identity_bridge | UID null/blank or canonical account disappears before a consistent resolution completes |
| missing_profile | UID exists but no AppUser |
| missing_token | Profile exists but token missing/empty/known invalid |
| preference_suppressed | Push target exists but applicable delivery is explicitly disabled/denied, an existing applicable category preference explicitly opts out, or another genuine policy exclusion applies. Missing dedicated marketing preference records alone are not suppression |
| duplicate_target | Remaining otherwise-eligible users in a token group with conflicting identities; every member excluded |
| eligible_targets | Remaining unique, unambiguous targets |

Identity inconsistency/resolver failure aborts the preview/execution; it must not be reported as a successful zero result. In a completed resolution:

`matched_users = missing_identity_bridge + missing_profile + missing_token + preference_suppressed + duplicate_target + eligible_targets`.

`suppressed_initial` is the sum of the five exclusion counters. Later suppression is separate and must not rewrite the initial matched/eligible counts. Preview includes policy version, resolved_at, criteria hash and technical-target count before preferences. Raw tokens/UIDs are never returned to the browser.

**FROZEN — PRODUCT OWNER APPROVED (P1; APPROVED WITH MODIFICATION).** Admin Campaign v1 is a first-party personalized engagement system. It uses SavedAudience, user intent and available Jyotishasha intelligence to guide users toward reasonably useful/relevant Jyotishasha app features, astrology services, website content, reports, products, subscriptions and approved destinations. Unrelated third-party advertising/promotional campaigns are out of scope. Relevant Jyotishasha-owned YouTube content may be a purpose example, but P1 grants no WEB_URL/YouTube destination permission: destination authorization remains governed by P3, now approved in Section 14.

A user may be eligible when the canonical User → AppUser bridge resolves safely, AppUser has a valid/current push target under the technical contract, applicable notification delivery has not been disabled/denied, and no explicit applicable campaign/personalized-notification category opt-out exists. Preserve missing bridge, missing profile, missing/invalid token, duplicate/ambiguous target and other genuine technical/policy exclusions. Technical capability is not a guarantee of provider acceptance or device delivery.

A separate pre-existing marketing opt-in database record is not mandatory. Its absence must not classify every otherwise push-capable user as UNKNOWN or suppress them. Do not rename token existence as marketing consent: OS notification permission, technical push capability and application-level marketing preference remain distinct. Respect available explicit denial/disablement and applicable opt-outs; if dedicated promotional/personalized preferences are introduced later, the resolver must respect them. Absence of a preference model is distinct from failure to read an existing applicable policy source: genuine dependency errors still fail closed rather than bypass known controls. No consent data is invented.

N2 preview/tests must distinguish absent dedicated preference records (not an exclusion by themselves), explicit denial/opt-out (excluded), technical exclusions and genuine policy-source failures. This approved policy removes the mandatory marketing-preference-foundation prerequisite; it does not authorize implementation or real sending in this documentation task.

## 9. Campaign State Machine

**FROZEN.** State transitions are server-enforced, revision-checked and audited. Status cannot be supplied arbitrarily by clients.

| From | Allowed next states and conditions |
|---|---|
| DRAFT | READY after validated immediate approval; SCHEDULED after validated future approval; CANCELLED |
| SCHEDULED | READY when due; DRAFT on explicit pre-claim edit that invalidates approval; CANCELLED; EXPIRED |
| READY | PROCESSING on atomic execution claim; DRAFT only before claim to edit/reapprove; CANCELLED; EXPIRED |
| PROCESSING | COMPLETED, PARTIAL, FAILED, CANCELLED or EXPIRED after execution settles |
| COMPLETED / PARTIAL / FAILED / CANCELLED / EXPIRED | Terminal for sending; clone creates a new campaign |

COMPLETED means resolution/processing completed with every eligible target ACCEPTED, or no eligible targets with completion_reason=NO_ELIGIBLE_TARGETS. The latter must display “No eligible targets,” not “Sent.” PARTIAL means some acceptance plus any final failure/unknown/later suppression, or any unresolved UNKNOWN even with zero acceptance. FAILED means an unrecoverable execution error, or nonempty eligible set with no acceptance/unknown and only conclusive unsuccessful outcomes. CANCELLED/EXPIRED retain any earlier acceptance counts and indicate partial dispatch if applicable; they never imply recall.

A pre-freeze safety hold is represented by the execution PAUSED state and a visible campaign hold_reason while campaign remains PROCESSING. Content/criteria cannot be changed on a claimed execution. Reapproval of unchanged intent clears a hold only through the approved transition and a fresh resolution.

## 10. Execution State Machine

**FROZEN.** States: PENDING → RESOLVING → FROZEN → SENDING ↔ RETRY_WAIT → COMPLETED/PARTIAL/FAILED. RESOLVING may enter PAUSED before targets freeze; PAUSED → RESOLVING requires recorded reapproval. Any nonterminal state can enter CANCELLING → CANCELLED, or EXPIRED after in-flight attempts settle or become UNKNOWN. A blocked resolution enters FAILED for definitive invalid criteria/integrity errors, PAUSED for reviewable policy holds.

Claim uses a database transaction and row lock/compare-and-set; create/get the unique campaign execution and set owner, monotonically increasing lease generation, lease_until and claimed_at atomically. Workers fence all writes against current lease generation. Technical starting defaults: 120-second lease, heartbeat every 30 seconds, poll every 5 seconds. No network send occurs inside the claim transaction.

Lease expiry alone does not create a new execution. Recovery reclaims the same execution. Pre-freeze staging is non-sendable; post-freeze targets are immutable. Expired ATTEMPTING rows become UNKNOWN unless a durable provider result can be reconciled. Fencing prevents stale worker database updates but cannot retract a request already sent to FCM. Preserve late responses in the attempt journal for reconciliation; do not overwrite newer state blindly.

## 11. Recipient Delivery State Machine

**FROZEN.**

| State | Valid next states / meaning |
|---|---|
| PENDING | ATTEMPTING, SUPPRESSED, CANCELLED, EXPIRED |
| ATTEMPTING | ACCEPTED, FAILED_RETRYABLE, FAILED_PERMANENT, INVALID_TOKEN, UNKNOWN |
| FAILED_RETRYABLE | ATTEMPTING when due/budget remains; FAILED_PERMANENT on exhaustion; SUPPRESSED/CANCELLED/EXPIRED |
| ACCEPTED | Transport-terminal; never resend |
| FAILED_PERMANENT / INVALID_TOKEN | Transport-terminal |
| UNKNOWN | No automatic retry; may become ACCEPTED or conclusive failure only with recorded evidence |
| SUPPRESSED / CANCELLED / EXPIRED | Terminal unsent remainder; preserves any earlier attempt journal |

Each attempt has monotonic attempt_number and an attempt UUID, started_at, finished_at, error class, provider result/message ID and lease generation. Increment attempt_count when an ATTEMPTING claim is durably recorded immediately before invoking transport. A crash before invocation may therefore count as a dispatch attempt with UNKNOWN outcome; metrics must disclose this conservative boundary. Store first_attempted_at/last_attempted_at/accepted_at independently. There is at most one live claimed attempt per delivery. Opens/actions/conversions are append-only observations, never delivery statuses.

## 12. Transport Contract

**FROZEN.** Future interface concept: `send(Target, RenderedMessage, DeliveryContext, Deadline) → TransportResult`. It performs one bounded attempt, with hidden SDK retries disabled or accounted for. Context includes notification UUID, attempt UUID, execution, environment and expiry. No audience queries, business selection, Bell writes, transaction commits or internal business retries are permitted in transport.

Structured result: outcome ACCEPTED/REJECTED/UNKNOWN/SIMULATED; provider; provider_message_id nullable; error_code; error_class; retryable; invalid_token; retry_after nullable; started/finished timestamps; sanitized diagnostics. ACCEPTED requires explicit provider response. Known invalid/unregistered token is permanent. Authentication/configuration or payload defects pause/fail the campaign; do not invalidate every user token. Explicit retryable provider rejection or connection failure conclusively before dispatch can retry. Timeout/disconnect after possible dispatch is UNKNOWN, not a definite failure.

Technical defaults: connection timeout 5 seconds, total attempt deadline 20 seconds, at most 10 concurrent calls, no more than 20 requests/second per campaign worker, bounded work batches of 100. Validate these through failure/load tests before activation; lower limits are allowed, raising them requires operational review. Respect provider retry-after without scheduling beyond execution expiry. These are application limits, not claims about provider quotas.

Admin Campaign can initially wrap the SDK behind this interface; it must not import the credential-refreshing legacy HTTP module in no-send mode. Existing A/B SDK and C legacy HTTP paths remain unchanged during N1/N2. Future convergence requires parity tests, not a wholesale sender replacement.

## 13. Environment Safety Contract

**FROZEN.** Local/test construction permits only NoSendTransport; it rejects attempts to configure real transport even if credentials happen to exist. Do not initialize Firebase, fetch OAuth credentials or import sender modules with network/credential side effects. Tests use synthetic targets and an injected deterministic outcome simulator; network-denial tests prove no Firebase egress. SIMULATED acceptance is labeled simulated, segregated by environment, and excluded from real campaign statistics.

Real C sending requires all of: deployment environment=production, explicit campaign-sending enable flag, configured provider credentials, authorized worker role and approved campaign. Missing/contradictory configuration fails closed. Web/API processes enqueue only and cannot construct a real sender. The flags proposed here are new contracts, not existing protection in N0. Old send-now/test-send endpoints cannot bypass this gate for new campaigns; disable/reroute their C write access before activation without changing A/B execution.

Later DB-dependent tests must verify current_database()=jyotishasha_local before local operations. No production activation is authorized by this document, product policy approval, or passing local tests.

## 14. Action Contract

**FROZEN.** Exactly three action types: NONE, APP_DEEP_LINK, WEB_URL. Registry version=1. Reject unknown fields, mismatched parameter types and arbitrary Flutter paths. Backend validates the same registry the client understands.

| Type/target | Typed parameters |
|---|---|
| NONE | target=null, parameters={} |
| APP_DEEP_LINK / ASK_NOW | parameters={} → existing /asknow mapping |
| APP_DEEP_LINK / KUNDALI | parameters={} → /kundali/overview |
| APP_DEEP_LINK / REPORTS | parameters={} → /reports |
| APP_DEEP_LINK / SUBSCRIPTION | parameters={} → /subscription |
| APP_DEEP_LINK / PROFILE | parameters={} → /profile |
| APP_DEEP_LINK / DASHBOARD | parameters={} → /dashboard |
| WEB_URL / HTTPS_URL | parameters={url: validated absolute HTTPS URL} |

Client mappings retain normal auth/feature prerequisites; an action does not bypass entitlement or invent birth/profile data. No feature-specific IDs/filters are accepted in registry v1.

**DEFERRED.** EVENT and TRANSIT for Admin v1: existing handlers require content/event-specific payloads and sometimes extra types; they need their own stable parameter/resource authorization contract. Existing automatic event/transit handlers remain supported unchanged. Horoscope, Compatibility and Muhurat are not claimed as Admin destinations.

**FROZEN — PRODUCT OWNER APPROVED (P3; APPROVED WITH MODIFICATION).** WEB_URL permits only explicitly trusted, relevant first-party Jyotishasha ecosystem destinations, with destination-specific validation and opening behavior:

- **Jyotishasha website:** allowed exact hosts are `jyotishasha.com` and `www.jyotishasha.com`. HTTPS only; no wildcard subdomains, IP literals, userinfo or non-default ports. Reject malformed URLs and hostname-lookalike attacks. Use the constrained in-app WebView. The initial URL and relevant top-level redirects/navigation must stay within this approved website-host policy.
- **Jyotishasha YouTube content:** permit only Jyotishasha-controlled/explicitly approved relevant content destinations. A youtube.com hostname alone is not authorization; arbitrary YouTube URLs and arbitrary external creators/channels are prohibited. Authoring requires an explicit allowlist/validation mechanism that distinguishes approved destinations from arbitrary links. N3 must inspect the authoritative Jyotishasha channel identity and URL forms before choosing the exact mechanism. No channel identifier or URL-form allowlist is guessed or hard-coded by this document. Until verified, unrecognized YouTube destinations fail validation.
- **YouTube opening:** use safe OS/app external URL handling, opening the YouTube app when supported and otherwise a safe browser/web fallback. Do not force YouTube through the Jyotishasha in-app WebView.
- **Other external destinations:** arbitrary third-party URLs remain prohibited. Admin cannot bypass destination validation by pasting a URL; P3 is not general external-link permission.

Keep NONE, APP_DEEP_LINK and WEB_URL unchanged. Approved website and YouTube destinations both use WEB_URL / HTTPS_URL with the existing typed URL parameter; destination class selects the validator/opening policy, not a new action type. Backend remains the destination-validation authority. Flutter must enforce the approved class/opening policy and must never treat a raw payload URL as automatically trusted. APP_DEEP_LINK destinations are unchanged.

**FROZEN — PRODUCT OWNER APPROVED (P4; APPROVED WITH MODIFICATION).** Direct destination first: NONE opens Notification Detail without an executable destination CTA. APP_DEEP_LINK opens the validated approved app destination directly from push/Bell tap. WEB_URL opens the validated website or approved Jyotishasha YouTube destination directly using P3's opening policy. Invalid, unsupported, unavailable, unsafe or unsatisfied auth/profile/app-state requirements fall back to Notification Detail; no untrusted destination executes. Backend-authoritative validation and the typed registry remain mandatory. A tap emits notification_opened, not a fabricated action_clicked. destination_opened requires an actual acknowledgement where technically measurable. action_clicked is reserved for a real explicit CTA in a future/detail interaction.

## 15. Flutter Payload/Tap Contract

**FROZEN.** FCM data fields are strings, including serialized JSON for action_parameters. Required fields: contract_version="1", source="ADMIN_CAMPAIGN", campaign_id, execution_id, notification_id, action_registry_version="1", action_type, action_target (empty for NONE), action_parameters (JSON object), expires_at (UTC). Notification title/body accompany data. Internal route/screen/click_action fields are not authoring inputs. Bound the serialized envelope and content to a conservative 3,500 UTF-8 byte application budget; fail validation rather than truncate identities/actions.

Foreground receipt updates receipt/Bell presentation only; never emits an open. Background receipt likewise is not an open. Background/terminated taps use the same versioned parser and may queue while the authenticated router initializes. Once ready, actionable taps navigate directly under P4; if required auth/profile/app state cannot be satisfied safely, use Notification Detail fallback instead. Never attribute a message to whichever unrelated account is currently logged in: event ingestion checks delivery ownership, and identity changes drop queued user-scoped context. Unsupported/invalid actions show a safe notification-detail fallback with no executable CTA; no destination_opened is emitted for the requested invalid action.

Separate events: notification_opened(channel=FCM or BELL) on actual tap/open; action_clicked only for an actual explicit CTA, never synthesized for direct navigation. destination_opened requires successful initial destination acknowledgement and links to the originating tap interaction ID or real CTA interaction ID. Fallback-screen presentation and external OS handoff are not success for the intended destination. NONE cannot emit action_clicked. Normal app launch cannot emit notification_opened. Direct actionable taps preserve a validated navigation/click context separately from the generic open event; no conversion is inferred merely because an open was logged.

Deduplicate duplicate OS callbacks/initial-message processing using persisted interaction IDs; retry event upload with the same event ID. A later intentional tap is a new interaction. Navigation executes once per interaction ID. Provide a bounded local event outbox: technical default maximum 100 events, 24-hour queue expiry, cleared on logout/account switch. This prevents network failure from silently redefining an open as absent; it does not guarantee complete analytics.

## 16. Website Landing Contract

**FROZEN — PRODUCT OWNER APPROVED (P3 scope).** This first-party website landing/UTM contract applies to the approved Jyotishasha website hosts. Approved YouTube destinations remain WEB_URL actions but open externally under Section 14; they do not automatically participate in website landing events, first-touch storage or report-payment attribution. Do not append website attribution parameters to YouTube URLs by assumption. A successful OS handoff is not evidence that YouTube content opened or was viewed; record no destination-open/view/conversion claim without the relevant acknowledgement. P6 attribution policy is approved as proposed; external destination measurability is not assumed.

**FROZEN.** Map campaign public key to utm_campaign with fixed source/medium: `utm_source=jyotishasha_app`, `utm_medium=push`, `utm_campaign=nc_<opaque_campaign_key>`. Server generates/overrides these reserved parameters for Jyotishasha website WEB_URL destinations; reject ambiguous duplicate reserved query keys. Never include users.id, Firebase UID, token, audience criteria or recipient notification UUID in a URL. Campaign key is attribution metadata, not proof of an authentic user click.

Because v1 has exactly one execution per campaign, the public key resolves that execution server-side; a second execution query key is unnecessary. A future multi-execution contract must revisit URL identity. Existing first-touch UTM and report-payment order-note plumbing remains unchanged. A landing event records validated campaign key, path without sensitive query, session, occurred_at and an idempotent page-visit ID after successful page presentation; initialization alone is not a visit. New event schema/producer work is required.

**FROZEN — PRODUCT OWNER APPROVED (P6; APPROVED AS PROPOSED).** Preserve existing first-touch attribution even when a later notification link arrives in that tab. Record a separate notification click/landing context; do not overwrite campaign_context in existing order/payment analytics. Add separately named notification attribution to future payment metadata/events. Report historical first-touch source and notification click-through source as different dimensions, not competing rewrites. A forwarded campaign URL can support campaign-link attribution but cannot prove the visitor was an original FCM recipient; label that origin separately.

## 17. Attribution Contract

**FROZEN.** Conversion requires an authoritative successful business/payment event, stable business transaction ID and validated click context at transaction creation. Carry the frozen context through provider notes/server records to verified payment processing; webhook retries must not duplicate conversions. Do not infer conversion from receipt, app launch, shared session alone, timestamp proximity or unvalidated client campaign IDs. Payment events remain financial truth; analytics counts do not replace reconciliation/refund records.

App context is owned by the authenticated user and validated delivery/actionable-click context; website campaign-link context is separately labeled and lacks per-recipient proof. Never merge anonymous web visitors with AppUser solely by campaign key. A converted transaction belongs to at most one notification campaign within the chosen attribution model. X1/X2 reports retain distinct keys even when first-touch and last-click dimensions differ.

**FROZEN — PRODUCT OWNER APPROVED (P6; APPROVED AS PROPOSED).** Start with deterministic click-through only: last explicit eligible campaign click (a validated direct actionable tap or actual CTA) or validated campaign landing in a 24-hour window before order creation. Expire context after 24 hours; a later qualifying campaign click replaces only the separate notification context. A pending order can verify later while retaining attribution fixed at creation. A generic receipt/open, NONE tap or invalid-action fallback is not qualifying click-through evidence. Under P4, a direct actionable tap is eligible only with a validated action-navigation context; it does not require a fabricated CTA event and is not proof of destination presentation. Do not infer conversion from an open alone, and do not enable view-through. Qualifying v1 conversions: verified Report, Ask Now and Subscription purchases, reported separately; feature starts are engagement, not purchases. Report-purchase plumbing is reusable; Ask Now/Subscription propagation requires new work and must display unavailable until implemented. No cross-device stitching; no revenue/refund attribution claim in v1.

**DEFERRED.** View-through, multi-touch weighting, inferred cross-device attribution and revenue allocation. Reconsider only with explicit new product approval and measurement evidence.

## 18. Metrics Contract

**FROZEN.** Every query scopes campaign/execution/source/environment. X1 and X2 never merge by audience/content. Initial counts are immutable; delivery outcome aggregates can advance with retries or evidence-backed reconciliation. Event counts expose observation completeness and as_of time.

| Metric | Definition |
|---|---|
| matched_users / eligible_targets | Frozen resolution counts from section 8 |
| suppressed | suppressed_initial + distinct frozen deliveries later SUPPRESSED; expose components separately |
| attempted | Distinct deliveries with attempt_count>0; attempts_total is separate |
| fcm_accepted | Distinct deliveries with explicit ACCEPTED provider outcome |
| failed | Distinct deliveries in FAILED_PERMANENT or INVALID_TOKEN, excluding UNKNOWN; retryable_pending separate |
| invalid_token | Subset of failed with INVALID_TOKEN; never add twice to failed |
| unknown | Distinct deliveries whose current transport outcome is UNKNOWN |
| opened | Deduplicated interaction events; channel-specific FCM and BELL totals |
| unique_opened | Distinct delivery UUIDs opened, reported separately by channel and as a union |
| action_clicked | Deduplicated CTA interaction events; unique_action_targets separate |
| destination_opened | Acknowledged destination events linked to direct-tap or actual CTA interaction IDs; unique_destination_targets separate; unobservable external opening is unavailable, not inferred |
| conversion_count | Distinct qualifying successful transaction IDs attributed by approved model and type |

Rates use the accepted delivery cohort, except acceptance itself:

- acceptance_rate = fcm_accepted / attempted.
- open_rate = distinct ACCEPTED delivery UUIDs with FCM tap / fcm_accepted. Bell rate is separately named and uses Bell-presented rows, not FCM acceptance.
- action_rate = distinct ACCEPTED delivery UUIDs with actual CTA / distinct ACCEPTED delivery UUIDs opened (FCM or Bell), with channel breakdown. This optional CTA metric is not the primary direct-navigation funnel and is not applicable where no CTA exists.
- destination_open_rate = distinct ACCEPTED delivery UUIDs with acknowledged destination presentation / distinct ACCEPTED delivery UUIDs with validated direct actionable tap or actual CTA. Report measurement coverage; do not count unobservable external opening as success.
- conversion_rate = distinct ACCEPTED delivery UUIDs with at least one attributed purchase / distinct ACCEPTED delivery UUIDs with a qualifying validated campaign click (direct actionable tap or actual CTA). Numerator must belong to that click-through cohort. Multiple purchases do not inflate this recipient rate above 100%.

Zero denominator returns null/not applicable, not 0%. Opens observed on UNKNOWN deliveries are retained but excluded from the accepted-cohort rate; they are not provider acceptance evidence. Website campaign-link conversions without recipient linkage contribute a separately labeled campaign conversion count and landing-to-conversion session rate, never the recipient conversion-rate numerator. Duplicate events are idempotently removed; repeated intentional interactions remain raw events but not additional unique targets.

Eligibility conservation: initial exclusions + eligible_targets = matched_users. Delivery state counts, including PENDING/ATTEMPTING/retryable/cancelled/expired/suppressed, partition eligible_targets. failed includes invalid_token as a subset. Do not assert attempted=accepted+failed while in-flight/unknown/retryable or previously attempted suppressed targets exist.

## 19. Bell Contract

**FROZEN.** UserNotification remains presentation. Preserve campaign_id, execution_id and notification_uuid for C items without fabricating IDs for legacy items. Deduplicate C presentation by notification_uuid/profile, never payload equality. X1 and X2 may have identical content and separate Bell items. Coordinate acceptance, Bell creation intent and analytics intent through durable delivery state/outbox; presentation failures never trigger another FCM send.

**FROZEN — PRODUCT OWNER APPROVED (P5; APPROVED WITH MODIFICATION).** Provide one coherent user-facing Bell/notification tray. AUTOMATIC_EVENT, PERSONALIZED_ALERT and ADMIN_CAMPAIGN remain separate in backend identity, execution, delivery, dedupe, metrics and business rules. Unified presentation does not require shared business storage/query scope. A source-aware presentation aggregator/adapter may merge isolated sources; C rows must not enter A/B attention budgets, selection, cooldown, dedupe, trimming/retention, trigger behavior or metrics. Retain A/B semantics, not just their displayed appearance. If compatibility tests cannot demonstrate isolation, keep C Bell integration disabled until safe; A/B behavior takes priority.

Future Bell UI is visually compact, with a preferred top-right overflow menu (such as three dots) containing **Mark all as read** and **Clear notifications**. Visible items support a subtle individual dismiss/remove action; exact swipe/context visuals are deferred to implementation/visual QA. No Mark unread in v1.

Mark all as read updates presentation/read state only. Clear hides/removes presentation for that user; individual dismiss does likewise for an item. None emits notification_opened, deletes campaign execution/delivery history, rewrites analytics, or changes accepted/failed counts. Read timestamp and channel=BELL tap remain distinct. To avoid altering A/B budgets/cooldowns through destructive row removal, clear/dismiss must use presentation-only visibility state unless an equivalent isolated mechanism is proven. Hidden items must not reappear merely because a projection retries.

The existing **Panchang evening automatic disappearance** remains an independent automatic behavior. A user may dismiss earlier; clear/read/dismiss must never replace, disable or redefine evening expiry/disappearance. Before activation, compatibility tests explicitly cover Panchang evening behavior, read/clear/individual dismiss, source-specific counts/dedupe/retention and A/B/C isolation. Campaign history remains independent of Bell visibility.

## 20. Scheduling Contract

**FROZEN.** Store timezone-aware UTC scheduled_at/expires_at; require ISO-8601 input with offset. Display explicit timezone, default Asia/Kolkata in Admin. Reject malformed dates and invalid expiry ordering rather than sending now. Scheduled approval records preview/count limits. Resolve at actual execution, claim atomically, persist lease/recovery, and run safety checks before freeze. Worker unavailable means due work remains durable and visibly overdue, not reported sent.

Cancellation before claim prevents dispatch. During execution set cancel_requested_at, stop new attempts and settle in-flight calls; accepted sends cannot be recalled. Terminal cancellation retains counts. Changing the campaign's schedule/content/audience before claim invalidates approval; claimed campaign content cannot change. Editing the referenced SavedAudience does not change the approved campaign definition. Audience edits/inactivation follow product-owner-approved P2: inactive/deactivated audiences use the existing stop/hold/reapproval rules. Count-drift hold uses PAUSED and must not silently authorize itself after waiting.

**FROZEN — PRODUCT OWNER APPROVED (P8; APPROVED WITH MODIFICATION).** When processing resumes after worker/server delay, dispatch overdue campaigns automatically if unexpired and all other safety checks pass. Lateness alone never requires reapproval, including a first start more than 60 minutes late. Preserve holds for count drift, inactive audiences and other genuine safety reasons. Record/display scheduled_at, actual_started_at, delay duration=max(0, actual_started_at−scheduled_at), and delayed/late indicator; an 08:00 schedule starting at 08:47 shows 47 minutes late without a lateness approval. Before start show current overdue duration, not an invented actual start. Default expires_at=scheduled_at+24 hours (or approved Send Now time+24 hours); valid approved configuration may choose a shorter permitted expiry. Expiry is a send-validity boundary. No new attempt starts after expiry; record in-flight results that return later and bound provider TTL to remaining validity. Terminal expired campaigns cannot be revived; clone instead. Existing A/B timing is unchanged.

**FROZEN (runtime recommendation).** Use a dedicated C worker process with PostgreSQL-backed execution/delivery polling and row-level claims; web requests enqueue and return. Use bounded internal chunks within the approved 50,000 safety ceiling; operational/load validation is required before activation, without assuming a new distributed queue is necessary. Do not select Celery merely because its scaffolding exists, or GitHub Actions as the per-campaign scheduler merely because A/B use it. Exact hosting/service configuration is DEFERRED to N5 operational validation; it must provide a long-running supervised worker and restart health checks before schedules are enabled.

## 21. Retry/Idempotency Contract

**FROZEN.** Mutation requests require an idempotency key scoped by authenticated Admin, endpoint operation and environment; store canonical request hash plus original result/reference. Reuse with identical payload returns same result; different payload returns 409. Campaign approval revision and unique execution(campaign_id) prevent new executions from repeated sends even after request-key retention expires. Unique execution/token fingerprint and unique notification_uuid protect target creation.

At most three transport attempts per delivery. Retry only conclusive retryable outcomes; exponential base delays 30 seconds then 120 seconds with bounded positive jitter up to 20%, respecting later provider retry-after and expiry. Retry exhaustion becomes FAILED_PERMANENT with RETRY_EXHAUSTED, retaining original error. Invalid tokens and permanent payload errors do not retry. Global auth/config failures stop batch progress and surface operator failure rather than exhausting every recipient.

UNKNOWN is not automatically retried. Timeout after possible dispatch and crash after external acceptance before durable commit are UNKNOWN. Reconcile only with conclusive result evidence; manual blind retry is not a v1 control. Once the execution settles, UNKNOWN yields PARTIAL and remains visible. A deliberate new campaign may reach the same user, but UI must warn it is not recovery with exactly-once guarantees.

FCM does not participate in the database transaction. Database uniqueness/leases prevent many duplicates but cannot promise exactly-once FCM/device delivery. Stable UUID supports client duplicate handling and analytics idempotency, not a claim that the provider suppresses duplicates.

## 22. All-Users Safety Contract

**FROZEN.** filters={} is a valid explicit All Users audience. Require a preview, matched/eligible counts, permission notifications.send, revision-bound confirmation, immutable approval record, server idempotency, rate/batch limits and hard no-send local/test mode. notifications.manage is insufficient to send; notifications.view controls history. No unsupported audience JSON may broaden targeting. Scheduled execution rechecks drift and cap.

**FROZEN — PRODUCT OWNER APPROVED (P7; APPROVED WITH MODIFICATION).**

- Every All Users send requires a warning and typed `SEND TO ALL USERS`, regardless of count, plus displayed audience/campaign identity.
- eligible_targets>=1,000 requires typed campaign name and eligible count and a large-audience warning.
- 10,000 is an internal processing/delivery chunk ceiling, not a campaign limit. A 24,500-target X1 may use 10,000 + 10,000 + 4,500 logical chunks while retaining one campaign, approved definition, execution and unified metrics. Smaller database and transport batches remain mandatory; a chunk is not one transaction/network call.
- Initial absolute ceiling: 50,000 matched users OR 50,000 eligible targets. If either exceeds 50,000, block activation for explicit future operational/scale review; never truncate or require artificial audience splitting at 10,000.
- After target freeze, every chunk/batch/retry uses the same frozen set, never newly resolved members.
- Send Now approval preview is at most 15 minutes old. Scheduled approval records its baseline even though it will be older at dispatch.
- At execution, pause before freeze if either matched_users or eligible_targets changes by more than max(10, ceil(20% of approved baseline)), in either direction. Any increase from zero pauses. Approval includes the absolute cap; it never authorizes an unbounded count.
- Same authorized Admin may confirm v1; two-person approval is not required initially. Changing any approval-bound content/action/criteria/schedule invalidates confirmation.

These are approved scope requirements, not implemented protection or real-send authorization. Drift reconfirmation uses fresh counts; the unchanged intent and frozen-target rules still apply.

## 23. Automatic Pipeline Isolation

**FROZEN.** N2–N8 may not change A/B trigger timing, event/Panchang selection, astrology calculations, alert entitlements, selection or attention-policy semantics. Do not call A/B builders during Admin audience resolution. Legacy NotificationLog namespace/dedupe remains outside the new C ledger. Do not use C Bell writes to consume automated budgets accidentally; section 19 freezes unified presentation with isolated backend mechanics. Clear/read/dismiss and the independent Panchang evening disappearance require explicit compatibility tests before C Bell activation.

Future telemetry can share source-qualified IDs, transport results, attempts and event schema, with source references to automatic event/alert runs rather than fabricated Admin campaigns. A/B migration to this measurement architecture is DEFERRED and is not a prerequisite for C. A future transport migration requires separate payload/content/timing, dedupe, cooldown, invalid-token, Bell and error parity tests. N0's A/B defects are recorded debt, not authorization to fix them during N1/N2.

## 24. Database Architecture Proposal

**FROZEN (logical architecture; no models/migrations created).**

| Table / extension | Minimum responsibilities / constraints |
|---|---|
| notification_jobs extended | Existing internal PK; unique public campaign key; source/contract_version; saved_audience_id; approved criteria/schema/hash; title/body/action and registry version; draft revision; state/hold reason; UTC schedule/expiry; creator/approver/time; approved preview/count envelope; cancellation markers. Preserve legacy audience/payload separately |
| notification_executions new | UUID PK, unique campaign_id FK; state/lease owner/generation/until; resolved/frozen/actual_started_at/finish timestamps; scheduled baseline, delay duration/late indicator; criteria hash/resolver version; immutable eligibility counts; durable bounded-chunk progress and aggregate outcomes; terminal reason |
| notification_deliveries new | UUID PK, execution FK, unique notification_uuid, user/profile association; encrypted token snapshot and keyed fingerprint; state/reason; attempt_count/next_attempt_at/attempt timestamps/provider ID. Unique(execution_id, token_fingerprint), unique(execution_id, user_id) for v1 |
| notification_delivery_attempts new | Append-only per-attempt outcome journal; unique(delivery_id, attempt_number), unique attempt UUID; lease generation/deadline/outcome/sanitized error/provider result |
| notification_outbox new | Durable Bell/event projection intents, unique logical event key, retry state; commits with authoritative delivery transitions |
| notification_request_keys new or equivalent durable store | Admin/operation/environment/key uniqueness, request hash and replay result; not a transport dedupe substitute |
| Bell presentation extension/adapter | Source-qualified C identity, read/hidden/dismiss state, unique C notification UUID/profile; aggregate one user-facing feed without inserting C into A/B business queries or destructively clearing rows used for A/B behavior |
| Activity Events schema/projections | Versioned execution/channel/direct-tap or CTA fields, ownership validation, stable event dedupe; lightweight user-linked interaction projection for 12 months and non-identifying campaign aggregates for 24 months, independent of 90-day technical logs |

Attempt journal and transactional outbox are the small reliability additions needed beyond the expected three entities. Do not hide provider acceptance gaps behind best-effort Bell events. Initial suppression reasons can be aggregate counts; no separate persisted SavedAudience membership table is required. Eligible targets are materialized only under execution.

Indexes: campaign(state,scheduled_at), execution(state,lease_until), delivery(execution_id,state,next_attempt_at), delivery(user_id), attempt(delivery_id,attempt_number), outbox(state,next_attempt_at). Delivery→execution→campaign references enforce ownership. Account/profile deletion nulls or pseudonymizes restricted identity references according to approved retention/deletion policy while preserving aggregate campaign facts; foreign keys must not block existing account deletion. Cryptographic key storage/access is an implementation prerequisite; raw token snapshots never enter logs/API.

**FROZEN — PRODUCT OWNER APPROVED (P9; APPROVED WITH MODIFICATION).** Layered retention:

| Layer | Retention and boundary |
|---|---|
| Campaign aggregate/history | 24 months: campaign/audience identity and approved criteria, content/action metadata, counts, acceptance/failure/open/destination/conversion aggregates/rates, scheduled versus actual timing/delay and permitted non-sensitive segmentation |
| User-level campaign interactions | 12 months: appropriately scoped user-linked open, destination engagement and qualifying conversion facts for future Customer360/content/timing intelligence, subject to deletion/privacy |
| Technical delivery/attempt logs | 90 days: retries, provider outcomes/errors and operational/debug records; not long-term behavioral storage |
| Raw/encrypted token snapshots | Erase after execution terminalization; cleanup complete within 24 hours, never retained as behavioral history |

Retention durations run from execution terminalization for campaign/technical layers and from occurrence for user interaction facts. Retention is a storage scope, not permission to invent future automated targeting rules. Preserve required non-secret identity/interaction linkage in a lightweight projection before technical logs expire; do not retain raw tokens/provider debug data or cascade-delete 12-month interactions with 90-day technical rows. Preserve approved aggregate history independently. After technical-log expiry, terminal campaign guards and retained execution identity still prohibit resend; no historical target re-resolution is allowed.

Account deletion/privacy removes or pseudonymizes user-linked facts where required; permitted non-identifying aggregates may remain. Bell clear/dismiss/Panchang disappearance never deletes analytics/history. Content/criteria remain access-restricted. Outbox, Activity Events and backups must follow consistent layered retention/deletion, not contradictory parallel policies. Request-key replay remains 30 days; token fingerprints are technical data and are not copied into long-term behavioral projections.

## 25. API Contract

**FROZEN.** Browser → Next Admin BFF `/api/admin/notifications/...` → Flask `/admin/api/notifications/...`. No direct browser→Flask Admin call. Use existing server-side Admin session/token conventions, CSRF/origin protection for mutations, authenticated authorization at both layers, bounded inputs, cursor pagination and no tokens/credentials in responses. Old `/api/notifications` endpoints are not the new C API.

| Flask route | Contract |
|---|---|
| POST /admin/api/notifications/preview | audience_mode/id, optional draft revision; return snapshot/hash/time, exclusive counts, policy version and blockers; no campaign send or persistent member list |
| POST /admin/api/notifications | Create DRAFT only: explicit audience, title/body, validated action, optional schedule/expiry proposal; no implicit send |
| GET /admin/api/notifications | Cursor-paginated campaign summaries, source/status/date filters; distinguish legacy rows |
| GET /admin/api/notifications/{id} | Revision, approved intent, execution, counts, holds, scheduled_at/actual_started_at/delay/late indicator, capabilities; no raw target tokens |
| PATCH /admin/api/notifications/{id} | Optimistic revision; only unclaimed draft/editable states; invalidates preview/approval |
| POST /admin/api/notifications/{id}/send | Preview reference/hash, revision, confirmation facts, idempotency key; approve immediate READY; 202 reference, no synchronous FCM |
| POST /admin/api/notifications/{id}/schedule | Same approval contract plus UTC schedule/expiry; transition SCHEDULED; 202 |
| POST /admin/api/notifications/{id}/cancel | Idempotent cancellation request; returns durable state, no recall claim |
| POST /admin/api/notifications/{id}/reapprove | Clears reviewable pre-freeze hold for unchanged intent; fresh preview/limits; no reopening terminal campaign |
| POST /admin/api/notifications/{id}/clone | New DRAFT/public key; no copied approval/execution/metrics |
| GET /admin/api/notifications/{id}/metrics | Defined campaign/execution cohort, time/environment and availability flags |
| GET /admin/api/notifications/{id}/deliveries | Restricted cursor-paginated technical outcome history within 90-day retention, redacted identity, no raw token; expired detail is unavailable, not zero |

Validate title/body nonblank with initial lengths bounded by existing 200/500-character columns plus serialized byte limit. Raw FCM payload edits are not supported. 400 malformed input; 401/403 auth; 404 missing entity; 409 revision/state/idempotency conflict; 422 invalid criteria/action/policy prerequisite; 503 resolution dependency unavailable. Preview never returns 200 with zero counts on dependency failure. Confirmation reference binds revision/criteria/action/content/counts, not just a client checkbox. No real send/test-send capability is introduced in N2.

Future authenticated user Bell API behavior must support one source-aware list, mark-all-read, clear presentation and individual dismiss scoped to the user. Those mutations change read/visibility only, emit no open event and cannot delete delivery history or alter A/B business state. No Mark unread operation in v1. Exact route wiring is an implementation detail; no API is created here.

## 26. Admin UI Contract

**FROZEN.** Future screens: Notifications list/history; create/edit draft; SavedAudience selector; recipient eligibility preview; title/body; versioned action selector; Send Now/Schedule; confirmation; campaign detail/metrics with execution and redacted delivery outcomes. Show audience definition versus live preview date, criteria snapshot difference, timezone, policy blocks, count drift and all-users flag.

Terminal detail offers “Create new campaign from this,” not a resend button. UNKNOWN is visible and not shown as failed/delivered. Simulated results have a persistent local/no-send label. Unsupported metrics show unavailable, never fabricated zero. Action destinations are product names, not internal Flutter routes. Warnings/confirmations follow approved P7. UI must distinguish absent dedicated marketing preferences (not a blanket eligibility block) from explicit applicable denial/opt-out and genuine policy failures; it must not label token capability as marketing consent. The user-facing Bell follows approved P5: compact overflow menu for Mark all as read/Clear notifications, subtle individual dismiss, no Mark unread, and independent Panchang evening disappearance. C integration remains disabled until isolation tests pass. Campaign detail displays scheduled_at, actual_started_at, delay and late indicator without demanding lateness-only reapproval. Display 24-month campaign aggregates, 12-month interaction history where authorized and 90-day technical detail as distinct retention layers.

## 27. Scale Contract

**FROZEN — PRODUCT OWNER APPROVED (P7 scope).** Support one campaign/execution up to the initial absolute ceiling of 50,000 matched users or eligible targets; exceeding either blocks activation for operational/scale review. Never silently truncate. A 10,000-target internal logical chunk ceiling does not split campaign identity or require Admin to author multiple audiences. Example 24,500 = 10,000 + 10,000 + 4,500 under one frozen execution with one aggregate metrics surface.

Current shared resolver materializes an ordered users.id list; this is evidence, not proof of scalable streaming. Before scale activation, a bounded count/keyset/streaming seam must reuse the exact shared SQL filter semantics and pass frozen Users regression checks. No duplicate astrology engine, N+1 profile query or unbounded full-model load. Resolve one consistent membership/identity snapshot; write non-sendable target staging in small committed batches under that resolution generation, then atomically freeze only metadata after complete validation. Partial staging cannot dispatch; interrupted pre-freeze resolution may restart, but post-freeze batches never re-resolve. Do not use a single giant 50,000-recipient write transaction or network call.

Bulk UID/profile/token lookup at most 500 IDs per database batch; delivery/transport work batches at most 100 with section 12 concurrency/rate/deadline limits. Logical 10,000 chunks contain these smaller operations. Durable progress and claim ownership resume the same targets after interruption, with aggregate metrics independent of chunk boundaries. No database transaction spans FCM calls. Preview uses exact counts and bounded redacted samples; metrics uses indexed aggregates rather than full payload scans.

N7 synthetic tests cover 100, 1,000, 10,000, 24,500 and 50,000 targets plus rejection above 50,000; prove one campaign/execution across chunks, duplicates, frozen-target retries, timeouts, crash/reclaim and count conservation. No throughput SLA or capacity claim before measurement. **DEFERRED:** raising the ceiling, 100,000+ campaigns, partitioning/distributed queues/multi-region workers until evidence and explicit review justify them.

## 28. Migration/Compatibility Risks

**FROZEN.** N0 found canonical/local notification_logs with string event_id and no composite unique constraint, versus stale model/migration integer/unique assumptions; Job creation provenance was not found. Before future schema work, inspect actual authorized local schema, migration heads/history and representative legacy fixtures. Document an explicit compatibility/baseline plan; do not stamp migrations, coerce IDs, deduplicate/delete logs or add uniqueness blindly. New C uniqueness lives in new execution/delivery tables, not a repair of A/B logs by assumption.

Use source/contract_version to keep new C jobs out of legacy process_due_jobs and send-now. New APIs must reject legacy resume/convert-by-guess. Existing logs/events are not backfilled into invented execution histories. Historical metrics remain labeled legacy/partial. Older Flutter versions need safe generic detail fallback; new action activation requires tested capable clients or a safe display-only compatibility policy. No arbitrary raw route fallback may bypass the registry.

N0 language-field/test-builder defects, topic reachability, unsafe legacy sender commits, Bell dedupe and workflow-comment discrepancies remain recorded debt. Address only explicitly scoped C seams in later work; no opportunistic A/B fixes. Migration/model changes, including outbox and applicable preference handling, require their own implementation phase and tests. Unified Bell activation requires explicit A/B isolation and Panchang evening-disappearance regression tests, including manual clear/read/dismiss. Layered retention must not cascade technical-log deletion into longer-lived interaction/aggregate history or keep token snapshots for that purpose.

## 29. N2–N8 Execution Plan

**FROZEN.** No stage implies authorization for production/Firebase activation.

| Phase | Work and acceptance gate |
|---|---|
| N2 | Notification-owned SavedAudience adapter and read-only eligibility preview; synthetic preference cases covering absent records without blanket suppression and explicit denial/opt-out, null/missing bridges, duplicate-token groups, resolver parity, count conservation, dependency failures and proof of no sender import/network. No real sends or send button activation |
| N3 | Approved policies, campaign draft/action schema and BFF/UI; schema provenance review before scoped migrations; preview/confirmation contracts, approved P1 applicability/opt-out handling without a mandatory pre-existing marketing opt-in foundation. Initial Flutter typed direct-destination/NONE-detail/fallback compatibility can be built/tested here |
| N4 | Execution/delivery/attempt/outbox, atomic claim, no-send transport, durable retries/UNKNOWN/cancellation, Send Now enqueue with all safeguards. Stable identity and minimum open instrumentation precede activation; tests remain simulated |
| N5 | Dedicated worker/scheduling, UTC, automatic unexpired late dispatch and delay observability, expiry/drift holds, lease recovery; validate runtime design locally without deployment |
| N6 | Detail/history/metrics, idempotent app interactions, landing events and approved purchase attribution. Unified user-facing Bell with isolated backend/read-clear-dismiss mechanics and Panchang regression gate; unavailable conversion paths remain labeled |
| N7 | Synthetic scale/failure tests through 50,000, including 24,500 across bounded chunks and above-ceiling rejection, layered retention/deletion, security, preference/threshold enforcement and A/B noninterference. Transport parity only if explicitly in scope |
| N8 | End-to-end local regression, frozen Users/Audiences parity, all three pipeline boundaries, direct/fallback UI actions, Bell clear/read/dismiss and Panchang evening disappearance, schedules/delay/history/rates, no-send evidence and release limitations. Separate later authorization governs actual activation |

N2 likely additions: notifications/saved_audience_recipient_resolver.py, notification preview route/BFF only if scoped, and test_notification_saved_audience_resolver.py. Read/reuse modules/services/{saved_audience_service,saved_audience_criteria,admin_users_service}.py and identity models; do not fork their semantics. P1 eligibility and P2 definition/membership semantics are approved; dependent references must use those policies. P1–P10 are approved and form the authoritative N2–N8 scope. This documentation update authorizes no implementation or Firebase activation. Stop after document verification: do not begin N2 or Language Filter work.

## 30. Explicit Frozen Decisions

**FROZEN — PRODUCT OWNER APPROVED.** P1 is approved with modification: first-party relevance-driven engagement, no mandatory separate marketing opt-in record, respect explicit applicable denial/opt-out and all technical exclusions, with no P3 destination expansion. P2 is approved as proposed: audience reference plus approved criteria JSON/schema/hash, live send-time membership and immutable post-freeze retry targets. P3 is approved with modification: exact Jyotishasha website hosts in a constrained WebView, plus explicitly validated Jyotishasha YouTube destinations through safe external handling; no arbitrary external links. P4–P10 are also approved: direct validated destination with safe fallback; unified Bell with backend isolation; deterministic 24-hour click-through attribution; 1,000 warning/10,000 chunk/50,000 ceiling; automatic unexpired late dispatch with delay visibility; layered 24-month/12-month/90-day/token-24-hour retention; single current token v1. This freezes the complete N1 scope/contract, not implementation or sending authorization.

**FROZEN.** Three separate business pipelines; users.id canonical membership and non-null UID bridge; AppUser token authority; fail-closed explicit audience mode; live send-time membership with immutable post-freeze targets; X2=new campaign and retry=same execution; per-delivery UUID; separate campaign/execution/delivery/attempt states; provider acceptance is not device delivery; UNKNOWN preserved; bounded provider interface with no business commits; hard no-send local/test environment; atomic claims/leases/idempotency; typed action registry; no recipient PII in URLs; separate transport/interaction/conversion state; Bell not history; UTC scheduling; BFF-only Admin access; bounded batches/no N+1; no A/B behavioral migration; no implied production activation. Technical defaults and API/table contracts in FROZEN blocks are part of this architectural baseline, subject to measured operational validation without weakening safety.

## 31. Explicit Deferred Decisions

**DEFERRED.** Multi-device storage/fan-out (v1 exclusion approved under P10); recurring/multiple-execution campaigns; explicit snapshot-membership targeting; Admin EVENT/TRANSIT typed resources; Horoscope/Compatibility/Muhurat destinations; browser return links and the exact approved-YouTube validation mechanism until N3 verifies authoritative channel identity/URL forms (YouTube destination permission itself is approved under P3; arbitrary external hosts remain prohibited); view-through/multi-touch/cross-device attribution; revenue/refund allocation; A/B migration to the new ledger/transport; distributed queue/100,000+ scale; detailed hosting deployment configuration until N5. Out-of-scope capabilities must not be described as supported by v1. Verified YouTube validation, hosting configuration and subtle dismiss visuals are implementation/QA details to resolve within their specified phases, not outstanding P1–P10 product approvals.

## 32. Open Questions Requiring Product Owner Decision

None remain for P1–P10. All are **FROZEN — PRODUCT OWNER APPROVED**. No unresolved contract contradiction prevents N1 freeze. Implementation evidence gates (YouTube identity validation, schema provenance, Bell/Panchang parity, bounded scale tests and runtime validation) remain prerequisites within separately authorized phases; they are not product approval questions or activation permission.

| ID | Decision / approval status | Dependency |
|---|---|---|
| P1 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: first-party relevant Jyotishasha engagement; no mandatory separate marketing opt-in record; respect explicit applicable denial/opt-out and technical exclusions | Section 8 governs eligibility; absent dedicated records do not cause blanket suppression; no third-party advertising or P3 destination expansion |
| P2 | FROZEN — PRODUCT OWNER APPROVED; APPROVED AS PROPOSED: approved criteria snapshot/hash remains stable; membership resolves live; active audience required and deactivation stops remaining dispatch | Sections 5–6 and 20 govern definition, live membership, frozen-target retries and safe stop/hold/reapproval |
| P3 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: exact jyotishasha.com/www.jyotishasha.com website hosts in constrained WebView; explicitly approved Jyotishasha YouTube destinations via safe external app/browser handling | Backend-authoritative destination validation; verify channel identity/URL forms and allowlist mechanism in N3; no arbitrary YouTube/external URLs or P4 change |
| P4 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: direct validated APP_DEEP_LINK/WEB_URL; NONE or unsafe/unavailable action opens Detail | Tap is not destination acknowledgement; no synthetic CTA event |
| P5 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: one user-facing Bell with isolated A/B/C mechanics | Compact read/clear menu, individual dismiss, no Mark unread; preserve Panchang evening disappearance; compatibility gate before C activation |
| P6 | FROZEN — PRODUCT OWNER APPROVED; APPROVED AS PROPOSED: 24-hour deterministic last eligible click/landing attribution, separate first-touch UTM; verified Report/Ask Now/Subscription counts | No view-through/cross-device/revenue inference; freeze at order creation and preserve through verification |
| P7 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: All Users typed confirmation; >=1,000 warning; 10,000 chunk ceiling; 50,000 absolute matched/eligible ceiling | <=15-minute immediate preview; drift >max(10,ceil(20%)) either direction or zero→positive pauses with fresh reconfirmation; same Admin may confirm; frozen targets across chunks |
| P8 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: automatic late dispatch if unexpired and safe; no lateness-only reapproval | scheduled/actual start, delay and late indicator; default 24-hour expiry or approved shorter validity |
| P9 | FROZEN — PRODUCT OWNER APPROVED; APPROVED WITH MODIFICATION: campaign history 24 months; user interactions 12 months; technical logs 90 days; token snapshots erased within 24 hours of terminalization | Privacy/account deletion and outbox/event-ledger/backup consistency; Bell operations never delete history |
| P10 | FROZEN — PRODUCT OWNER APPROVED; APPROVED AS PROPOSED: single current authoritative AppUser token/device slot | No multi-device registry/fan-out promise; ambiguous ownership safeguards retained |

## PRODUCT OWNER DECISIONS REQUIRED

None. P1–P10 are FROZEN — PRODUCT OWNER APPROVED. Approved as proposed: P2, P6, P10. Approved with modification: P1, P3, P4, P5, P7, P8, P9.

This is the authoritative implementation scope for separately authorized N2–N8 tasks. Implementation is not complete or started by this freeze. Do not start N2, Language Filter, application startup, code/model/migration/API/UI/Flutter work, Firebase changes, production access or sending. No commit, push or deploy is authorized.

NOTIFICATIONS N1 ARCHITECTURE CONTRACT:
FROZEN — PRODUCT OWNER APPROVED
