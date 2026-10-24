# Satyapan (सत्यापन): live V-CIP deepfake co-pilot

Team RVSHH · IIT Delhi × Amazon "Raksham AI II" hackathon

Satyapan checks the KYC **documents** first, then gathers independent signals about the live **audio, video, identity, camera and
network**, and shows a human **officer** the reasons behind every recommendation. The officer approves the customer's request,
can watch and talk to the customer live, and can end the session at any moment. Satyapan is decision support: a person makes
every decision.

## Run it in VS Code

You need **Python 3.12** and **Node.js 18+**. Open this folder in VS Code, open a terminal and run:

| OS | Command |
|---|---|
| macOS / Linux | `./start.sh` |
| Windows (PowerShell) | `.\start.ps1` |

The script creates a virtual environment, installs the requirements (including the ML packages unless you set `SATYAPAN_ML=0`),
writes `backend/.env`, runs `python manage.py setup_db` (creates and verifies the database), adds two demo users, starts the
backend on port 8000 and the frontend on `http://localhost:5173`.

Demo logins (development only):

| Role | Username | Password |
|---|---|---|
| Officer | `officer` | `officer-pass-123` |
| Customer | `customer` | `customer-pass-123` |

Use **two browser profiles** (or one normal and one private window): one is the customer, the other is the officer.

### Models: one-time setup (do this before the demo)

The models are loaded **once, on the CPU, when the server starts** (`PRELOAD_MODELS=true`); after that requests only run inference.

```
cd backend
python scripts/download_models.py --all      # video deepfake ViT, face detector + recogniser, SyncNet
python scripts/update_ip_lists.py            # free public VPN / Tor / data-centre address lists
python scripts/verify_models.py              # prints what loaded and what did not
```

1. **Voice anti-spoofing (your fine-tuned wav2vec2)**: copy `model.safetensors` into `backend/models/audio/` (the folder already has
   `config.json` and `preprocessor_config.json`). If the weights do not fit the config the detector reports `WEIGHTS_INCOMPLETE`
   instead of guessing.
2. **Video deepfake**: `prithivMLmods/Deep-Fake-Detector-v2-Model` (Apache-2.0, free for commercial use), downloaded by the script.
3. **Lip sync (SyncNet)**: weights are **research-only** (see `docs/MODELS_AND_LICENCES.md`). Fine for the hackathon; replace or
   retrain before any commercial use, or set `ENABLE_SYNCNET=false`.
4. **Face match and face landmarks**: OpenCV YuNet + SFace (downloaded) and MediaPipe Face Landmarker (`models/face_landmarker.task`, included).

Anything that is not installed shows as an evidence gap (**GREY** or "unavailable"), never as suspicion and never as a pass. A
session can only turn **GREEN** when enough independent checks positively confirm authenticity, so for a green demo you need the
models loaded.

### Try the whole flow (about 5 minutes)

1. **Customer**: sign in, tick the consent box and press *Ask an officer to start my verification*. The page says it is waiting for an officer.
2. **Officer** (*Review console*): the request is in *Verification requests*. Press *Approve* (or *Reject*).
3. **Customer**: tick consent, fill in the documents step (valid test set: PAN `ABCPS1234F`, Aadhaar `2345 6789 0124`, PIN `110001`,
   mobile `9876543210`, same name and date of birth on every document; any small JPEG, PNG or PDF works as the file).
4. **Customer**: take the **start photo** (close, face centred, eyes wide open). The page tells you what to fix if it is unusable.
5. **Customer**: *Start camera and begin*. Challenges (head turn, blink, spoken words, and a close-up **eye scan**) keep coming for the
   whole session; the customer is never told whether one passed.
6. **Officer**: open the session. Use *Start live call* to see and talk to the customer, *Approve* each challenge (or switch on
   auto-release), and watch the colour of every evidence family.
7. When the session ends the officer opens the **report** and can **download** it (PDF or HTML). It ends with an "In plain words"
   section that explains the colours without jargon.

Try a mismatch: a different person in front of the camera than in the start photo is flagged by the face match.

### Mock mode (frontend only, no backend)

Set `VITE_USE_MOCKS=true` in `frontend/.env`. Everything is simulated and labelled as such. The approval workflow, live call,
and officer termination need the real backend.

## What the system checks (evidence families)

| Family | Colour source | Notes |
|---|---|---|
| Voice authenticity | your fine-tuned wav2vec2 | judged over **all** clips, not the last one |
| Face video authenticity | ViT deepfake classifier | over all frames, worst quarter and latest window |
| Lip sync | SyncNet | supporting; research-only weights |
| Face = start photo | YuNet + SFace | drift over the session is tracked |
| Iris = start photo | classical iris code | **visible-light, uncalibrated**; raises AMBER alone, RED only with other evidence |
| Liveness (challenges) | browser report **cross-checked by the server's own frame landmarks** | a browser claim the server's frames contradict is a tampering indicator |
| Camera is a real device | rule-based probe | virtual camera, injected `getUserMedia`, automation |
| Network | IP lists, optional reputation API, WebRTC leak, header and IP-change checks | VPN / proxy / Tor / data centre |
| Documents | format, checksum, consistency, face on the document | not a lookup in government systems |
| Session pattern | timing, gaps, drift, media coverage | needs `MIN_SESSION_SECONDS` (90 s) |

Overall colour: **RED** any hard family red or three risk points · **AMBER** any concern · **GREY** nothing raised but evidence is
missing (the report lists exactly what) · **GREEN** nothing raised *and* every requirement for enough evidence is met.

## Checks you can run

```
cd backend && pip install -r requirements-dev.txt && pytest          # full backend test suite
cd backend && python scripts/static_check.py                          # no install needed
cd frontend && npm install && npm run build                           # type-check + production build
```

## If sign-up returns HTTP 500

The usual cause is a missing or outdated database (migrations not applied, or an old `satyapan.db`). Run
`python manage.py setup_db` in `backend/` (the start scripts do it). It creates migration files, applies them, verifies every
table and column, and in development rebuilds a wrong SQLite file after backing it up. The API now answers a database problem
with a clear `503 DATABASE_NOT_READY` and writes the full traceback to the server log with the request id.

## Honest limits

* **Documents** are checked for format, checksum, freshness and consistency. This is **not** a lookup in UIDAI, NSDL, DigiLocker
  or the passport office. Only masked numbers are stored.
* **The iris scan is not a retina scan.** A camera cannot image the retina. The iris code works on ordinary photos and is much
  weaker than near-infrared iris hardware: thresholds (`IRIS_MATCH_HD`, `IRIS_MISMATCH_HD`) are **not calibrated on real data**.
  In synthetic tests different irises scored 0.33 to 0.43 and the same iris 0.01 to 0.05, so many impostors will come out as
  "uncertain" rather than "mismatch". Calibrate on real captures before relying on it.
* **Face match** defends against a *different person*, not against a face swap that copies the reference person's identity.
* **Camera and IP checks** rely on what the browser reports. A determined attacker who controls the browser can fake some of it; a
  residential proxy or a fresh, unlisted VPN looks like an ordinary connection.
* **Deepfake model scores** are uncalibrated outputs of public or fine-tuned models, compared with demo thresholds. They generalise
  imperfectly to new generators. They are not probabilities of fraud.
* **The officer's live call** is peer to peer (WebRTC). Behind strict firewalls a TURN relay is needed (`TURN_URLS`).
* The hash chain makes later edits to the evidence log *detectable*; it is not legally certified evidence.
* Migration files are generated on first run. Commit them once you are happy with the schema.
