# Satyapan frontend

React 18 + Vite + TypeScript + Tailwind. Talks to the Django backend through the Vite proxy (`/api`, `/ws`), so the browser
sees one origin. Set `VITE_USE_MOCKS=true` in `.env` to run on simulated data instead (no backend needed; the officer
approval workflow and session termination need the real backend).

## Run
    npm install
    npm run dev        # http://localhost:5173 (or use ../start.sh, which also starts the backend)
    npm run typecheck  # tsc --noEmit
    npm run build      # type-check + production build

`npm run setup:assets` (runs automatically before dev and build) copies the MediaPipe WebAssembly files and downloads the
face model, which the head-turn and blink challenges need.

## Routes
| Route | Who | What |
|---|---|---|
| `/`, `/login`, `/register` | anyone | Landing, sign in, customer sign-up (officers cannot self-register) |
| `/dashboard` | customer | Own sessions with plain-language status (never a risk outcome) |
| `/verify` | customer | Consent → Documents → Live check (challenges released by an officer) |
| `/officer` | officer | Review console: live sessions, approval queue, risk, documents |
| `/sessions/:id` | officer | Live video call and chat, challenge approval, KYC documents, signals, **Finish verification**, **End session now** |
| `/sessions/:id/report`, `/sessions/:id/evidence` | officer | Frozen report; hash-chained evidence |

## Structure
    src/components/ui.tsx            design kit (Card, Pill, TierBadge, Modal, buttons)
    src/components/DocumentsStep.tsx customer KYC upload step
    src/components/officer/          ApprovalPanel, DocumentsPanel, TerminateDialog
    src/features/services.ts         service interface + mock; realService.ts maps the API to UI types
    src/hooks/                       useSession, useOfficerFeed, useCustomerChannel, useMediaStream
    src/utils/                       integrityProbe, pulseSampler, challengeDetector, capture
Design tokens (colours, fonts, shadows) are in `tailwind.config.js`.

## Manual test checklist
- [ ] Signed out: `/verify` and `/officer` redirect to `/login`; after signing in you land where you were going.
- [ ] Consent must be ticked before Continue; the camera stays off until "Start camera and begin".
- [ ] Documents: a wrong PAN or Aadhaar checksum shows a message under that field; Submit stays blocked until all are valid.
- [ ] The customer sees "Waiting for the reviewing officer" with no challenge text until the officer approves it.
- [ ] Officer: Regenerate replaces the pending challenge; Approve shows it on the customer's screen within a few seconds.
- [ ] Officer: "End session now" stops the customer's camera at once and shows a neutral message.
- [ ] Deny camera permission: a clear error appears and the session is not started.
