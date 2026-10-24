# Models, licences and what each one can and cannot do

All models are loaded **once, on the CPU, at server start** (`PRELOAD_MODELS=true`, `INFERENCE_DEVICE=cpu`). A request only runs
inference. A bounded worker pool (`MAX_CONCURRENT_INFERENCES`) and a back-pressure gate (`INFERENCE_QUEUE_LIMIT`) keep the site
responsive: when the models are saturated a request gets a quick `503 SERVER_BUSY` and the browser retries on its next tick.
Set `REDIS_URL` to share the cache, rate limiter, back-pressure counter and WebSocket channel layer between several server
processes (`pip install -r requirements-optional.txt`).

| Purpose | Model | Where it lives | Licence | Commercial use |
|---|---|---|---|---|
| Voice anti-spoof | your fine-tuned wav2vec2 | `models/audio/` (copy `model.safetensors`) | yours | yours to decide (base model licence applies) |
| Face video deepfake | `prithivMLmods/Deep-Fake-Detector-v2-Model` (ViT) | `models/video/` via `download_models.py --video` (needs `--faces` for the crop) | Apache-2.0 | yes |
| Lip sync | SyncNet (S) | `models/syncnet/syncnet_v2.model` via `--syncnet` | **research-only** weights | **no**: replace, retrain or disable (`ENABLE_SYNCNET=false`) |
| Face detect + recognise | OpenCV YuNet + SFace | `models/` via `--faces` | MIT / Apache-2.0 | yes |
| Landmarks (pose, blink, eye geometry) | MediaPipe Face Landmarker | `models/face_landmarker.task` | Apache-2.0 | yes |
| Speech-to-text (spoken-words challenge) | `openai/whisper-base` (Whisper) | `models/speech/` via `download_models.py --speech` | MIT | yes |
| Iris code | classical log-Gabor (own code, numpy/scipy) | none | project licence | yes |
| Camera / IP checks | rules + CIDR lists (`scripts/update_ip_lists.py`) + optional proxycheck.io / IPQS | `data/ip/` | list licences vary: read each source | check the list source |

Check the licence of every list that `update_ip_lists.py` downloads before commercial use.

## What each result means

* **Voice, video, lip sync** produce an uncalibrated score. The policy judges them over every sample in the session: the flagged
  fraction, the worst quarter of samples and the latest samples (so a mid-session switch to a fake is caught). A single sample
  never clears or condemns a family. Poor input quality gives GREY for that family.
* **Face video deepfake (ViT)** is loaded once at server start together with the face detector, and warmed up with one dummy
  inference; afterwards each uploaded frame only runs inference (about 0.5 s per frame on a laptop CPU with mirror averaging).
  Each frame is cropped to a square around the largest face (the model was trained on face crops); a frame with no face or a face
  under `VIDEO_MIN_FACE_PX` is not scored. Its published 92 % accuracy is on a random split of its own training pool (the
  OpenForensics-based "Deepfake and real images" set), not on unseen data; on real webcam-like video it can lean towards "fake".
  Measure it on your own labelled data with `python scripts/eval_video_model.py <folder>` before trusting the threshold.
* **Face match** compares the live face with the start photo: OpenCV YuNet finds the face (a second, padded pass catches faces
  that fill the picture, which YuNet misses on its own), SFace turns it into a 128-number fingerprint, and the cosine similarity is
  compared with 0.363 (the published SFace value). Measured through the production code on real people the model was not built for:
  | test | genuine accepted | impostors accepted |
  |---|---|---|
  | DFD actors, start photo and live frames from *different* videos (24 genuine / 1,520 impostor pairs) | 100 % (lowest similarity 0.53) | 0.46 % |
  | CelebA-HQ, two different photos of the same celebrity (59 / 708 pairs) | 88 % | 0.28 % |
  It detects a *different person*. It does not detect a face swap that reproduces the reference person's identity. A downward drift
  of the similarity during a long session is reported separately. Poor images (dark, blurry, small, several faces) are "low quality",
  never a mismatch.
* **Iris** compares the coloured ring of the eye from the close-up scan with the start photo (MediaPipe iris landmarks + a classical
  log-Gabor iris code). It is **not a retina scan** (a camera cannot see the retina). Measured on the CelebA-HQ pairs, irises of
  40-55 px (about what a webcam eye scan gives) separate people barely better than chance (AUC about 0.62: genuine median Hamming
  distance 0.38, impostors 0.40), and the old thresholds wrongly called 10 of 59 genuine people a "mismatch". So no match or mismatch
  verdict is given below `IRIS_MIN_VERDICT_PX` (80 px): the result is "inconclusive", which never counts for or against the customer.
  The 80 px limit itself is not validated: collect real genuine/impostor eye scans before trusting any iris verdict. A mismatch
  needs two agreeing readings and raises AMBER; it reaches RED only together with other concerns.
* **Challenges** continue for the whole session. The browser measures the action, and the server independently measures head pose,
  eye openness and mouth movement on the frames uploaded during the challenge. A browser claim that the server's frames
  contradict counts as a tampering indicator; a pass that only the browser vouches for does not count as liveness proof for GREEN.
* **Camera** (virtual vs hardware) and **IP** (VPN / proxy / Tor / data centre / WebRTC leak / address change) are client-reported
  or list-based. They catch careless attacks, not a determined one.

## Why GREEN is hard to get (bluff resistance)

GREEN requires **all** of: a minimum session length; verified liveness including a server-confirmed challenge; a positive face
match when a face model is installed; at least three independent families positively clear; at least one media-authenticity family
positively clear; media that kept arriving for most of the session; and no AMBER or RED anywhere. Missing evidence gives GREY and
the report names exactly what is missing. The customer never sees any result (no risk level, no challenge outcome), so there is
nothing to tune an attack against.
