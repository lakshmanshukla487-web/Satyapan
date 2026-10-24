"""Download model files into MODEL_DIR (default ./models). Run only when you intend to: weights are large and have their own licences.

    python scripts/download_models.py --all            # everything below except the voice model
    python scripts/download_models.py --video          # video deepfake classifier (Apache-2.0)        -> models/video/
    python scripts/download_models.py --faces          # OpenCV YuNet + SFace (face match, Apache-2.0) -> models/*.onnx
    python scripts/download_models.py --landmarks      # MediaPipe face landmarker (Apache-2.0)        -> models/face_landmarker.task
    python scripts/download_models.py --syncnet        # SyncNet lip-sync weights (RESEARCH-ONLY licence!) -> models/syncnet/
    python scripts/download_models.py --speech         # Whisper speech-to-text for the 'say three words' challenge (MIT) -> models/speech/

The fine-tuned VOICE model is yours: copy model.safetensors into models/audio/ (config.json and preprocessor_config.json are already there)."""
import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

VIDEO_REPO = os.getenv("VIDEO_MODEL_REPO", "prithivMLmods/Deep-Fake-Detector-v2-Model")
FILES = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
LANDMARKER = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
SYNCNET = "http://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model"


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  {url}\n  -> {dest}")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    print(f"  sha256 {hashlib.sha256(dest.read_bytes()).hexdigest()}  ({dest.stat().st_size // 1024} KB)")


p = argparse.ArgumentParser()
for f in ("all", "video", "faces", "landmarks", "syncnet", "speech"):
    p.add_argument(f"--{f}", action="store_true")
a = p.parse_args()
if not any(vars(a).values()):
    p.print_help()
    sys.exit(1)
root = Path(os.getenv("MODEL_DIR", "./models"))
root.mkdir(parents=True, exist_ok=True)
failed = []


def step(name: str, fn) -> None:
    print(f"[{name}]")
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        failed.append(name)
        print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)


if a.all or a.video:
    def _video():
        from huggingface_hub import snapshot_download
        print(f"  {VIDEO_REPO} (check the model card licence before deployment)")
        snapshot_download(VIDEO_REPO, local_dir=root / "video", allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors", "README.md"])  # not the training checkpoints
    step("video deepfake model", _video)
if a.all or a.faces:
    for name, url in FILES.items():
        step(name, lambda n=name, u=url: fetch(u, root / n))
if a.all or a.landmarks:
    def _landmarks():
        local = Path(__file__).resolve().parents[2] / "frontend" / "public" / "models" / "face_landmarker.task"  # same file, already in the repo
        if local.is_file():
            import shutil
            shutil.copyfile(local, root / "face_landmarker.task")
            print(f"  copied {local} -> {root / 'face_landmarker.task'}")
        else:
            fetch(LANDMARKER, root / "face_landmarker.task")
    step("face landmarker", _landmarks)
if a.all or a.speech:
    def _speech():
        from huggingface_hub import snapshot_download
        repo = os.getenv("SPEECH_MODEL_REPO", "openai/whisper-base")
        print(f"  {repo} (MIT licence)")
        snapshot_download(repo, local_dir=root / "speech", allow_patterns=["*.json", "*.txt", "*.safetensors"])
    step("speech-to-text model", _speech)
if a.all or a.syncnet:
    print("NOTE: the SyncNet weights are published by the Oxford VGG group for RESEARCH use. Get a commercial licence or train your own before commercial deployment.")
    step("syncnet", lambda: fetch(SYNCNET, root / "syncnet" / "syncnet_v2.model"))
print("\nVoice model: copy your model.safetensors to", root / "audio" / "model.safetensors")
print("Then run: python scripts/verify_models.py")
sys.exit(1 if failed else 0)
