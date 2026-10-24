"""Pure-logic tests (no database, no models): face geometry, iris coding, the camera probe and IP intelligence."""
import numpy as np

from apps.biometrics import geometry as g
from apps.biometrics import iris


# ---------------------------------------------------------------- synthetic face mesh

def face(yaw_deg=0.0, ear=0.30, mar=0.05, eye_dist=0.2, iris_r=0.02):
    """478 landmarks on a 1000x1000 image; only the indices the code reads are placed."""
    lm = np.full((478, 3), 0.5, dtype=np.float64)

    def put(i, x, y):
        lm[i, 0], lm[i, 1] = x, y
    put(33, 0.5 - eye_dist / 2, 0.40), put(263, 0.5 + eye_dist / 2, 0.40)
    offset = 0.5 * np.sin(np.radians(yaw_deg))
    put(1, 0.5 - offset * eye_dist, 0.52)                       # positive yaw: nose toward the person's right = smaller x
    a = ear * 0.06 / 2.0                                          # half the vertical lid gap for the wanted ear (horizontal = 0.06)
    # right eye (person's right = image left): p1 outer 33, p4 inner 133
    put(133, 0.46, 0.40)
    for i, x, dy in ((160, 0.42, -a), (144, 0.42, a), (158, 0.44, -a), (153, 0.44, a)):
        put(i, x, 0.40 + dy)
    # left eye: p1 inner 362, p4 outer 263
    put(362, 0.54, 0.40)
    for i, x, dy in ((385, 0.56, -a), (380, 0.56, a), (387, 0.58, -a), (373, 0.58, a)):
        put(i, x, 0.40 + dy)
    m = mar * 0.1 / 2.0
    put(78, 0.45, 0.70), put(308, 0.55, 0.70), put(13, 0.5, 0.70 - m), put(14, 0.5, 0.70 + m)
    for centre, ring, cx in ((468, (469, 470, 471, 472), 0.42), (473, (474, 475, 476, 477), 0.58)):
        put(centre, cx, 0.40)
        for k, (dx, dy) in zip(ring, ((iris_r, 0), (-iris_r, 0), (0, iris_r), (0, -iris_r))):
            put(k, cx + dx, 0.40 + dy)
    return lm


def test_yaw_sign_convention():
    right = g.measure(face(yaw_deg=30), 1000, 1000)
    left = g.measure(face(yaw_deg=-30), 1000, 1000)
    straight = g.measure(face(0), 1000, 1000)
    assert right["ok"] and 28 < right["yaw_right_deg"] < 32       # toward the person's own right = positive
    assert -32 < left["yaw_right_deg"] < -28
    assert abs(straight["yaw_right_deg"]) < 1


def test_openness_mouth_and_iris_measurements():
    m = g.measure(face(ear=0.30, mar=0.05), 1000, 1000)
    assert abs(m["ear_mean"] - 0.30) < 0.02 and abs(m["mar"] - 0.05) < 0.01
    assert abs(m["iris"]["right"]["r"] - 20) < 0.5 and abs(m["iris"]["left"]["cx"] - 580) < 0.5
    assert m["eye_dist_frac"] == 0.2
    assert g.measure(face(ear=0.05), 1000, 1000)["ear_mean"] < 0.1


def test_measure_rejects_bad_input():
    assert g.measure(None, 100, 100) == {"ok": False}
    assert g.measure(np.zeros((100, 3)), 100, 100) == {"ok": False}
    assert g.measure(np.full((478, 3), 0.5), 1000, 1000) == {"ok": False}   # all points identical: no eye distance
    assert g.measure(face()[:468], 1000, 1000)["iris"] is None             # no iris landmarks in a 468-point mesh


def _series(yaws=None, ears=None, mars=None):
    n = max(len(x) for x in (yaws, ears, mars) if x is not None)
    return [{"t": i * 0.2, "yaw_right_deg": (yaws or [0] * n)[i], "ear_mean": (ears or [0.3] * n)[i], "mar": (mars or [0.05] * n)[i], "eye_dist_frac": 0.2} for i in range(n)]


def test_series_turn_left_and_right():
    left = g.series_summary(_series(yaws=[0, 0, 1, -8, -18, -26, -25]))
    assert left["turn_left_deg"] > 24 and left["turn_right_deg"] < 3
    right = g.series_summary(_series(yaws=[2, 2, 2, 10, 20, 28, 27]))
    assert right["turn_right_deg"] > 24 and right["turn_left_deg"] < 1
    assert g.series_summary([])["n"] == 0
    assert g.series_summary([{"t": 0}])["n"] == 0      # a frame without a face contributes nothing


def test_series_counts_blinks_as_separate_dips():
    ears = [0.3, 0.3, 0.3, 0.05, 0.3, 0.3, 0.3, 0.06, 0.3, 0.3]
    assert g.series_summary(_series(ears=ears))["ear_dips"] == 2
    assert g.series_summary(_series(ears=[0.3] * 10))["ear_dips"] == 0
    held_shut = [0.3, 0.3, 0.05, 0.05, 0.05, 0.05, 0.3, 0.3]
    assert g.series_summary(_series(ears=held_shut))["ear_dips"] == 1     # one long blink is one dip, not four


def test_series_mouth_range():
    s = g.series_summary(_series(mars=[0.02, 0.2, 0.03, 0.25, 0.02, 0.2]))
    assert s["mar_range"] > 0.2
    assert g.series_summary(_series(mars=[0.05] * 6))["mar_range"] == 0.0


# ---------------------------------------------------------------- iris

def iris_image(seed, shift_deg=0.0, size=160, radius=40.0, noise=0.0, blur=1.0):
    """A synthetic iris: texture defined in polar coordinates, so rotating the eye is a shift along the angle."""
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(seed)
    tex = gaussian_filter(rng.normal(size=(24, 180)), (1.0, 2.0), mode=("nearest", "wrap"))
    tex = (tex - tex.mean()) / tex.std()
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    cx = cy = size / 2.0
    rho = np.hypot(xx - cx, yy - cy) / radius
    ang = (np.degrees(np.arctan2(-(yy - cy), xx - cx)) + shift_deg) % 360
    val = 120 + 35 * tex[np.clip((rho * 23).astype(int), 0, 23), (ang / 360 * 180).astype(int) % 180]
    val = np.where(rho <= 1.0, val, 200.0)
    val = np.where(rho < 0.35, 30.0, val)                       # pupil
    if noise:
        val = val + np.random.default_rng(seed + 1000).normal(0, noise, val.shape)
    val = gaussian_filter(val, blur)
    rgb = np.stack([val, val, val], -1)
    return np.clip(rgb, 0, 255).astype(np.uint8), {"cx": cx, "cy": cy, "r": radius}


def _template(seed, **kw):
    img, circ = iris_image(seed, **kw)
    return iris.enrol_eye(img, circ)


def test_iris_same_eye_matches_and_other_eye_does_not():
    ref = _template(1)
    assert ref["quality"]["usable"], ref["quality"]
    same = iris.compare(ref, _template(1, noise=4.0))
    other = iris.compare(ref, _template(2))
    assert same["bits"] > iris.MIN_BITS and same["hd"] < 0.25, same
    assert other["bits"] > iris.MIN_BITS and other["hd"] > 0.35, other


def test_iris_tolerates_head_tilt():
    ref = _template(3)
    tilted = iris.compare(ref, _template(3, shift_deg=15.0))
    assert tilted["hd"] < 0.25, tilted


def test_iris_small_or_blank_images_are_not_usable():
    img, circ = iris_image(4, size=60, radius=12.0)
    assert iris.enrol_eye(img, circ)["quality"]["usable"] is False            # 24 px across: too small to say anything
    flat = np.full((160, 160, 3), 120, np.uint8)
    assert iris.enrol_eye(flat, {"cx": 80, "cy": 80, "r": 40})["quality"]["usable"] is False   # no texture at all


def test_iris_template_survives_storage():
    t = _template(5)
    back = iris.unpack(iris.pack(t))
    assert (back["code"] == t["code"]).all() and (back["mask"] == t["mask"]).all()
    assert iris.compare(t, back)["hd"] == 0.0


def test_iris_comparison_without_enough_bits_gives_no_verdict():
    t = _template(6)
    empty = {"code": t["code"], "mask": np.zeros_like(t["mask"])}
    assert iris.compare(t, empty) == {"hd": 1.0, "bits": 0}
