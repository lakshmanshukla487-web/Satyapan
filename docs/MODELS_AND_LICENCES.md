# Models, licences and what each one can and cannot do

All models are loaded **once, on the CPU, at server start** (`PRELOAD_MODELS=true`, `INFERENCE_DEVICE=cpu`). A request only runs
inference. A bounded worker pool (`MAX_CONCURRENT_INFERENCES`) and a back-pressure gate (`INFERENCE_QUEUE_LIMIT`) keep the site
responsive: when the models are saturated a request gets a quick `503 SERVER_BUSY` and the browser retries on its next tick.
Set `REDIS_URL` to share the cache, rate limiter, back-pressure counter and WebSocket channel layer between several server
processes (`pip install -r requirements-optional.txt`).

| Purpose | Model | Where it lives | Licence | Commercial use |
|---|---|---|---|---|
| Voice anti-spoof | your fine-tuned wav2vec2 | `models/audio/` (copy `model.safetensors`) | yours | yours to decide (base model licence applies) |
| Face video deepfake | `prithivMLmods/Deep-Fake-Detector-v2-Model` (ViT) | `model_cache/` via `download_models.py --video` | Apache-2.0 | yes |
| Lip sync | SyncNet (S) | `models/syncnet/syncnet_v2.model` via `--syncnet` | **research-only** weights | **no**: replace, retrain or disable (`ENABLE_SYNCNET=false`) |
| Face detect + recognise | OpenCV YuNet + SFace | `models/` via `--faces` | MIT / Apache-2.0 | yes |
| Landmarks (pose, blink, eye geometry) | MediaPipe Face Landmarker | `models/face_landmarker.task` | Apache-2.0 | yes |
| Iris code | classical log-Gabor (own code, numpy/scipy) | none | project licence | yes |
| Camera / IP checks | rules + CIDR lists (`scripts/update_ip_lists.py`) + optional proxycheck.io / IPQS | `data/ip/` | list licences vary: read each source | check the list source |

Check the licence of every list that `update_ip_lists.py` downloads before commercial use.

## What each result means

* **Voice, video, lip sync** produce an uncalibrated score. The policy judges them over every sample in the session: the flagged
  fraction, the worst quarter of samples and the latest samples (so a mid-session switch to a fake is caught). A single sample
  never clears or condemns a family. Poor input quality gives GREY for that family.
* **Face match** compares the live face with the start photo (cosine similarity, 0.363 is the SFace published value). It detects a
  *different person*. It does not detect a face swap that reproduces the reference person's identity. A downward drift of the
  similarity during a long session is reported separately.
* **Iris** compares the coloured ring of the eye from the close-up scan with the start photo. It is **not a retina scan** (a
  camera cannot see the retina) and is much weaker than near-infrared iris hardware. The thresholds are not calibrated on real
  data. In synthetic tests the same iris scored a Hamming distance of 0.01 to 0.05 and different irises 0.33 to 0.43, so the
  0.40 mismatch line labels many impostors "uncertain" instead of "mismatch" (the safe direction for genuine users). Calibrate on
  real captures before trusting it. A mismatch needs two agreeing readings and raises AMBER; it reaches RED only together with
  other concerns.
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
