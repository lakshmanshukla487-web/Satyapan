"""Measure the face deepfake model (the production `vit` detector, with the server's exact preprocessing) on labelled test data.

    python scripts/eval_video_model.py KIT [--frames 8] [--per-class 250] [--transport] [--kyc-framing] [--out results.json]

KIT holds one folder per test set, each with `real/` and `fake/` sub-folders of images (.jpg/.png/.webp) or videos (.mp4/.mov/
.avi/.mkv/.webm):   KIT/my_set/real/*.jpg   KIT/my_set/fake/*.mp4   ...

  --transport    re-encode every frame the way the customer's browser uploads it (at most 640 px wide, JPEG quality 85)
  --kyc-framing  videos only: cut a 4:3 window ~3.5x the face width around the face before --transport, so wide shots look like a
                 webcam KYC call (otherwise their faces end up too small and are skipped)

Reported per set and overall (positive class = fake):
  ROC AUC                threshold-free separation of real and fake (0.5 = coin toss, 1.0 = perfect)
  acc / TPR / FPR @ thr  at the configured VIDEO_FLAG_THRESHOLD: TPR = fakes caught, FPR = real people wrongly flagged
  TPR @ FPR 5 %          fakes caught when at most 5 % of real people may be flagged
  skipped                items with no scorable face (NO_FACE / FACE_TOO_SMALL); they are listed, not silently dropped
Videos are scored per frame and summarised per video by the mean (and the worst quarter) of their frame scores.

The numbers are only as good as the data: use sets the model was NOT trained on (its training pool is the OpenForensics-based
"Deepfake and real images" collection), and report them together with the data source, never on their own."""
import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyapan.settings")
import django  # noqa: E402

django.setup()
from apps.core.runtime import get_runtime  # noqa: E402
from apps.devlab.metrics import roc_auc  # noqa: E402

IMAGES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEOS = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def transport(rgb: np.ndarray) -> np.ndarray:
    im = Image.fromarray(rgb)
    if im.width > 640:
        im = im.resize((640, round(im.height * 640 / im.width)), Image.BILINEAR)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return np.asarray(Image.open(io.BytesIO(b.getvalue())).convert("RGB"))


def kyc_framing(rgb: np.ndarray, detect) -> np.ndarray | None:
    faces = detect(rgb)
    if not faces:
        return None
    x, y, w, h = faces[0]["box"]
    H, W = rgb.shape[:2]
    ww = min(W, int(max(w, h) * 3.5))
    hh = min(H, int(ww * 3 / 4))
    x0 = int(min(max(0, x + w / 2 - ww / 2), W - ww))
    y0 = int(min(max(0, y + h / 2 - hh / 2), H - hh))
    return rgb[y0:y0 + hh, x0:x0 + ww]


def frames_of(path: Path, n: int):
    if path.suffix.lower() in IMAGES:
        yield np.asarray(Image.open(path).convert("RGB"))
        return
    import cv2
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for idx in np.linspace(total * 0.1, total * 0.9, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, bgr = cap.read()
        if ok:
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    cap.release()


def metrics(pairs: list[tuple[float, int]], thr: float) -> dict:
    if not pairs:
        return {"n": 0}
    s = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    pos, neg = s[y == 1], s[y == 0]
    out = {"n": len(pairs), "n_real": int(len(neg)), "n_fake": int(len(pos)), "auc": roc_auc(pairs)}
    if len(pos) and len(neg):
        tpr, fpr = float((pos >= thr).mean()), float((neg >= thr).mean())
        out.update(acc=round(float(((s >= thr) == (y == 1)).mean()), 4), tpr=round(tpr, 4), fpr=round(fpr, 4), balanced_acc=round((tpr + 1 - fpr) / 2, 4))
        t5 = float(np.quantile(neg, 0.95))  # threshold that flags at most 5 % of the real items
        out.update(tpr_at_fpr5=round(float((pos > t5).mean()), 4), thr_at_fpr5=round(t5, 4),
                   mean_real=round(float(neg.mean()), 4), mean_fake=round(float(pos.mean()), 4))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kit")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--per-class", type=int, default=10**9)
    ap.add_argument("--transport", action="store_true")
    ap.add_argument("--kyc-framing", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    rt = get_runtime()
    det = rt.registry.get("vit")
    if det is None or not det.ensure_loaded():
        sys.exit(f"The vit detector is not available: {getattr(det, '_error', 'disabled')}. Run scripts/download_models.py --video --faces.")
    from apps.biometrics.faces import engine_or_none
    eng = engine_or_none(rt.settings.model_dir)
    thr = det.threshold
    cfg = rt.settings
    print(f"model {cfg.video_model_repo}  threshold {thr}  crop margin {cfg.video_crop_margin}  flip {cfg.video_tta_flip}  min face {cfg.video_min_face_px}px")
    results, t0 = [], time.time()
    for ds in sorted(p for p in Path(a.kit).iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        for label in ("real", "fake"):
            files = sorted(f for f in (ds / label).glob("*") if f.suffix.lower() in IMAGES + VIDEOS)[:a.per_class] if (ds / label).is_dir() else []
            for f in files:
                scores, skipped = [], []
                for rgb in frames_of(f, a.frames):
                    if a.kyc_framing and f.suffix.lower() in VIDEOS and eng is not None:
                        rgb = kyc_framing(rgb, eng.detect)
                        if rgb is None:
                            skipped.append("NO_FACE")
                            continue
                    if a.transport:
                        rgb = transport(rgb)
                    r = det.analyze(Image.fromarray(rgb))
                    if r["status"] == "ok":
                        scores.append(float(r["score"]))
                    else:
                        skipped.append(r.get("error_code") or r["status"])
                results.append({"set": ds.name, "label": label, "file": f.name, "scores": scores, "skipped": skipped})
            print(f"  {ds.name}/{label}: {len(files)} items ({time.time() - t0:.0f}s)", flush=True)
    report = {"model": cfg.video_model_repo, "threshold": thr, "settings": {"crop_margin": cfg.video_crop_margin, "tta_flip": cfg.video_tta_flip,
              "min_face_px": cfg.video_min_face_px, "transport": a.transport, "kyc_framing": a.kyc_framing, "frames_per_video": a.frames}, "sets": {}}
    for name in sorted({r["set"] for r in results}) + ["ALL"]:
        rows = [r for r in results if name in ("ALL", r["set"])]
        scored = [r for r in rows if r["scores"]]
        pairs = [(float(np.mean(r["scores"])), int(r["label"] == "fake")) for r in scored]
        worst = [(float(np.mean(sorted(r["scores"], reverse=True)[:max(1, -(-len(r["scores"]) // 4))])), int(r["label"] == "fake")) for r in scored]
        report["sets"][name] = {"items": len(rows), "skipped_items": len(rows) - len(scored), "per_item_mean": metrics(pairs, thr),
                                "per_item_worst_quarter": metrics(worst, thr) if any(len(r["scores"]) > 1 for r in scored) else None}
    print(f"\n{'set':<16}{'items':>6}{'skip':>6}{'AUC':>8}{'acc':>8}{'TPR':>8}{'FPR':>8}{'TPR@5%FPR':>11}  (at threshold {thr})")
    for name, r in report["sets"].items():
        m = r["per_item_mean"]
        f = lambda k: f"{m[k]:.3f}" if m.get(k) is not None else "  -  "  # noqa: E731
        print(f"{name:<16}{r['items']:>6}{r['skipped_items']:>6}{f('auc'):>8}{f('acc'):>8}{f('tpr'):>8}{f('fpr'):>8}{f('tpr_at_fpr5'):>11}")
    if a.out:
        Path(a.out).write_text(json.dumps({**report, "items": results}, indent=1))
        print(f"\nfull results: {a.out}")


if __name__ == "__main__":
    main()
