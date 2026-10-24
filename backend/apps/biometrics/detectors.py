"""Identity detectors: face match (selfie vs live face) and iris match (close-up eye scan)."""
from __future__ import annotations

import numpy as np

from apps.biometrics import faces, geometry, iris
from apps.signals.detector_base import BaseDetector, DetectorError


class FaceMatchDetector(BaseDetector):
    """Is the face in the live frame the same person as in the reference photo? OpenCV YuNet + SFace (both permissive licences).
    score = 1 - cosine similarity (so, like every detector, higher = more suspicious); flagged when similarity < FACE_COSINE_THRESHOLD.
    Poor images (small, dark, blurry, several people) give 'low_quality', never a mismatch."""
    name, signal_type, score_kind = "facematch", "face_match", "one_minus_cosine_similarity"
    model_id = "opencv/yunet+sface"
    expected = False  # only when a reference photo exists

    @property
    def threshold(self):
        return round(1.0 - self.settings.face_cosine_threshold, 3)

    def load(self) -> None:
        self._eng = faces.get_engine(self.settings.model_dir)

    def embed_reference(self, rgb: np.ndarray) -> dict:
        """For the enrolment upload: -> {'ok', 'embedding', 'quality', 'face_count'}."""
        found = self._eng.detect(rgb)
        if not found:
            return {"ok": False, "code": "NO_FACE", "face_count": 0}
        q = faces.face_quality(rgb, found[0])
        if len(found) > 1 and found[1]["box"][2] * found[1]["box"][3] > 0.25 * found[0]["box"][2] * found[0]["box"][3]:
            return {"ok": False, "code": "MULTIPLE_FACES", "face_count": len(found), "quality": q}
        return {"ok": True, "embedding": self._eng.embed(rgb, found[0]).tolist(), "quality": q, "face_count": len(found)}

    def _infer(self, media, metadata):
        rgb = np.asarray(media["img"])
        ref = np.asarray(media["ref"], dtype=np.float32)
        found = self._eng.detect(rgb)
        if not found:
            return self.result("low_quality", error_code="NO_FACE", details={"face_count": 0})
        if len(found) > 1 and found[1]["box"][2] * found[1]["box"][3] > 0.25 * found[0]["box"][2] * found[0]["box"][3]:
            return self.result("low_quality", error_code="MULTIPLE_FACES", details={"face_count": len(found)})
        q = faces.face_quality(rgb, found[0])
        if not q["usable"]:
            return self.result("low_quality", error_code=q["issues"][0], details={"quality": q})
        sim = faces.cosine(self._eng.embed(rgb, found[0]), ref)
        score = float(np.clip(1.0 - sim, 0.0, 1.0))
        return self.result("ok", round(score, 4), label="match" if sim >= self.settings.face_cosine_threshold else "mismatch",
                           details={"similarity": round(sim, 4), "cosine_threshold": self.settings.face_cosine_threshold, "quality": q})


class EyeScanDetector(BaseDetector):
    """Iris pattern match between the enrolment photo and the close-up 'eye scan' challenge frames (see iris.py for the honest
    description: iris texture from ordinary cameras, not a retina scan). Verdicts: match | mismatch | uncertain | not_enough_detail."""
    name, signal_type, score_kind = "eyescan", "iris_match", "iris_hamming_risk"
    model_id = "classical log-Gabor iris code + mediapipe iris landmarks"
    expected = False

    @property
    def threshold(self):
        return 0.7

    def load(self) -> None:
        from apps.core.runtime import get_runtime
        lm = get_runtime().registry.get("landmarks")
        if lm is None or not lm.ensure_loaded():
            raise DetectorError("LANDMARKS_UNAVAILABLE")
        self._lm = lm

    def _score(self, hd: float) -> float:
        s = self.settings
        return float(np.clip((hd - s.iris_match_hd) / max(1e-6, (s.iris_mismatch_hd - s.iris_match_hd)) * 0.7, 0.0, 1.0))

    def template_from_frame(self, rgb: np.ndarray) -> dict:
        """Per-eye templates and face measurements from one image. -> {'face': measure dict or None, 'eyes': {'right': tpl, 'left': tpl}}"""
        n, lm = self._lm.landmarks(rgb)
        if n != 1:
            return {"face": None, "n_faces": n, "eyes": {}}
        h, w = rgb.shape[:2]
        m = geometry.measure(lm, w, h)
        if not m.get("ok") or not m.get("iris"):
            return {"face": None, "n_faces": n, "eyes": {}}
        eyes = {}
        for side in ("right", "left"):
            t = iris.enrol_eye(rgb, m["iris"][side])
            if t is not None:
                eyes[side] = t
        return {"face": m, "n_faces": n, "eyes": eyes}

    # media = {"frames": [rgb arrays], "ref": {"right": packed, "left": packed}}
    def _infer(self, media, metadata):
        s = self.settings
        ref = {k: iris.unpack(v) for k, v in (media.get("ref") or {}).items() if v}
        hds: dict[str, list[float]] = {"right": [], "left": []}
        diams: list[float] = []  # iris diameter of each comparison (the smaller of reference and probe)
        usable_frames, per_frame, max_close, max_ear = 0, [], 0.0, 0.0
        for rgb in media["frames"]:
            t = self.template_from_frame(np.asarray(rgb))
            f = t["face"]
            if f is None:
                per_frame.append({"face": False})
                continue
            max_close, max_ear = max(max_close, f["eye_dist_frac"]), max(max_ear, f["ear_mean"])
            row = {"face": True, "eye_dist_frac": f["eye_dist_frac"], "ear": f["ear_mean"]}
            ok_any = False
            for side, tpl in t["eyes"].items():
                q = tpl["quality"]
                row[side] = {"diameter_px": q["diameter_px"], "usable": q["usable"], "quality": q["score"]}
                if q["usable"] and side in ref and ref[side]["quality"].get("usable"):
                    cmp = iris.compare(ref[side], tpl)
                    if cmp["bits"] >= iris.MIN_BITS:
                        hds[side].append(cmp["hd"])
                        diams.append(min(q["diameter_px"], ref[side]["quality"].get("diameter_px", 0.0)))
                        row[side]["hd"] = cmp["hd"]
                        ok_any = True
            usable_frames += int(ok_any)
            per_frame.append(row)
        details = {"frames_received": len(media["frames"]), "frames_with_usable_iris": usable_frames, "max_eye_distance_fraction": round(max_close, 3),
                   "max_eye_openness": round(max_ear, 3), "per_frame": per_frame[:8], "hd_right": [round(x, 3) for x in hds["right"]], "hd_left": [round(x, 3) for x in hds["left"]],
                   "match_hd": s.iris_match_hd, "mismatch_hd": s.iris_mismatch_hd}
        all_hd = hds["right"] + hds["left"]
        if not ref:
            return self.result("low_quality", error_code="NO_REFERENCE_IRIS", details=details)
        if not all_hd:
            return self.result("low_quality", error_code="IRIS_DETAIL_TOO_LOW", details=details)
        eye_med = [float(np.median(v)) for v in hds.values() if v]
        hd = float(np.mean(eye_med))
        bad = sum(1 for x in all_hd if x >= s.iris_mismatch_hd)
        diam = float(np.median(diams))
        details["iris_diameter_px"] = round(diam, 1)
        if diam < s.iris_min_verdict_px:
            # Measured on real photo pairs (two photos of the same person vs different people): with irises of 40-55 px the code
            # barely separates people (AUC ~0.62), so a match/mismatch verdict would be wrong far too often. Report it, judge nothing.
            details.update({"hamming_distance": round(hd, 4), "verdict": "uncertain", "readings": len(all_hd), "why": "IRIS_TOO_SMALL_FOR_VERDICT"})
            return self.result("ok", round(min(self._score(hd), 0.6), 4), label="uncertain", details=details)
        if hd <= s.iris_match_hd:
            verdict = "match"
        elif hd >= s.iris_mismatch_hd and bad >= 2:
            verdict = "mismatch"   # needs at least two separate readings to agree
        else:
            verdict = "uncertain"
        details.update({"hamming_distance": round(hd, 4), "verdict": verdict, "readings": len(all_hd)})
        score = self._score(hd) if verdict != "uncertain" else min(self._score(hd), 0.6)  # an uncertain result never reaches the flag threshold
        return self.result("ok", round(score, 4), label=verdict, details=details)
