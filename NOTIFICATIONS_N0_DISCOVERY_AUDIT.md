# NOTIFICATIONS N0 DISCOVERY & SAVED AUDIENCE ACTIVATION AUDIT

Audit date: 2026-09-08. Scope: current, uncommitted backend, Next.js frontend, and Flutter workspace. This is discovery and proposed architecture only; recommendations below are not implemented.

Evidence: source inspection, repository searches, and read-only local PostgreSQL schema/count inspection. Before database-dependent inspection, `SELECT current_database()` returned **jyotishasha_local**. The connection was restricted to read-only transactions and a loopback database. No application startup, notification API invocation, Firebase call, production access, migration, or push test was performed. Historical local event rows do not prove real delivery. Deployment enablement, provider dashboards, production data, and actual device behavior were deliberately not inspected.

Backend links below are relative to this report; frontend and Flutter links point to sibling repositories. Existing uncommitted work was preserved. The only N0 file addition is this report.

## 1. Executive Summary

Saved Audiences are ready to supply dynamic **users.id** membership, but the notification system is not yet a safe Saved Audience campaign execution system. There are separate Admin Job, scheduled event, and personalized alert pipelines. The latter two must remain operationally separate during this workstream.

`NotificationJob` already provides a campaign-like integer identity and mutable delivery counters. It does not understand SavedAudience IDs, freeze execution facts, or maintain recipient delivery history. Its permissive audience resolver can silently broaden an unsupported audience to every token-bearing profile. Scheduled-job polling exists as a function, but no production caller was found in the inspected code.

There is no Notifications UI or notification BFF in the current Next Admin. Backend create/list/send-now APIs exist. Two transports exist: direct FCM HTTP v1 for Admin Jobs and Firebase Admin SDK for automated pushes. Neither provides the durable execution, error classification, and concurrency controls required for a safe 10,000-user campaign.

Identity and analytics are partially reusable. A per-push UUID travels through FCM taps into `notification_opened`; backend sent events can associate that UUID with a Job ID. However, campaign identity is not automatically placed in the push, Bell rows omit the generated UUID, duplicate Bell payload handling suppresses some campaign analytics, and existing metrics are aggregate rather than dependable X1/X2 reports. Website report-payment UTM attribution already exists, but notification campaign linkage and landing/click instrumentation are incomplete.

**N1 can proceed to architecture freeze. This does not mean sending, scheduling, or production rollout is ready.** The minimum direction is a SavedAudience adapter, a campaign/execution/delivery contract, a controlled sender, typed actions, and consistent IDs across delivery and analytics.

## 2. Existing Notification Architecture

| Pipeline | Entry/caller | Resolution and delivery | Persistent state |
|---|---|---|---|
| Admin/marketing Job | Flask create/list/send-now routes; due-job helper | Legacy AppUser filters → direct HTTP FCM | notification_jobs, notification_logs, user_notifications; best-effort activity_events |
| Daily event notifications | GitHub Actions notifications workflow → event scheduler | Events and per-profile builder; SDK personal pushes plus topic broadcasts | AstroEvents, notification_logs, user_notifications, activity_events |
| Personalized alerts | GitHub Actions alerts workflow → alerts scheduler | Entitlement-qualified profiles → alert detection/selection → SDK delivery | alert_micro_events, user_notifications, activity_events |
| Admin test-send | Separate JWT-admin endpoint | Explicit profile and token; builder/manual content → real sender | Diagnostic path, not dependable campaign history |
| App Bell | Authenticated Flutter repository → user notification routes | Read stored presentation rows, mark read | user_notifications |
| Open measurement | FCM tap → Flutter Activity Events client | Authenticated event ingestion | activity_events |

Admin campaigns do not create the scheduled festival/transit/Dasha pipeline. Automated notifications bypass NotificationJob. There is no universal campaign object spanning all these paths.

## 3. File / Component Inventory

| File/component | Purpose, caller, environment, and state |
|---|---|
| [notifications/notification_routes.py](notifications/notification_routes.py) | Flask JWT-admin Job create/list/send-now and real test-send; registered by app.py; notification_jobs |
| [notifications/notification_service.py](notifications/notification_service.py) | get_recipients, send_job_now, process_due_jobs; Job, Log, Bell, event writes |
| [notifications/notification_models.py](notifications/notification_models.py) | Canonical NotificationJob, NotificationLog, UserNotification ORM definitions |
| [notifications/notification_fcm.py](notifications/notification_fcm.py) | Direct HTTP v1 sender used by Admin Job path; credential/OAuth handling and partial invalid-token cleanup |
| [notifications/user_notification_routes.py](notifications/user_notification_routes.py) | App JWT → profile bridge; Bell list, unread count, mark-read/all |
| [services/notification_engine.py](services/notification_engine.py) | Firebase Admin SDK personal, data-only, topic transports for automated pipelines |
| [extensions.py](extensions.py), [factory.py](factory.py), [app.py](app.py) | Firebase initialization, Flask factory and blueprint registration |
| [services/event_scheduler.py](services/event_scheduler.py) | Daily personal/topic selection, pushes, Bell/log/event writes, Panchang dismissal |
| [services/notification_builder.py](services/notification_builder.py) | Festival/vrat, transit, Dasha and Panchang notification construction |
| [services/attention_policy.py](services/attention_policy.py), [services/notification_lifecycle.py](services/notification_lifecycle.py) | Shared automated push budget; Bell visibility/expiry rules |
| [.github/workflows/notifications.yml](.github/workflows/notifications.yml) | Morning, evening, dismissal cron and manual workflow dispatch |
| [.github/workflows/alerts.yml](.github/workflows/alerts.yml) | Daily personalized alerts cron/manual dispatch |
| [modules/alerts/alerts_scheduler.py](modules/alerts/alerts_scheduler.py), [modules/alerts/alert_delivery_service.py](modules/alerts/alert_delivery_service.py) | Entitlement checks, advisory lock, alert selection, SDK delivery, cooldown/Bell/event finalization |
| [celery_app.py](celery_app.py), [tasks.py](tasks.py), [cron_app.py](cron_app.py), [render.yaml](render.yaml) | Other runtime scaffolding; no wired NotificationJob worker found |
| [scripts/daily_rotation_engine.py](scripts/daily_rotation_engine.py) | Horoscope/content rotation, not a discovered push sender |
| [modules/models_notification.py](modules/models_notification.py), [models_notification_log.py](models_notification_log.py) | Stale duplicate models; differ from canonical definitions |
| [modules/models_saved_audience.py](modules/models_saved_audience.py), [modules/services/saved_audience_service.py](modules/services/saved_audience_service.py), [modules/services/saved_audience_criteria.py](modules/services/saved_audience_criteria.py) | Frozen dynamic audience storage, CRUD/preview, validation |
| [modules/services/admin_users_service.py](modules/services/admin_users_service.py) | Shared SQL filtering and resolve_user_ids; canonical users.id membership |
| [modules/auth/models.py](modules/auth/models.py), [modules/models_user.py](modules/models_user.py), [modules/user_service.py](modules/user_service.py) | User/profile identities, tokens, UID upsert |
| [modules/auth/routes_profile.py](modules/auth/routes_profile.py), [modules/auth/account_deletion_service.py](modules/auth/account_deletion_service.py) | Authenticated FCM registration and account cleanup |
| [modules/models_activity_events.py](modules/models_activity_events.py), modules/activity_events/{event_schemas,service,analytics_repository,analytics_service}.py | Event ledger, validation, insertion, aggregate notification analytics |
| [routes/routes_analytics.py](routes/routes_analytics.py) | Admin analytics endpoint, including notifications |
| [modules/payments/campaign_attribution.py](modules/payments/campaign_attribution.py), app.py payment routes | Website campaign context through provider order notes and payment verification |
| [frontend AdminNav](../jyotishasha-frontend/components/admin/AdminNav.tsx), frontend app/admin and app/api/admin | Existing Users/Audiences/Orders/App Version UI and BFF pattern; no Notifications implementation |
| [Flutter main.dart](../jyotishasha_appF/lib/main.dart) | Firebase initialization, receive/tap listeners, cold-start message handling |
| [FCM token manager](../jyotishasha_appF/lib/core/messaging/fcm_token_manager.dart) | Permission, refresh/auth subscription, token upload and logout cleanup |
| Flutter lib/core/notifications/{notification_dispatcher,notification_navigation_service,notification_opened_producer}.dart | Payload parsing, deferred navigation, FCM tap event |
| [Flutter activity client](../jyotishasha_appF/lib/services/activity_event_client.dart) | Authenticated first-party event requests |
| [Flutter backend notification repository](../jyotishasha_appF/lib/core/repositories/implementations/backend_notification_repository.dart), lib/services/notification_service.dart | Bell/token HTTP wrappers; not sender code |
| [Flutter greeting header](../jyotishasha_appF/lib/core/widgets/greeting_header_widget.dart) | Bell UI, read action and navigation |
| [Flutter app routes](../jyotishasha_appF/lib/app/routes/app_routes.dart) | GoRouter destinations, auth redirect, fallback |
| [Flutter resource router](../jyotishasha_appF/lib/core/resources/resource_router.dart), lib/features/events/{transit_article_page,authority_resource_screen}.dart, lib/core/widgets/in_app_webview.dart | Content CTA → authority WebView path |
| [Website analytics init](../jyotishasha-frontend/components/analytics/WebsiteAnalyticsInit.tsx), lib/{analyticsAttribution,anonymousActivityEventClient}.ts | First-touch UTM capture and anonymous events |
| [Website ReportCheckout](../jyotishasha-frontend/components/reports/ReportCheckout.tsx) | Carries website campaign context into report order creation |

Legacy references to previous notification phases are not evidence that this new N1–N8 Saved Audience workstream is implemented.

## 4. Admin Notification UI

No Notifications page, composer, audience selector for notifications, recipient eligibility preview, notification history screen, or monitoring screen was found in the current Next Admin. AdminNav links Users, Audiences, Orders and App Version. Existing SavedAudience preview is a Users membership preview, not a push-capable-recipient preview.

Backend APIs already exist:

| API | Actual capability and limitation |
|---|---|
| POST /api/notifications | Creates Job; requires title/body; accepts audience/payload JSON and scheduled_at. Audience defaults to all. No SavedAudience validation or action contract |
| GET /api/notifications | Latest 100, optional status; metadata and mutable counters, not execution/delivery history |
| POST /api/notifications/{id}/send-now | Synchronous real send; resets schedule to now, no terminal-status restriction or confirmation |
| POST /api/admin/notifications/test-send | Real token send for a specified profile; not a local dry run |

These are Flask JWT-admin endpoints using the admin allowlist. No notification Browser → BFF → Flask integration exists. Invalid or absent schedule text falls back to current UTC, rather than rejecting malformed scheduling input. The send-now route can catch a processing exception and still return a successful HTTP response with zero counters, obscuring failure. No API was invoked during N0.

## 5. Database Models

Actual local schema was checked, not just model comments.

| Table | Fields / role | Missing for campaigns |
|---|---|---|
| notification_jobs | id PK; title varchar(200), body varchar(500); title_hi/body_hi; type varchar(50); audience JSON; payload JSON; scheduled_at and created_at timestamp without timezone; status string; total_recipients, success_count, failure_count | No sent_at, execution identity, owner/approval record, saved_audience_id, criteria version snapshot, lease, retry state, structured failure, recipient records |
| user_notifications | id; user_id **means AppUser/profile ID**; title/body/data; is_read; created_at/read_at/expires_at | Presentation feed, not campaign delivery ledger; no required Job/UUID FK |
| notification_logs | id, profile user_id, event_id varchar(100), slot varchar(20), sent_at | No actual local composite uniqueness, delivery status, attempt history, error or provider ID |
| alert_micro_events | Profile/event unique key; state, priority, confidence, active/evaluation timestamps, severity, last_delivered_at, AI fields and triggered facts | Alert lifecycle, not an Admin campaign |
| activity_events | Event UUID, timestamps, identities/session/platform/source/environment, entity, properties, campaign_context, notification_context, dedupe support | Observation ledger, not authoritative delivery state |

Job statuses are conventional strings pending/processing/sent/cancelled/failed, not an enforced transition machine. Job can be invoked repeatedly. Payload JSON can contain arbitrary metadata, including route/URL, but no typed deep-link/URL columns or validated campaign action exist. Job audience does not store resolved member IDs.

Local indexes: Job PK and scheduled_at; notification_logs **PK only**; Bell PK plus user_id, is_read and created_at. The legacy root NotificationLog model and migration `241a028dadcd_add_notification_logs_clean.py` declare integer event_id and a unique user/event/slot constraint, whereas the active model/local table use a string and lack that constraint. No Job creation migration or later log string-conversion migration was found by the migration search. Schema provenance needs review before a future migration; nothing was repaired here.

Local inspection found no notification Jobs, zero populated tokens across 18 users and 19 profiles, and 34 notification_created plus 34 notification_sent historical activity rows. These are local fixture/history observations, not proof of active provider delivery. No device registry table was found.

## 6. Legacy Audience System

`get_recipients` starts with AppUser.fcm_token IS NOT NULL, optionally applies `zodiac` to moon_sign, `lagna` to lagna, and `subscription` to the legacy profile subscription string, then calls `.all()`. Delivery loops in Python. Empty token strings survive SQL selection but are skipped by the sender loop.

There is no strict accepted JSON schema. `mode` is ignored; documented age/interest concepts are not implemented; unknown keys are silently ignored. Supplying only a SavedAudience ID would therefore select all token-bearing profiles, not that audience. No current Job path supports canonical users.id lists or persists resolved members.

Membership is recomputed each invocation, but through different filter semantics from frozen Admin Users. Static sign fields are queried rather than recalculated; subscription filtering does not reuse authoritative entitlement semantics. This resolver must not become a second SavedAudience engine. Preserve historical JSON for old Jobs, introduce a discriminated adapter for new Jobs, and reject unsupported modes/keys rather than translating them into all users.

## 7. SavedAudience Integration Point

SavedAudience stores versioned declarative criteria and metadata, not users, profiles, UIDs or tokens. Canonical membership is **users.id**. Its validator rejects unknown criteria instead of broadening the match. Existing stored audience resolution uses `validate_criteria(..., authoring=False)`; new authoring uses `authoring=True`, including the intended category-activity distinction.

The integration point is the existing shared `modules.services.admin_users_service.resolve_user_ids` SQL filtering contract. A notification-owned adapter should load the audience, apply its lifecycle policy, validate stored criteria, resolve canonical users, bulk bridge their non-null Firebase UIDs to profiles, then apply push eligibility and token deduplication. It must reuse frozen filtering semantics without birth-chart calculations, duplicated astrology logic, or alterations to audience membership storage.

Notification previews need separate counts for matched users, missing bridge, missing token, preference suppression, duplicate target, and eligible recipients. Existing paginated member preview alone cannot provide those facts.

## 8. Identity → FCM Resolution

Required bridge: `users.id → users.firebase_uid → app_users.firebase_uid → app_users.id → app_users.fcm_token`.

User firebase_uid is unique; AppUser has a unique partial index for non-null firebase_uid. Thus one authenticated UID maps to at most one current profile under these constraints. Nullable legacy rows remain possible. Local inspection found no duplicate non-null profile UIDs. Different row counts are not evidence of multiple profiles per user.

Both tables contain tokens. `/api/users/update-fcm` verifies the Firebase ID token, updates User if present, upserts AppUser by UID and writes its token. **AppUser.fcm_token is authoritative for current delivery selection; User.fcm_token is a legacy mirror.** A Firestore user document is another client-written mirror, not the backend recipient source.

There is one token slot per profile, not a multi-device registry. A second device can overwrite the first device's token. Tokens can be null, stale, or duplicated across distinct identities; no token uniqueness or recipient-level token dedupe protects current sends. Physical multi-device use is possible but reliable delivery to all devices is not modeled.

The Bell identity helper already bridges backend JWT User to profile by UID, but does not explicitly reject a null UID before querying AppUser. The new adapter must exclude nulls rather than risk a legacy null-to-null match. Never compare users.id directly with AppUser.id.

Flutter refresh and sign-in synchronize tokens with retries. Permission must be authorized before the current registration path proceeds. Logout unsubscribes general_0 and deletes the device token; it does not clear the SQL/Firestore stored token. Account deletion has separate profile/token cleanup. Direct HTTP sender cleanup and SDK cleanup differ, as below.

## 9. Firebase Sender

**There is no single universal canonical sender today.** `services.notification_engine.send_push_notification` is the shared automated SDK sender; Admin Jobs use `notifications.notification_fcm.send_fcm`, a separate HTTP implementation.

| Concern | Admin HTTP sender | Automated SDK sender |
|---|---|---|
| Credentials | Reads FCM_SERVICE_ACCOUNT_JSON on import; invalid/missing configuration can fail import | extensions.init_firebase initializes Firebase Admin from environment credentials; skips when absent |
| Local protection | No enforced local dry-run switch | No enforced local dry-run switch |
| Sending | One token per HTTP request | One token per messaging.send; separate topic/data-only helpers |
| Batching/limits | No batching or application throughput control | No multicast/batch control in inspected helper |
| Authentication | Creates credentials and refreshes OAuth per send | Firebase Admin SDK-managed authentication |
| Timeout | requests.post has no explicit timeout | No explicit timeout policy configured in wrapper; SDK defaults were not asserted/tested |
| Retry | No retry/backoff | Two attempts for personal sends on any exception, without classification/backoff; topic/data-only no equivalent retry |
| Invalid token | On 404 UNREGISTERED clears first matching token in each SQL table and commits | No invalid-token cleanup |
| Result | Boolean; response failure logging; no persisted provider ID | Boolean; provider message ID logged, not persisted |

A token may be invalid for different reasons; only the specific HTTP cleanup path is implemented, not a comprehensive expired/invalid-token policy. Its internal commit can also commit pending caller work, weakening transaction boundaries. Neither sender can establish delivery to a device. Success means provider acceptance, not receipt/read.

Recommend a notification-owned transport adapter with a structured result, stable per-recipient ID, bounded timeout, classified retries, token cleanup and no internal business transaction commit. Converge duplicate transports only after automated parity tests; do not replace their behavior incidentally during SavedAudience work.

## 10. Scheduling System

Admin create stores scheduled_at. `process_due_jobs` selects pending due Jobs, marks processing and commits, then sends. No repository production caller was found for this helper. `render.yaml` defines a web process, not an Admin notification worker/cron. `cron_app.py` constructs an app but is not a polling schedule by itself.

Claims are not locked or atomic compare-and-set transitions. Concurrent callers can claim the same Job. A crash can strand processing state; no lease/reclaim exists. Pending jobs would wait indefinitely without an actual worker. A caught failure marks failed without a durable retry plan. Naive UTC storage and permissive parsing do not provide a clear, validated timezone contract for offset-aware input or Admin display.

Actual automated schedules in repository YAML:

| Workflow | Cron UTC | Intended IST operation |
|---|---|---|
| notifications.yml | 00:30 daily | 06:00 morning events |
| notifications.yml | 11:30 daily | 17:00 Panchang dismissal |
| notifications.yml | 12:30 daily | 18:00 evening events, using tomorrow's event date |
| alerts.yml | 02:30 daily | 08:00 personalized alerts |

Both support manual dispatch. These files prove configured code, not that hosted Actions are enabled or healthy. notifications.yml has no concurrency stanza despite a related code comment referring to workflow concurrency. Alerts have their own PostgreSQL advisory lock.

Celery/Redis scaffolding exists, but inspected tasks cover report generation, not notifications. Redis configuration requires environment setup and contains TLS verification/logging concerns; its mere presence is not evidence of a running notification scheduler. Monthly/daily content rotation and subscription-state sync are separate from Admin Job delivery.

## 11. Existing Automated Notifications

The event scheduler generates/stores event content, uses the builder for festival/vrat, personalized transit, Dasha/pre-Dasha and Panchang/Panchak, and processes profiles in batches of 500. It writes successful personal delivery logs and Bell rows and emits events. Suppressed candidates may get Bell-only rows. It trims the Bell feed to the latest ten rows per profile. That retention policy is unsuitable for campaign delivery history.

Topic broadcasts are separately limited in a run and deduped only by an in-memory set. They lack per-recipient UUIDs and equivalent analytics. Scheduler topics are constructed from event type/event ID; the inspected app subscribes to general_0, and corresponding dynamic event-topic subscriptions were not found. Topic reachability therefore needs confirmation before relying on it.

Alerts are a separate scheduler, with authoritative entitlement checks, profile detection/selection, batch processing, a dedicated advisory-lock connection and shared attention-budget checks. `alert_delivery_service` sends first, then finalizes cooldown and Bell state and emits events. This avoids conflating alerts with campaigns, but still has an external-send/database-commit crash gap. The alerts YAML exists despite an older comment saying scheduling was not enabled.

The shared automated daily push cap is two, with priority rules in attention_policy. Admin Jobs and topic sends bypass that decision path. Admin Bell writes can nevertheless affect budget counts, creating an indirect interaction. Reuse content builders, SDK abstractions, lifecycle behavior and attention-policy knowledge without moving automated selection into NotificationJob.

## 12. Campaign / Notification Identity

NotificationJob.id is the existing campaign-like identity. There is no independent immutable execution record. Each successful attempted personal Admin push gets a generated UUID in FCM data.notification_id. Backend created/sent events include that UUID plus campaign_id=str(job.id). The Job ID is **not automatically inserted into FCM data**; only caller-supplied payload fields and the generated UUID travel there.

The stored Bell data is job.payload, omitting the newly generated UUID. Bell duplicate detection compares profile and payload JSON, not Job identity. X1 and X2 with identical payload can both send a push but the later one can lose its Bell row and its created/sent events. NotificationLog uses Job ID as event_id with slot general, but is not a delivery identity model.

Flutter preserves payload fields and its opened producer can carry notification_id/campaign_id/slot. Thus **X1/X2 FCM taps can be distinguished by UUID where the corresponding sent event exists**, and the campaign can be derived by joining that event. They are not yet reliably independently measurable end to end. Topic/test paths do not provide the same chain; websites receive no automatic campaign identity.

## 13. Existing Metrics

Classification is for the inspected implementation, not hypothetical Firebase console capabilities.

| Metric | Classification | Evidence / practical limit |
|---|---|---|
| Job identifier, status, current counters | AVAILABLE NOW | Job list exposes mutable values |
| Attempted, FCM accepted, FCM failed | AVAILABLE NOW, limited | Job success/failure counters; total is success+failure for that invocation, excludes skipped; overwritten on rerun |
| True audience members at execution | REQUIRES NEW INSTRUMENTATION | Resolver prefilters profiles/tokens; no canonical member snapshot/count |
| Eligible and suppressed by reason | REQUIRES NEW INSTRUMENTATION | No durable eligibility breakdown |
| Invalid-token count per campaign | NOT RELIABLY AVAILABLE | Partial cleanup and logs, no structured recipient outcome |
| Created/sent event totals | AVAILABLE NOW, limited | Best-effort events tied to new Bell rows, not every provider attempt |
| FCM device receipt | NOT RELIABLY AVAILABLE | Acceptance is not delivery; no first-party acknowledgement ledger |
| FCM tap/open event | AVAILABLE NOW, partial | notification_opened for authenticated FCM tap callbacks |
| X1/X2 opens linked to Job | DERIVABLE, partial | Join opened UUID to sent UUID/campaign; missing events and no reliable campaign cohort aggregation |
| Unique recipient open rate | REQUIRES NEW INSTRUMENTATION / aggregation | Must dedupe and use an execution acceptance cohort |
| Bell item opened | REQUIRES NEW INSTRUMENTATION | Mark-read is not a campaign open event |
| CTA clicked / destination successfully opened | REQUIRES NEW INSTRUMENTATION | No notification-specific acknowledgement after navigation |
| Website landing visit | REQUIRES NEW INSTRUMENTATION | Attribution initializer stores context but does not emit page_view |
| Ask Now started / subscription purchased attributable to push | REQUIRES NEW INSTRUMENTATION | Feature/payment events lack propagated notification attribution |
| Website report payment verified by UTM campaign | AVAILABLE NOW for existing UTM flow | Provider notes preserve campaign context; notification link mapping is not automatic |
| Report purchase attributable specifically to X1 | DERIVABLE only with explicit campaign mapping | Existing UTM campaign must identify X1 and survive first-touch semantics; no current automatic notification funnel |
| Campaign revenue, refunds and other conversions | NOT RELIABLY AVAILABLE | Event counts are not financial truth; no complete notification revenue contract |

`GET /admin/api/analytics/notifications` supports date window/platform, not campaign filtering. It reports aggregate created/sent/opened/users-opened and opened/sent rate. Its service filters environment=production; no call was made in this local audit. This rate is not a deduplicated X1 acceptance-cohort rate and can mix repeated opens and differently timed sends.

## 14. Flutter Receive / Tap Flow

| App state/action | Source-observed behavior |
|---|---|
| Foreground onMessage | Increments notification state when context is available, handles Panchang dismissal; no local visible-notification display implementation found in this handler |
| Background handler | Initializes Firebase, logs message information, handles data-only dismissal; does not count an open merely on receipt |
| Background notification tap | onMessageOpenedApp → handleNotificationTap → dispatcher → opened event → navigation service |
| Terminated notification tap | getInitialMessage via startup handling → same tap flow; navigation may queue until dashboard/router ready |
| Normal launch | Does not emit notification_opened through this path |
| Bell tap | Parses stored row, marks read, refreshes feed/count, navigates; does not call opened producer |

The dispatcher understands type, event_id and route while preserving original payload. The navigation service returns to dashboard before opening a target and queues early taps. It does not deduplicate by notification ID or confirm successful destination display to analytics. Open emission happens before navigation, so it measures tap callback handling, not destination success.

Activity event sending needs authenticated context/backend JWT, is best-effort with a bounded request, and has no durable offline retry queue. Cold-start/auth timing can drop measurement. Background OS notification presentation was not device-tested. Unsupported routes reach router fallback; some existing routes expect a different extra type than the notification navigation service provides.

## 15. App Deep-Link Capability

Internal notification navigation exists, but there is no complete typed Admin deep-link contract. Payload `route` is accepted as a raw internal route. `screen`, `deep_link`, `click_action`, and arbitrary parameters are not a generic interpreted contract.

| Destination | Existing registered route / limitation |
|---|---|
| Ask Now | /asknow |
| Kundali | /kundali/overview |
| Reports | /reports |
| Subscription | /subscription |
| Profile | /profile |
| Dashboard, Astrology, Darshan | /dashboard, /astrology, /darshan |
| Event and transit detail | /event, /transit-article; dispatcher provides their payload context |
| Generic notification detail | /notification-detail; fallback for custom/alert/Dasha types |
| Astrology detail | /astrology/detail expects a Map extra; raw notification route use can be incompatible |
| Horoscope | Existing Navigator-based entry via Today's Essentials; no dedicated named route in inspected router |
| Compatibility | Existing Navigator-based LovePartnerFormPage entry; no dedicated named route in inspected router |
| Muhurat | No dedicated named notification destination in inspected router; this is not a claim that the feature is absent |

Android manifest has no inspected VIEW/BROWSABLE app-link intent filter; iOS search found no associated-domain/custom URL scheme declaration. Internal push routing does not establish website-to-app universal-link capability.

Recommend NONE / APP_DEEP_LINK / WEB_URL with an allowlisted, versioned action registry and typed parameters. Admin should choose supported product destinations, not type GoRouter paths. NONE needs an explicit display-only behavior decision. Invalid actions need a safe detail fallback and measurable rejection without arbitrary route execution.

## 16. Website / Landing Page Capability

An existing transit article CTA can read payload.url, construct an authority resource, and open AuthorityResourceScreen → InAppWebView. Events also use resource routing. This can display a website/landing page, but it is not a universal custom-notification WEB_URL action or automatic URL launch on push tap.

The WebView allows parsed HTTP/HTTPS URLs, enables JavaScript and permits navigation without a trusted-host allowlist. Other app features use url_launcher, but that does not supply a generic notification browser contract. No campaign tracking bridge or confirmed web-to-app return contract was found.

Website attribution captures utm_source/utm_medium/utm_campaign plus normalized referrer as first-touch sessionStorage context. The initializer itself emits no landing-page event. A new notification_campaign_id query parameter would currently be ignored by that contract. A future opaque, non-PII campaign key could map deliberately into existing utm_campaign, or be added through an explicit schema change. Never place users.id, Firebase UID, FCM tokens or sensitive audience criteria in destination URLs.

N1 should freeze HTTPS/host validation, redirect handling, browser choice and campaign query preservation. They are not implemented safeguards today.

## 17. Open / Click Tracking

`NotificationOpenedProducer` emits notification_opened on FCM tap, with allowlisted notification_id/campaign_id/slot context. The backend ingestion supports that event and derives authenticated identity. Normal app launch does not emit it from this flow, so normal launch versus notification tap is distinguishable **when ingestion succeeds**.

There is no opened-producer idempotency key, no durable queue, no Bell-open equivalent and no separate CTA-click event. Firebase analytics navigation observers exist, but provider console data was not accessed and cannot be claimed as an existing per-Job funnel. UUID preservation supports partial X1/X2 distinction; it does not repair missing backend send events or infer a successful destination view.

Bell mark-read endpoints update is_read without populating read_at through the available model helper. Read state and notification_opened therefore should not be treated as interchangeable measurements.

## 18. Conversion Attribution

The first-party Activity Events schema already has notification_context {notification_id, campaign_id, slot} and campaign_context {utm_source, utm_medium, utm_campaign, referrer, medium}. Those are useful integration points; they do not automatically propagate context to subsequent feature/payment actions.

Flutter's tap producer supplies notification context to that event only. Ask Now and other feature producers do not automatically inherit it. Session identity alone is not a defined conversion attribution rule. A same-session correlation could be exploratory analysis, not dependable notification conversion truth.

**Existing website report-payment attribution must be preserved:** ReportCheckout forwards first-touch campaign context to order creation; backend campaign_attribution sanitizes and stores it in Razorpay order notes; verified/failed payment processing recovers it for Activity Events. Existing campaign analytics can count verified report payments by UTM campaign. That is real reusable capability, not a complete notification funnel. There is no automatic Job→URL campaign mapping; later campaign URLs in an already-attributed tab may retain the previous first touch. Landing path is stored internally but not emitted as a visit by the initializer. Anonymous event ingestion lacks notification_context.

Subscriptions and Ask Now purchases lack equivalent demonstrated notification propagation. Revenue attribution is not supplied by these event counts. N1 must decide click-through versus view-through, first/last touch, TTL/window, repeated opens, cross-session behavior, app/WebView identity and payment/refund truth. Do not infer conversions solely because they happened after an open.

## 19. Dynamic Audience Send-Time Semantics

Dynamic criteria and membership resolution must remain entirely owned by SavedAudience/shared Users filtering. Notification history must not modify or materialize audience membership on the SavedAudience row.

For X1, resolve current users at execution start and freeze counts/results on its execution. If 40 match and 36 are eligible, retain both facts and suppression reasons. For later X2, run the same criteria against current data: 46 matching users produces a new execution record and new campaign identity, without rewriting X1's 40/36 history.

Distinguish changing user data from editing the audience definition. Recommended N1 policy: retain audience reference and an approved criteria version/hash plus snapshot on the campaign, then evaluate that approved definition against live user data at send time. If the product instead wants the latest edited definition, require an explicit reapproval rule. This policy choice remains for N1 freeze; neither is implemented by current Jobs.

## 20. Scheduled Audience Semantics

**Resolve at SEND TIME.** A preview of 40 today is advisory; Friday's actual execution can resolve 55. Do not store preview recipients as future membership by accident. A future explicitly labeled snapshot mode would be a separate feature.

The current legacy resolver runs when send_job_now executes, so live evaluation is conceptually compatible. However, SavedAudience resolution and a dependable scheduled worker are absent. N1 must specify UTC storage and timezone display, due-time tolerances/expiry, cancellation, inactive/missing audience handling, criteria-edit policy, and a durable claim.

Resolve membership once per claimed execution and retain its delivery targets. A retry resumes that execution's unfinished targets; it must not silently add newly matching users. A fresh campaign X2 may resolve a different population. Current repeated Job sends do not preserve this boundary.

## 21. Delivery History Architecture

Extend NotificationJob as campaign metadata rather than discard its identity. Add explicit execution identity/state and recipient-level delivery records. Even if one-off Jobs initially have one execution, separating execution semantics prevents retries from becoming a new campaign or changing its membership.

Minimum execution facts: campaign/audience references, approved criteria version/hash/snapshot, content/action version, resolved_at, scheduled/start/finish times, initiating/approving Admin, resolved-user count, eligibility exclusions, unique targets, attempted/accepted/failed/unknown counts and state transitions. These belong to notification execution, not SavedAudience.

Minimum recipient facts: execution, canonical user/profile association, stable notification UUID, deduplicated delivery target reference/fingerprint, status, attempts/timestamps, provider response/message ID when available, structured error class and retry disposition. Actual token access must remain restricted; hashing alone cannot be used to send. Choose token rotation/revalidation behavior explicitly and avoid exposing raw tokens in Admin/history.

**A new recipient-level delivery table is needed.** Bell is truncated presentation state, NotificationLog is an inadequate success guard, and Activity Events are best-effort observations. None is the authoritative campaign delivery ledger. X1/X2 reports should aggregate immutable executions and join deduplicated actions/conversions by stable campaign/delivery identities, preserving acceptance versus receipt terminology.

## 22. All-Users Safety

SavedAudience filters={} deliberately means All Users. Existing notification audience omission also defaults broadly, and unknown legacy filters can broaden unintentionally. JWT-admin gating is present, but no recipient preview, explicit all-users acknowledgement, campaign approval record, size limit, dry-run enforcement, campaign-specific permission or robust send idempotency exists.

Before enabling send, require validated audience mode, visible resolved/eligible counts, explicit all-users and large-count confirmation, a permission check, approved content/action, bounded rate/batches, server-side idempotency and a local/test transport that cannot reach real tokens. Detect material count drift between preview and execution with a defined pause/approval threshold. Scheduled campaigns must apply these controls at execution as well as creation.

These are recommended future product controls, not an N0 permission request or implemented behavior.

## 23. Retry / Idempotency

| Failure scenario | Current behavior / gap |
|---|---|
| Firebase unavailable | HTTP returns failure or can block without explicit timeout; SDK repeats immediately; no durable classified retry |
| Token invalid/expired | Limited HTTP UNREGISTERED cleanup; SDK no cleanup; no consistent per-target reason |
| Partial failure | Admin counts success/failure but marks Job sent even if all attempts failed; no recipient retry ledger |
| Crash after provider acceptance before commit | Successful push may have no success log; retry can duplicate it |
| Retry same Job | Existing committed profile/job/general log skips success; failed or newly matching profiles can be attempted; counters overwritten |
| Two workers / repeated send-now | Query-then-insert guard races; actual local log table lacks uniqueness; terminal Jobs can be invoked |
| Crash while processing | No lease/reclaim; can remain processing indefinitely |
| Topic rerun | In-memory dedupe resets; no durable per-topic execution guard |

Alerts' advisory lock is a useful pattern but does not protect Admin Jobs or close the external-provider transaction gap. The shared Log's event_id/slot namespace is not a substitute for typed campaign identity.

N1 needs atomic claiming, stable delivery IDs, database uniqueness, retry eligibility/backoff/expiry, cancellation boundaries and an explicit uncertain-outcome state. Do not promise exactly-once device delivery: a timeout after external acceptance cannot be made atomic with a local database transaction. SDK retries on every exception can also repeat an ambiguously accepted request.

## 24. Privacy / Notification Preference

OS permission is requested by Flutter. Token registration and refresh exist. No inspected application-level marketing opt-in/out, category preference registry, durable OS-permission-state model or consent-based campaign exclusion was found.

OS authorization, token existence and marketing preference are three different facts. Existing AppUser token presence establishes only a technical delivery candidate. Logout leaves server token state stale until replacement/cleanup; invalid token handling differs by transport. N1 must define eligible preferences and suppression rules before marketing activation, plus recipient-record retention/deletion access rules consistent with account deletion. No consent status was inferred for real people.

## 25. Scale Assessment

This is static assessment, not a load benchmark. No real sends or populated-token tests were run.

| Scale | Assessment |
|---|---|
| 100 users | Computationally plausible for a controlled prototype, but current concurrency, audience validation and crash gaps mean it is not an unconditional safe production sender |
| 1,000 users | Needs near-term batching, bulk identity/token lookup, bounded transport and durable progress; serial per-recipient OAuth and DB checks are inefficient |
| 10,000 users | **Cannot safely approve current system.** All-at-once resolution, synchronous request execution, per-user queries, serial network calls, missing timeout/claim/retry controls and end-of-job commit are material risks |
| 100,000+ users | Future scale work: measured query plans/indexes, chunked/keyset resolution, rate-controlled workers, delivery-table retention/partition strategy if justified, and aggregate metrics |

Shared Users SQL filtering is reusable, but whole-ID materialization and costly predicates need measurement at volume. Bulk UID bridging should avoid N+1 queries. Automated batch size 500 is not FCM multicast support and does not establish Admin capacity. Bell's ten-row retention cannot be reused for campaign reporting. Start with durable relational state and bounded batches; add infrastructure based on measured demand.

## 26. Reuse vs Replace Matrix

| Component | Classification | Rationale |
|---|---|---|
| SavedAudience model/criteria semantics | REUSE AS-IS | Frozen dynamic audience truth |
| Shared Users membership resolver | REUSE WITH ADAPTER | Canonical membership; notification-owned bulk bridge/eligibility |
| UID bridge/upsert | REUSE WITH ADAPTER | Correct identity key; reject nulls, count missing profiles, dedupe targets |
| NotificationJob | EXTEND | Existing campaign-like identity, insufficient execution semantics |
| Legacy audience JSON resolver | DEPRECATE LATER | Preserve old jobs explicitly; do not accept it as new SavedAudience filtering |
| NotificationLog as campaign ledger | DO NOT REUSE | Success-only, no actual uniqueness/attempt history, mixed namespaces |
| Canonical Bell model/feed | REUSE WITH ADAPTER | Presentation and read state; attach stable identity without treating it as delivery truth |
| Duplicate legacy models | DO NOT REUSE | Conflicting definitions and migration assumptions |
| SDK sender | REUSE WITH ADAPTER | Shared automated transport; needs structured reliability contract |
| Admin direct HTTP sender | DEPRECATE LATER | Duplicate auth/error policy; converge only after parity verification |
| Daily event and alert selection | REUSE AS-IS | Preserve existing automated business behavior during campaign integration |
| Attention policy/lifecycle | REUSE WITH ADAPTER | Explicit campaign interaction; preserve automated budget/visibility semantics |
| Alerts advisory-lock pattern | REUSE WITH ADAPTER | Useful locking evidence; campaign needs its own claim scope and lease |
| Unwired process_due_jobs | EXTEND | Concept exists; must gain durable claims and an actual runtime caller |
| Celery configuration unchanged | DO NOT REUSE | No notification task demonstrated; review runtime/security before selecting it |
| Activity Events ledger/schema | EXTEND | Existing contexts/events; add consistent producers and campaign projections |
| Flutter dispatcher/navigation | REUSE WITH ADAPTER | Add typed allowlisted actions and consistent identity without breaking existing types |
| Existing WebView | REUSE WITH ADAPTER | Add trusted destination policy and action/attribution behavior |
| Website UTM/payment attribution | REUSE WITH ADAPTER | Existing report-conversion flow; explicit campaign mapping and landing events needed |
| Existing test-send endpoint | DO NOT REUSE as campaign execution | Real-send diagnostic path, no campaign safety/ledger |

## 27. Risks / Technical Debt

Priority blockers before any activation:

1. Unsupported audience JSON can become an all-profile send. SavedAudience IDs are unsupported today.
2. No durable execution/recipient ledger, atomic Job claim or reliable retry boundary; local Log uniqueness is absent.
3. Scheduled Admin delivery has no discovered runtime caller. Existing workflow files are not evidence of hosted runtime health.
4. X1/X2 payload-equality Bell dedupe suppresses later campaign events; UUID and campaign identity are not consistent across all channels.
5. Token presence is used without an application marketing-preference contract, and multiple devices are not modeled.
6. Sender implementations disagree on retries/cleanup, lack a consistent timeout policy, and the HTTP sender commits caller state internally.

Additional source findings, not executed defects:

- Job service reads `u.language`, but AppUser's field is `lang`; intended Hindi selection does not use the actual field. Create API also does not populate the model's Hindi title/body fields.
- Test-send builder calls get_user_notifications with three arguments while the current builder signature accepts two.
- Send-now can report HTTP success after processing failure; Job can be marked sent with only failures.
- Legacy migration/model definitions disagree with actual local log schema; Job schema creation provenance was not found in the migration search.
- Topic subscription names do not align with the inspected Flutter general_0 subscription; topic dedupe is per-process only.
- Bell retention, payload-based dedupe and read_at omissions limit history and measurement.
- Attention policy comments and alerts scheduling comments disagree with checked-in workflow behavior.
- Raw route extras can violate screen contracts; WebView destination/redirect hosts are unrestricted by current app policy.
- Celery configuration includes disabled Redis TLS certificate verification and connection-URL logging; review before choosing that runtime. No credential values are reproduced here.
- Provider send and local commit cannot be atomic; exactly-once claims would be misleading even after local dedupe is added.

## 28. Recommended N1 Contract

Freeze the following architecture decisions before implementation:

1. **Identity:** Job/campaign ID for X1; separate immutable execution identity; stable recipient notification UUID. X2 is a new campaign even when its audience/content matches X1. Include IDs consistently in FCM, Bell, event context and permitted landing attribution.
2. **Audience:** new validated SavedAudience mode; no unknown-key fallback. Reuse users.id resolution. Preserve audience reference and approved criteria snapshot/version/hash; decide definition-edit and inactive-audience policies explicitly.
3. **Timing:** preview is informational; membership resolves live at the actual send. Retries resume frozen execution targets, not refreshed membership. UTC schedule contract with Admin timezone display.
4. **Eligibility:** bulk non-null UID bridge, explicit missing-profile/token/preference exclusions, token deduplication and documented single-device scope until a device registry is approved.
5. **History:** extend Job plus execution and recipient delivery records; Bell remains presentation. Define attempted, accepted, failed, invalid, suppressed, unknown and opened separately.
6. **Transport:** injectable provider adapter, enforced no-send test/local mode, bounded calls, rate/batches, structured provider result, safe token cleanup and caller-owned transactions.
7. **Reliability:** atomic claim/lease, unique target key, idempotent request contract, classified retries, cancellation/expiry and unknown-outcome policy. No exactly-once device-delivery promise.
8. **Actions:** NONE/APP_DEEP_LINK/WEB_URL with versioned allowlisted destinations/typed parameters; trusted HTTPS host policy and safe fallback.
9. **Measurement:** common IDs and idempotent event producers, Bell/FCM distinction, tap versus CTA/destination distinction, campaign-cohort aggregates. Preserve existing website report UTM conversion plumbing and explicitly freeze attribution windows.
10. **Safety:** campaign permission, explicit all-users approval/count-drift policy, preference gating and automated attention-budget interaction before send enablement.
11. **Scope:** do not redesign frozen Users/SavedAudience semantics or migrate automated selection into Admin Jobs. Review schema drift before authoring migrations in a later implementation phase.

This is the proposed minimum architecture, not a schema or API already created in N0.

## 29. Recommended Implementation Sequence

| Phase | Scope and exit condition |
|---|---|
| N1 Architecture + contracts | Freeze decisions in section 28, runtime choice, migration provenance and metric definitions; no ambiguous all-users behavior |
| N2 SavedAudience recipient adapter | Reuse membership query, bulk bridge, token/preference eligibility, preview counts; verify with isolated local fixtures and a no-send transport |
| N3 Composer + action contract | Next Admin/BFF create/preview, typed actions, validation, permission and all-users confirmation; drafting remains separate from sending |
| N4 Send Now | Implement campaign/execution/delivery state, atomic claims, idempotency, bounded transport, basic retry/error handling and local-only tests before enabling send |
| N5 Scheduling | Wire chosen worker, UTC handling, leases/recovery/cancellation, send-time resolution and preview-drift policy |
| N6 Metrics/history | Execution/recipient aggregation, consistent identity across Bell/FCM/app/web, deduped opens, explicit attribution contract |
| N7 Safety/reliability hardening | Load tests, failure injection, retention, reconciliation and operational controls; expand the protections already required in N2–N5 |
| N8 Regression/freeze | Users/SavedAudience regression plus automated event/alert parity, action navigation, identity/metrics, retries/schedules and documented limits |

Safety cannot be postponed wholesale to N7: fail-closed audience handling, no-send tests, claims and idempotency are prerequisites for N4. Scheduling runtime activation or any real push would need a separately authorized later task; neither occurred here.

## 30. Exact Files Likely Touched in N1/N2

N1 should initially produce architecture documentation. N2 should keep frozen Users/SavedAudience implementation stable and put new behavior in notification-owned files. The paths below are a proposed review map, not files changed by N0.

| Path | Expected role |
|---|---|
| Backend `NOTIFICATIONS_N1_ARCHITECTURE_CONTRACT.md` (proposed new) | Approved identity, audience, execution, action, safety and metrics contract |
| Backend `notifications/saved_audience_recipient_resolver.py` (proposed new) | Notification-owned membership/UID/token/eligibility adapter |
| Backend `test_notification_saved_audience_resolver.py` (proposed new) | Local isolated identity, criteria, inactive audience, null UID, duplicate token and count-contract verification |
| Backend `notifications/notification_service.py` | Narrow integration seam for new audience mode; do not silently reinterpret legacy Jobs |
| Backend `notifications/notification_routes.py` | Validated recipient-preview contract if included in N2; no send activation by implication |
| Backend `notifications/notification_models.py` | Campaign-model contract reference in N1; later extension only after approved schema plan |
| Backend `modules/services/saved_audience_service.py` | Read/reuse get_audience and lifecycle semantics; no planned filter redesign |
| Backend `modules/services/saved_audience_criteria.py` | Reuse stored-criteria validation; no planned changes |
| Backend `modules/services/admin_users_service.py` | Reuse resolve_user_ids; only revisit streaming/query performance with evidence and Users regression protection |
| Backend `modules/models_saved_audience.py`, `modules/auth/models.py`, `modules/models_user.py` | Read-only identity/schema contract references for adapter |
| Backend `test_saved_audience.py`, `test_admin_users_api.py` | Existing regression references; execute in an appropriately isolated later implementation task |

No frontend or Flutter change is necessary for a backend-only N2 adapter. Likely later paths are frontend `app/admin/notifications/page.tsx`, `app/api/admin/notifications/route.ts` and nested preview/send/history routes (all proposed), `components/admin/AdminNav.tsx`, and notification-specific client/components; backend notification sender/models/routes/service and Activity Events modules; Flutter `lib/core/notifications/notification_dispatcher.dart`, `notification_navigation_service.dart`, `notification_opened_producer.dart`, app routes and WebView; website attribution/client/checkout only where the approved contract requires it. These later changes must not be smuggled into N0/N2.

### Explicit completion answers

- Production system touched: **No.** Real notification sent: **No.** Firebase contacted: **No.**
- Code/business/schema changes: **None.** One local Markdown audit report added; existing uncommitted files preserved. No commit, push or deploy.
- Canonical sender: **SDK helper for automated notifications; separate HTTP sender for Admin Jobs; no universal transport today.**
- Current recipients: **AppUser non-null token plus optional legacy zodiac/lagna/subscription filters, not SavedAudience.**
- Job campaign support: **Campaign-like ID exists; SavedAudience IDs and persisted resolved member IDs do not. Repeat execution is possible without immutable execution history.**
- User/token bridge: **users.id → non-null UID → profile UID → AppUser token. Single profile/token slot per UID; no reliable multi-device registry. Cleanup is partial and sender-dependent.**
- 10,000-user safe send: **No, not with current controls.** Automated GitHub workflows exist; Admin Job polling is unwired in inspected code. Log checks are not sufficient concurrency/crash protection.
- X1/X2 and opens: **Partially identifiable via UUID/sent-event join, not reliably independently measurable. FCM tap events exist; Bell opens, CTA/destination and notification conversions need work.**
- Deep links/web: **Internal routes and a content CTA WebView exist; no complete generic typed campaign action or demonstrated universal-link return contract.**
- Website conversion: **Existing UTM report-payment attribution is reusable; automatic notification-specific mapping and complete visit/conversion instrumentation are absent.**
- Dynamic audience truth: **Keep it in SavedAudience. Freeze criteria identity, counts and execution/delivery facts on notification records. Resolve scheduled membership at send time, then resume the same targets for retries.**
- Legacy audience and history: **Adapt new Jobs through strict SavedAudience mode; preserve old JSON explicitly. Extend Job and add execution/recipient delivery records for dependable separate X1/X2 metrics.**

NOTIFICATIONS N0 DISCOVERY AUDIT: READY FOR N1 ARCHITECTURE FREEZE
