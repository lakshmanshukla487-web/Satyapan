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
