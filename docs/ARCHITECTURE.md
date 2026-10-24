# Architecture

## 1. Backend layout (one Django app per concern)

The original single `verification` app was split into the apps below. Detector, decision and evidence logic was moved, not
rewritten; the original tests were ported and still target the same behaviour.

| App | Responsibility | Models |
|---|---|---|
| `core` | errors, validation, uploads, rate limit, security headers, request ids, runtime/model registry, audit log | `AuditLog` |
| `accounts` | users with roles (`customer`, `officer`), signed bearer tokens, login throttling, logout revocation | `User` |
| `verification` | session lifecycle: create, consent, start, complete, cancel, **terminate** | `VerificationSession` |
| `documents` | **KYC upload and cross-document verification** (new) | `KycDocument`, `DocumentCheck` |
| `challenges` | challenge generation, **officer approval workflow**, results | `Challenge` |
| `integrity` | evidence family 1: pipeline integrity (virtual-camera name, frame timing) | none |
| `voice` | family 4: voice anti-spoof (wav2vec2 XLS-R) | none |
| `avsync` | family 3: audio-video consistency (SyncNet placeholder) | none |
| `pulse` | family 5: rPPG pulse (POS algorithm), supporting only | none |
| `provenance` | family 6: document provenance (metadata rules), supporting only | none |
| `visual` | ViT / Xception / landmark frame analysis | none |
| `signals` | detector registry and stored per-sample results | `DetectorSignal` |
| `decision_engine` | median aggregation, deterministic rules R2 to R6, tiers GREEN / AMBER / RED / GREY | none |
| `evidence` | SHA-256 hash-chained event log, export and verification | `EvidenceEvent` |
| `reports` | frozen officer report with its hash recorded in the chain | none |
| `realtime` | Channels consumers and event publishing | none |

Family 2 (challenge-response) lives in `challenges`. Supporting families (pulse, provenance) can never raise an indicator by
themselves. The only hard indicator from family 1 is a virtual-camera name *together with* unnaturally regular timing.

## 2. Officer approval workflow

```
customer page                     backend                               officer console
─────────────                     ───────                               ───────────────
POST /challenges  ───────────────► Challenge(status=awaiting_approval,
(text and type are generated)       approval_status=pending)
                                    customer sees only {id, status}
                                    publish challenge.pending ─────────► appears in "Approval queue"
"Waiting for the reviewing          (+ officer feed)
 officer" (no content)                                                    POST .../approve
                                    status=issued, fresh TTL starts  ◄──  or .../regenerate (new hidden one)
◄── challenge.released (WS)         publish_customer(challenge.released)
or GET /challenges/current (poll)
does the challenge, POST .../result ► status=answered, result stored
```

* `Challenge.status`: `awaiting_approval → issued → answered | expired`. `approval_status`: `not_required | pending | approved | regenerated`.
* The customer serializer **hides type and text** while a challenge is pending. The customer cannot answer a pending one
  (`409 CHALLENGE_NOT_APPROVED`).
* The time limit restarts at release, so a slow officer never shortens the customer's window. An unanswered request expires
  after `CHALLENGE_APPROVAL_TIMEOUT_SECONDS`; the customer page then asks for a new one.
* An officer can also *run a challenge now* of a chosen type (`POST .../challenges/issue`); that one is released at once.
* Switch the gate off with `REQUIRE_CHALLENGE_APPROVAL=false` (challenges are then issued directly).

### Officer termination override

`POST /api/v1/sessions/{id}/terminate` (officers only, any time while the session is live):

1. status becomes `terminated`; `terminated_at`, `terminated_by` and the reason are stored;
2. every open challenge is expired;
3. the report is frozen and its hash is recorded in the evidence chain;
4. the customer's channel receives `session.terminated` with a **neutral** message (no accusation), their camera stops, and
   every later write from the customer is refused (`409`);
5. the action is written to the audit log.

## 3. Real-time (Channels / WebSocket)

Three groups, so nobody receives more than they should:

| Path | Who may connect | Group | Carries |
|---|---|---|---|
| `/ws/sessions/<id>` | officers | `session.<id>` | everything about one session, including risk |
| `/ws/officer/feed` | officers | `officers` | dashboard events across sessions |
| `/ws/customer/<id>` | the owning customer | `customer.<id>` | released challenges, status, termination. **Never risk data** |

Authentication: the token travels as a WebSocket subprotocol (`["satyapan.v1", token]`), never in the URL. Close codes:
`4401` not signed in, `4403` wrong role or origin, `4404` unknown session. A missing `Origin` header is refused outside `DEBUG`.

| Event | Audience | Meaning |
|---|---|---|
| `session.status` | officer, customer, feed | lifecycle change |
| `challenge.pending` | officer, feed | a hidden challenge needs approval |
| `challenge.approved` / `challenge.issued` | officer | released / officer-issued |
| `challenge.released` | customer | the content of a challenge, for the first time |
| `challenge.result` | officer | the customer answered |
| `document.uploaded`, `documents.checked` | officer, feed | KYC progress |
| `detector.*`, `signal.updated`, `risk.updated`, `analysis.completed` | officer | analysis progress |
| `session.terminated` | officer, customer, feed | officer ended the session (customer text is neutral) |

If a socket drops, the customer page polls `GET /challenges/current` and the dashboard refreshes on a timer.

## 4. KYC documents and cross-document verification

Required before the camera starts (`REQUIRE_DOCUMENTS=true`; `POST /start` is refused until the check passes):

* application details (name, date of birth, mobile, PIN)
* **PAN** (individual PAN only, the 4th letter must be `P`)
* **one officially valid document**: Aadhaar, passport, driving licence or voter ID (EPIC)
* optional: address proof (recent bill or bank statement), cancelled cheque (IFSC, last four digits of the account)

Per-document checks: structure and checksum (PAN pattern, Aadhaar Verhoeff, passport / DL / EPIC patterns, IFSC, mobile, PIN),
expiry, document age for address proofs, file type by content (not by name), size limit, and optional OCR.

Cross-document checks:

| Finding | Severity | Effect |
|---|---|---|
| name differs between documents (fuzzy match) | **indicator** | raises a `documents` indicator in the decision engine |
| date of birth differs | **indicator** | same |
| year of birth differs (Aadhaar with year only) | **indicator** | same |
| PIN code differs | note | shown to the officer |
| same file uploaded for two documents | note | shown to the officer |
| PAN surname initial does not match | note | shown to the officer |
| the same ID number was used in another customer's session | note | keyed HMAC (`id_hash`), never the number itself |

The customer is told only what they can fix (a bad checksum, an expired document). Cross-document findings are shown to
the officer only, so a fraudster learns nothing about what to adjust.

Privacy: files are processed in memory and **not stored**; only masked numbers, derived flags and a SHA-256 of each file are
kept. **Not** verified against UIDAI, NSDL or DigiLocker: this is structure and consistency only.

## 5. Security (OWASP Top 10, 2021)

| Risk | What was done |
|---|---|
| **A01 Broken access control** | role checks on every view (`IsCustomer`, `IsOfficer`); customers only reach their own sessions (`get_owned`); officers cannot act as customers; customer WebSocket group never carries risk data; objects are looked up by UUID and unknown ids return a uniform 404 |
| **A02 Cryptographic failures** | Argon2 password hashing; HMAC-signed tokens with expiry and a per-user `token_epoch` so logout revokes at once; HSTS, TLS redirect and secure cookies in production; `Cache-Control: no-store` on API responses; ID numbers stored masked, cross-customer matching by keyed HMAC |
| **A03 Injection** | ORM only, no raw SQL; strict serializers; bounded challenge measurement input (count, key length, finite numbers); file type sniffed from content |
| **A04 Insecure design** | documents before camera; officer approval before the customer sees a challenge; server-side time limits; rule-based, explainable decisions; supporting evidence can never decide alone |
| **A05 Security misconfiguration** | production refuses to start with a weak `SECRET_KEY`, wildcard `ALLOWED_HOSTS` or non-https origins; API docs off in production; strict CSP (`default-src 'none'`), `nosniff`, frame denial, `Permissions-Policy`; narrow CORS methods and headers; cookie flags (`HttpOnly`, `SameSite=Strict`, `Secure`) as defence in depth |
| **A06 Vulnerable components** | pinned requirements; the frontend has no new runtime dependencies; run `pip-audit` / `npm audit` in CI |
| **A07 Identification and authentication failures** | login throttling per IP and username, password validators, logout revocation, officers cannot self-register, WebSocket tokens via subprotocol (not URLs) |
| **A08 Software and data integrity** | SHA-256 hash-chained evidence log; the report hash is recorded in the chain; signed tokens |
| **A09 Logging and monitoring failures** | `AuditLog` for sign-ins, approvals, regenerations, terminations and document actions; request ids on every response; security log for throttled logins |
| **A10 SSRF** | the backend makes no outbound requests on behalf of users |

Cross-site request forgery: the API authenticates with bearer tokens in a header, not cookies, so CSRF does not apply to it.
The CSRF and cookie settings are in place for the day an admin or cookie session is added.

## 6. Frontend

* `src/components/ui.tsx`: design kit (cards, pills, tier badge, modal, buttons). Tokens live in `tailwind.config.js`.
* Customer: `VerificationPage` (Stepper: Consent → Documents → Live check), `DocumentsStep`, `CustomerDashboardPage`.
* Officer: `OfficerDashboardPage` (live feed, approval queue), `SessionDetailsPage` (approval panel, documents panel,
  end-session dialog, signal cards), `SessionReportPage`, `EvidencePage`.
* `features/services.ts` selects the mock or the real service; `realService.ts` maps the API to UI types.
* Hooks: `useCustomerChannel`, `useOfficerFeed`, `useSession`; utilities: `integrityProbe`, `pulseSampler`, `challengeDetector`.

## 7. Configuration

All settings are environment variables listed in `backend/.env.example`. Production checklist: `APP_ENV=production`,
`DJANGO_SECRET_KEY` (50+ random characters), exact `ALLOWED_HOSTS`, https `FRONTEND_ORIGIN`, `BEHIND_TLS_PROXY=true` only behind
a trusted proxy, `REDIS_URL` when running more than one process (the channel layer and rate limiter are in-memory otherwise),
a real database via `DATABASE_URL`.

## 8. Version 4 additions

### 8.1 Session approval (customer asks, officer decides)

`POST /api/v1/sessions` creates the session with `approval_status = pending` (`REQUIRE_SESSION_APPROVAL=true`). Until an officer calls
`POST /sessions/{id}/approve`, the customer cannot give consent, upload documents or the start photo, or start the camera
(`403 APPROVAL_PENDING`). `POST /sessions/{id}/reject` cancels the request; the reason stays with the officers. A request nobody
answers expires after `SESSION_APPROVAL_TIMEOUT_SECONDS`. A customer may hold at most three open requests. Consent is recorded after
approval. `POST /sessions/{id}/auto-approve` (officer) releases every challenge of the session automatically, including ones
already waiting.

### 8.2 Continuous challenges

`POST /sessions/{id}/challenges` is idempotent: while a challenge is open it returns that one (200); otherwise it creates the next
(201). The browser asks again whenever one finishes, so challenges run for the whole session, and the session length is analysed
(gaps, answer speed, performance drift). The type is random, never the same twice in a row, and the iris scan is scheduled as the
second challenge (then about every fifth) when a usable reference iris exists. The customer's API never contains `result`,
`reason` or `verification`; only officers see them.

### 8.3 Identity

* `POST /sessions/{id}/reference-photo`: the close-up, eyes-wide photo. Analysed in memory; only a face embedding and iris
  templates are stored (never the image), with the file hash in the evidence chain. Unusable photos return plain-language advice.
* Frames uploaded during a challenge (`challenge_id` field) are measured by the server (landmarks) and compared with the start
  photo (face match). `Observation` rows hold the time series.
* `POST /sessions/{id}/challenges/{id}/eye-scan`: 1 to 6 close-up frames; the server decides the result.
* Documents: the face on each document is compared with the start photo.

### 8.4 Pipeline integrity

`POST /sessions/{id}/analysis/integrity` takes the browser probe (camera label with USB ids, driver controls, installed virtual
devices, `getUserMedia` nativeness, automation flag, frame timing, and the public address found through STUN). The server adds the
IP assessment (lists, optional reputation API, WebRTC leak, proxy headers, address change during the session).

### 8.5 Decision policy v3

See `apps/decision_engine/engine_v3.py` (its docstring is the specification). Families are judged over all samples and combined by
risk points; GREEN needs every "enough evidence" requirement; the report lists what is missing for GREEN.

### 8.6 Live call

Only small signalling messages go through the existing session WebSocket; the server never touches the video and does not record
the call. Allowed client events (whitelisted, size-limited, rate-limited, relayed only between the two sockets of one running
session): `call.request`, `call.accept`, `call.decline`, `call.end`, `chat.message`, and `rtc.signal` with `kind` = `offer`,
`answer` or `candidate`. The officer requests the call; the customer must accept it (and the browser asks for camera and microphone
permission) before anything is shown. The officer makes the offer (receive-only video, own microphone); the customer answers with
camera and microphone. ICE servers come from `GET /api/v1/rtc/config` (STUN by default; configure `TURN_URLS` for strict networks).

### 8.7 Reports

`GET /sessions/{id}/report` (JSON), `/report/download?format=pdf|html|json`. The report is frozen at completion and its hash is in
the evidence chain. It contains the family table, coverage, session analysis, identity and network sections, and ends with an
"In plain words" section written for a non-technical reader.

## 9. Version 5 changes

### 9.1 Request volume and rate limiting

Root cause of the "too many requests" errors: the officer's session page refetched five endpoints (session, analysis,
challenges, full evidence chain, documents) on EVERY WebSocket event, and one uploaded frame produces about 13 events
(detector.started / completed / signal.updated per detector, then risk.updated). With a frame every 3 s and a dense frame series
during challenges this was ~3,600 requests per minute from one officer page (measured with the page code and a simulated event
stream: 1,195 requests in 20 s). The console loaded every session through five requests each and reloaded on every feed event.
All users behind the Vite proxy share one address (127.0.0.1), so the per-address limit of 120/min was exceeded within seconds
and also hit customers. Every failed refresh also replaced the officer page by an error box, unmounting the live video.

Fixes:
* Officer workspace (`hooks/useSession.ts`): events that carry the new state (`risk.updated`, `signal.updated`) are applied without
  a request; other events refetch only the part they concern, coalesced (throttle with trailing call, at most one round per 1.5 s,
  one request in flight); the evidence list is a bounded tail (`GET .../evidence?tail=200`, not audited) refreshed at most every
  10 s; polling (every 10 s) only while the socket is down; one catch-up refresh after a reconnect. Measured: 7 requests in 20 s.
* Officer console: `GET /api/v1/officer/dashboard` returns sessions (with colour, document status and usable-signal count), the
  approval queue, the requests and recent activity in one response, refreshed at most every 5 s.
* Customer page: WebSocket first; polling is a slow safety net while the socket is open and a bounded fallback while it is down;
  "has the officer ended the session" reads one session instead of listing all of them.
* Client: request timeouts, bounded retries with exponential backoff and jitter for transient errors only, `Retry-After`
  honoured, and a client-side pause of background traffic after a 429 (no burst when the limit lifts). Terminal errors are not
  retried. `useAsync` never overlaps requests and ignores stale answers; a failed refresh keeps the last data on screen.
* Server (`apps/core/middleware.py`): buckets per signed-in account (API and media separately) and per address for anonymous
  requests, plus an address ceiling; 429 responses carry `Retry-After`, `retry_after`, `scope` and the request id. The account
  id is read from the signed token without a database query; forged tokens count as anonymous. Login/sign-up throttles,
  inference back-pressure (503 `SERVER_BUSY`, now with `Retry-After`) and workflow limits (`TOO_MANY_PENDING`) are unchanged.

### 9.2 Live call and the live verification workspace

The session page is now a workspace: the customer's live video (large) and the challenges of the SAME session side by side
(stacked on small screens), with session context that keeps risk indicators, missing evidence (unavailable models) and failed
challenges apart. Call fixes (`features/call/*`, `components/CallPanels.tsx`): a per-call id on every signalling message (the
relay whitelists it; messages of another call are ignored, e.g. a late `call.end` no longer kills a new call), signalling
processed strictly in order, remote tracks collected into one stream, remote audio played through an `<audio>` element with an
explicit "click to hear" control when autoplay is blocked, a live audio level meter, officer microphone mute and an accurate
microphone state (blocked / muted / on), answer and connect timeouts, recovery window for a dropped connection, and the call is
ended for the other side when the page is left or closed. The customer's verification camera is never stopped by the call.

### 9.3 Document correction

`POST /api/v1/sessions/{id}/documents/{doc_type}/remove` (customer, own session, only while documents are editable: after
consent, before the live check). Files are never stored, so it removes what is kept about the document, everything derived from
its file (face embedding from the document photo; provenance results are marked superseded and ignored by the decision engine),
and the last document check; the removal is recorded in the evidence chain. Replacing a document clears the same derived data
before the new file is processed. The documents step shows the selected file (name, type, size) with Replace and Remove, the
state of documents already on the server, and lets the customer go back from the photo step to correct documents.

### 9.4 Developer role and model test lab

Role `developer` (migration `accounts.0002`, choices only). Created only with `manage.py create_developer`; public sign-up always
creates customers; developers cannot create or read customer sessions or officer endpoints. App `apps.devlab` (own tables, no
relation to sessions) under `/api/v1/devlab/*` (all `IsDeveloper`). Jobs run in a background worker (one per process by default)
through the same detector objects, preprocessing, bounded model pool and back-pressure gate as live traffic, always leaving
`DEVLAB_LIVE_RESERVE` slots to live sessions. Uploads are identified by content (the extension must agree), probed for length and
dimensions before acceptance, stored with private permissions only while needed, and deleted after processing, on cancel and on
expiry. Videos are sampled evenly over the whole clip and aggregated (median by default, the same majority rule the live policy
uses for a RED video family). Metrics use only labelled samples with a real detector result and list every exclusion.
