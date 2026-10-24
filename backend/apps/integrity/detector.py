from apps.integrity.logic import FLAG_AT, evaluate_probe
from apps.signals.detector_base import BaseDetector


class IntegrityDetector(BaseDetector):
    """Family 1, pipeline integrity: rule-based, two checks in one signal.
      camera - physical camera or virtual / injected video (apps/integrity/logic.py)
      ip     - VPN / proxy / Tor / data-centre / spoofed or changing address (apps/integrity/ipintel.py)
    Input: {'probe': browser probe dict, 'net': the server's IP assessment dict or None}. score = the higher of the two risks (0..1);
    a check that could not be judged contributes nothing (never suspicion)."""
    name, signal_type, model_id, score_kind = "integrity", "pipeline_integrity", None, "rule_based"
    expected = False  # counts when the browser sends a probe; a session without one is not reported as "missing"

    @property
    def threshold(self):
        return FLAG_AT

    def load(self) -> None:
        pass

    def _infer(self, media, metadata):
        cam = evaluate_probe(media.get("probe") or {})
        net = media.get("net")
        checks, scores, notes = {}, [], []
        if cam["status"] == "ok":
            scores.append(cam["score"])
            checks["camera"] = {"klass": cam["klass"], "risk": cam["score"], "flags": cam["flags"], "label": str((media.get("probe") or {}).get("camera_label") or "")[:80], **cam["metrics"]}
            notes += cam["notes"]
        else:
            checks["camera"] = {"klass": "unknown", "risk": None, "error_code": cam["error_code"], **cam["metrics"]}
        if net:
            checks["ip"] = {"klass": net["klass"], "risk": net["score"], "flags": net["flags"], "error_code": net.get("error_code"), **net["details"]}
            if net["status"] == "ok":
                scores.append(net["score"])
            notes += net["notes"]
        if not scores:
            return self.result("low_quality", error_code=cam["error_code"] or "NO_PROBE_DATA", details={"notes": notes, "checks": checks})
        score = max(scores)
        which = [k for k in ("camera", "ip") if checks.get(k, {}).get("risk") is not None and checks[k]["risk"] >= FLAG_AT]
        return self.result("ok", round(score, 3), label=("raised: " + ", ".join(which)) if which else "no hard indicator", details={"notes": notes, "checks": checks, "raised": which})
