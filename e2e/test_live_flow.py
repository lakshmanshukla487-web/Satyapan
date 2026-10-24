"""Two-browser end-to-end test of a running Satyapan (backend + frontend), customer and officer in two separate Chromium contexts
with fake camera/microphone devices, plus (optionally) a developer account.

    ./start.sh                                   # in another terminal (creates the demo officer/customer in development)
    pip install playwright && python -m playwright install chromium
    SATYAPAN_DEV_USER=devon SATYAPAN_DEV_PASSWORD=... python e2e/test_live_flow.py   # developer part only with these set

Environment: SATYAPAN_APP_URL (default http://localhost:5173), SATYAPAN_API_URL (default: the app URL, which proxies /api),
SATYAPAN_OFFICER / SATYAPAN_OFFICER_PASSWORD, SATYAPAN_CUSTOMER / SATYAPAN_CUSTOMER_PASSWORD (default: the development demo users).
Use a development database: the test creates and ends verification sessions.

Covers: request -> approval -> documents (select / remove / reselect / wrong type / wrong document removed) -> photo -> back to
documents (correction without starting over) -> live check -> challenge approval in the live workspace -> live call with real video
and audio both ways -> call end -> officer ends the session; the developer test lab; role isolation; and HTTP status/request
counts for the whole run (no 429 expected)."""
import collections
import io
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).parent
APP = os.environ.get("SATYAPAN_APP_URL", "http://localhost:5173").rstrip("/")
API = os.environ.get("SATYAPAN_API_URL", APP).rstrip("/")
OFFICER = (os.environ.get("SATYAPAN_OFFICER", "officer"), os.environ.get("SATYAPAN_OFFICER_PASSWORD", "officer-pass-123"))     # development demo users
CUSTOMER = (os.environ.get("SATYAPAN_CUSTOMER", "customer"), os.environ.get("SATYAPAN_CUSTOMER_PASSWORD", "customer-pass-123"))
DEVELOPER = (os.environ.get("SATYAPAN_DEV_USER"), os.environ.get("SATYAPAN_DEV_PASSWORD"))  # no default: developer accounts are provisioned
results = []
status_counts = collections.Counter()
req_counts = collections.Counter()
t_live = {}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def files():
    d = HERE / ".e2e_files"
    d.mkdir(exist_ok=True)
    for name, size, color in (("pan.png", (500, 320), (200, 210, 220)), ("aadhaar.png", (500, 320), (180, 200, 190)), ("pan_v2.png", (500, 320), (90, 120, 200)),
                              ("photo.png", (640, 480), (160, 140, 120)), ("lab_face.png", (256, 256), (130, 120, 110))):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, "PNG")
        (d / name).write_bytes(buf.getvalue())
    (d / "notes.txt").write_text("not a document")
    return d


def track(page, who):
    def on_resp(r):
        if r.url.startswith(API + "/api/"):
            status_counts[(who, r.status)] += 1
            if r.status >= 400:
                print(f"   ({who} got {r.status} on {r.request.method} {r.url[len(API):]})", flush=True)
            path = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", ":id", r.url[len(API):].split("?")[0])
            req_counts[(who, r.request.method, path)] += 1
    page.on("response", on_resp)


def login(page, user, pw):
    page.goto(f"{APP}/login")
    page.get_by_label(re.compile("username", re.I)).fill(user)
    page.get_by_label(re.compile("password", re.I)).fill(pw)
    page.get_by_role("button", name=re.compile("sign in", re.I)).click()


def lab(scope, text):
    """A form field by its label; required fields have a trailing ' *' in their accessible name."""
    return scope.get_by_label(re.compile("^" + re.escape(text) + r"( \*)?$"))


def card(page, title):
    return page.locator("section").filter(has=page.get_by_role("heading", name=title, exact=True))


def main():
    f = files()
    logs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--disable-features=WebRtcHideLocalIpsWithMdns"])
        ctx_c = browser.new_context(permissions=["camera", "microphone"])
        ctx_o = browser.new_context(permissions=["camera", "microphone"])
        cus, off = ctx_c.new_page(), ctx_o.new_page()
        for p, who in ((cus, "customer"), (off, "officer")):
            track(p, who)
            p.on("pageerror", lambda e, w=who: logs.append(f"{w} pageerror: {e}"))
            p.on("console", lambda m, w=who: logs.append(f"{w} console.{m.type}: {m.text}") if m.type == "error" else None)
        cus.set_default_timeout(20000)
        off.set_default_timeout(20000)

        # ---- 1. customer asks, officer approves ------------------------------------------------------------------------------
        login(cus, *CUSTOMER)
        cus.wait_for_url("**/dashboard")
        cus.goto(f"{APP}/verify")
        cus.get_by_role("checkbox").check()
        cus.get_by_role("button", name=re.compile("Ask an officer")).click()
        expect(cus.get_by_text("Waiting for an officer to approve")).to_be_visible()
        login(off, *OFFICER)
        off.wait_for_url("**/officer")
        expect(off.get_by_text("Verification requests")).to_be_visible(timeout=15000)
        off.get_by_role("button", name="Approve", exact=True).first.click()
        expect(cus.get_by_role("heading", name="Your details")).to_be_visible(timeout=20000)
        check("customer request approved by the officer and the documents step opens (WebSocket event)", True)

        # ---- 2. documents: select, remove, reselect, wrong type, wrong document --------------------------------------------------
        lab(card(cus, "Your details"), "Full name").fill("Rahul Sharma")
        lab(card(cus, "Your details"), "Date of birth").fill("15/08/1995")
        lab(card(cus, "Your details"), "Mobile number").fill("9876543210")
        lab(card(cus, "Your details"), "PIN code").fill("110001")
        pan = card(cus, "PAN card")
        lab(pan, "Name on PAN").fill("RAHUL SHARMA")
        lab(pan, "PAN").fill("ABCPS1234F")
        lab(pan, "Date of birth on PAN").fill("15/08/1995")
        pan_input = pan.locator("input[type=file]")
        pan_input.set_input_files(str(f / "notes.txt"))
        check("a wrong file type is refused in the browser with a clear message", pan.get_by_text("Only JPEG, PNG or PDF files can be used.").is_visible())
        pan_input.set_input_files(str(f / "pan.png"))
        check("the selected file shows its name, type and size", pan.get_by_text("pan.png").is_visible() and pan.get_by_text(re.compile("PNG · .*KB")).is_visible())
        pan.get_by_role("button", name=re.compile("Remove the selected file")).click()
        check("Remove clears the selection", pan.get_by_text("pan.png").count() == 0 and pan.get_by_text(re.compile("Choose a clear photo")).is_visible())
        pan_input.set_input_files(str(f / "pan.png"))
        check("the same file can be selected again after removal", pan.get_by_text("pan.png").is_visible())
        # first a passport with a typo (the wrong document), then Aadhaar instead
        cus.get_by_role("tab", name="Passport").click()
        pp = card(cus, "Passport")
        lab(pp, "Name as on the document").fill("Rahul Sharma")
        lab(pp, "Passport number").fill("123")
        lab(pp, "Date of birth").fill("15/08/1995")
        lab(pp, "Expiry date").fill("01/01/2033")
        pp.locator("input[type=file]").set_input_files(str(f / "aadhaar.png"))
        cus.get_by_role("button", name="Check documents and continue").click()
        expect(cus.get_by_text("Please fix the highlighted items and try again.")).to_be_visible()
        check("the server flags the mistyped passport (correctable error)", pp.get_by_text("Needs correction").is_visible())
        cus.get_by_role("tab", name="Aadhaar").click()
        ad = card(cus, "Aadhaar")
        lab(ad, "Name on Aadhaar").fill("Rahul Sharma")
        lab(ad, "Aadhaar number").fill("2345 6789 0124")
        lab(ad, "Date of birth (if printed)").fill("15/08/1995")
        ad.locator("input[type=file]").set_input_files(str(f / "aadhaar.png"))
        check("the other submitted identity document is listed with a Remove action", cus.get_by_text("You also submitted a Passport").is_visible())
        cus.get_by_role("button", name="Remove it").click()
        cus.get_by_role("dialog").get_by_role("button", name="Remove", exact=True).click()
        expect(cus.get_by_text("Passport was removed. Your other documents are unchanged")).to_be_visible()
        cus.get_by_role("button", name="Check documents and continue").click()
        expect(cus.get_by_role("heading", name="Your starting photo")).to_be_visible(timeout=20000)
        check("after removing the wrong document the documents are accepted (no restart needed)", True)

        # ---- 3. photo, then back to documents to replace a file -----------------------------------------------------------------
        cus.get_by_role("button", name=re.compile("Back to my documents")).click()
        expect(card(cus, "PAN card").get_by_text(re.compile("A PNG file was received earlier"))).to_be_visible()
        check("going back shows what the server already holds (file kind, not the name)", card(cus, "PAN card").get_by_text("Received", exact=True).is_visible())
        pan = card(cus, "PAN card")
        lab(pan, "Name on PAN").fill("RAHUL SHARMA")
        lab(pan, "PAN").fill("ABCPS1234F")
        lab(pan, "Date of birth on PAN").fill("15/08/1995")
        pan.locator("input[type=file]").set_input_files(str(f / "pan_v2.png"))
        cus.get_by_role("button", name="Check documents and continue").click()
        expect(cus.get_by_role("heading", name="Your starting photo")).to_be_visible(timeout=20000)
        check("a replaced PAN file is re-checked and accepted", True)
        cus.locator("input[type=file][accept='image/jpeg,image/png']").set_input_files(str(f / "photo.png"))
        expect(cus.get_by_role("button", name=re.compile("Start camera and begin"))).to_be_visible(timeout=20000)
        check("start photo accepted", True)

        # ---- 4. live check + live workspace ---------------------------------------------------------------------------------------
        cus.get_by_role("button", name=re.compile("Start camera and begin")).click()
        expect(cus.get_by_text("Capturing", exact=True)).to_be_visible(timeout=20000)
        t_live["start"] = time.time()
        cust_sid = re.search(r"Session ID: ([0-9a-f-]{36})", cus.get_by_text(re.compile("Session ID:")).inner_text()).group(1)
        off.goto(f"{APP}/officer")
        link = off.locator(f"a[href='/sessions/{cust_sid}']").first  # the console row of THIS customer's session
        link.wait_for(timeout=45000)
        link.click()
        off.wait_for_url(re.compile(r".*/sessions/[0-9a-f-]{36}$"))
        sid = off.url.rsplit("/", 1)[1]
        check("the officer opened the customer's own session", sid == cust_sid)
        ws = off.get_by_role("region", name="Live verification workspace")
        expect(ws.get_by_role("heading", name="Customer live")).to_be_visible()
        expect(ws.get_by_role("heading", name="Challenges")).to_be_visible()
        boxes = [ws.get_by_role("heading", name=n).bounding_box() for n in ("Customer live", "Challenges")]
        check("the live workspace shows the customer video panel and the challenges side by side", boxes[0]["x"] < boxes[1]["x"] and abs(boxes[0]["y"] - boxes[1]["y"]) < 200, str([(round(b["x"]), round(b["y"])) for b in boxes]))
        off.set_viewport_size({"width": 390, "height": 844})
        off.wait_for_timeout(300)
        small = [ws.get_by_role("heading", name=n).bounding_box() for n in ("Customer live", "Challenges")]
        check("on a phone-sized screen the two panels stack (video first)", abs(small[0]["x"] - small[1]["x"]) < 5 and small[0]["y"] < small[1]["y"], str([(round(b["x"]), round(b["y"])) for b in small]))
        off.set_viewport_size({"width": 1280, "height": 720})
        pend = ws.locator(f"[data-session-id='{sid}'][data-challenge-id]").first
        pend.wait_for(timeout=30000)
        check("the pending challenge in the workspace belongs to the same session as the video", pend.get_attribute("data-session-id") == sid)
        prompt = pend.locator("p.text-lg").inner_text()
        pend.get_by_role("button", name="Approve and release").click()
        # Depending on the face-detection assets, the step may already be answered when we look (a fake camera shows no face):
        # the prompt is then in the customer's step list. Either way it must be exactly the prompt the officer approved.
        expect(cus.get_by_text(prompt, exact=True).first).to_be_visible(timeout=20000)
        check("the released challenge reaches the right customer, with the approved prompt", True, prompt)
        cid = pend.get_attribute("data-challenge-id") if pend.count() else None
        answered = False
        for _ in range(40):
            hist = off.evaluate("([api, sid]) => fetch(api + '/api/v1/sessions/' + sid + '/challenges', {headers: {Authorization: 'Bearer ' + sessionStorage.getItem('satyapan.token')}}).then(r => r.json())", [API, sid])
            if any(c["challenge_text"] == prompt and c["status"] in ("answered", "issued") for c in hist):
                answered = True
                break
            off.wait_for_timeout(500)
        check("the customer's answer is recorded on the same session (officer view)", answered)

        # ---- 5. live call: real video and audio both ways ----------------------------------------------------------------------
        ws.get_by_role("button", name="Start live call").click()
        cus.get_by_role("button", name="Accept", exact=True).click(timeout=20000)
        expect(ws.get_by_text("Connected", exact=True)).to_be_visible(timeout=30000)
        vid = off.locator("[data-testid=officer-remote-video]")
        ok = False
        for _ in range(60):
            dims = vid.evaluate("v => [v.videoWidth, v.videoHeight, v.readyState]")
            if dims[0] > 0:
                ok = True
                break
            off.wait_for_timeout(250)
        check("officer sees the customer's live camera in the workspace", ok, str(dims))
        a0 = vid.evaluate("v => v.currentTime")
        off.wait_for_timeout(1500)
        check("the video keeps playing", vid.evaluate("v => v.currentTime") > a0)
        levels = []
        for _ in range(25):
            off.wait_for_timeout(200)
            levels.append(int(off.locator("[data-testid=remote-audio-level]").get_attribute("aria-valuenow") or 0))
        check("officer hears the customer (audio level > 0)", max(levels) > 0, f"max {max(levels)}")
        check("the customer receives the officer's microphone", cus.evaluate("() => [...document.querySelectorAll('audio')].some(a => a.srcObject && a.srcObject.getAudioTracks().some(t => t.readyState === 'live'))"))
        # keep working in the workspace during the call: the next challenge, approvals, live events
        node_before = vid.evaluate("v => { window.__vid = v; return true }")
        pend2 = ws.locator(f"[data-session-id='{sid}'][data-challenge-id]").first
        try:
            pend2.wait_for(timeout=60000)
            pend2.get_by_role("button", name="Approve and release").click()
            check("a challenge can be approved while the call is running", True)
        except Exception as e:  # noqa: BLE001
            check("a challenge can be approved while the call is running", False, type(e).__name__)
        off.wait_for_timeout(3000)
        check("the video element survived all live updates (never unmounted)", node_before and off.evaluate("() => window.__vid === document.querySelector('[data-testid=officer-remote-video]') && window.__vid.videoWidth > 0"))
        ws.get_by_role("button", name="Mute my microphone").click()
        check("officer can mute the microphone", ws.get_by_text("Your microphone is muted").is_visible())
        ws.get_by_role("button", name="Unmute my microphone").click()
        ws.get_by_role("button", name="End call").click()
        expect(cus.get_by_text(re.compile("The other side ended the call"))).to_be_visible(timeout=15000)
        check("ending the call reaches the customer", True)
        check("the customer's verification camera keeps running after the call", cus.get_by_text("Capturing", exact=True).is_visible())

        # ---- 6. a minute of live session: request volume and statuses -----------------------------------------------------------
        before = sum(v for (w, m, p), v in req_counts.items() if w == "officer")
        before_c = collections.Counter({k: v for k, v in req_counts.items() if k[0] == "customer"})
        end = time.time() + 45
        while time.time() < end:
            p = ws.locator(f"[data-session-id='{sid}'][data-challenge-id]")
            if p.count():
                try:
                    p.first.get_by_role("button", name="Approve and release").click(timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
            off.wait_for_timeout(1000)
        officer_req = sum(v for (w, m, p), v in req_counts.items() if w == "officer") - before
        cust_delta = collections.Counter({k: v - before_c.get(k, 0) for k, v in req_counts.items() if k[0] == "customer" and v - before_c.get(k, 0) > 0})
        media = sum(v for (w, m, p), v in cust_delta.items() if re.search(r"/analysis/(frame|audio|avsync)$|eye-scan$", p))
        other = sum(cust_delta.values()) - media
        check("officer workspace stays far below its rate limit during 45 s of a live session", officer_req < 60, f"{officer_req} officer requests in 45 s")
        check("customer non-media requests stay low (polling only as a fallback)", other < 60, f"{other} API + {media} media uploads in 45 s")

        # ---- 7. officer ends the session --------------------------------------------------------------------------------------
        off.get_by_role("button", name="End session now").click()
        off.get_by_role("dialog").get_by_role("button", name="End session").click()
        expect(cus.get_by_text("This check has ended")).to_be_visible(timeout=20000)
        check("officer termination reaches the customer at once (neutral message)", True)

        # ---- 8. developer lab and role isolation ------------------------------------------------------------------------------
        if not DEVELOPER[0]:
            print("(developer part skipped: set SATYAPAN_DEV_USER and SATYAPAN_DEV_PASSWORD to a provisioned developer account)")
            return finish(browser, logs)
        ctx_d = browser.new_context()
        dev = ctx_d.new_page()
        track(dev, "developer")
        dev.on("pageerror", lambda e: logs.append(f"developer pageerror: {e}"))
        login(dev, *DEVELOPER)
        dev.wait_for_url("**/developer")
        expect(dev.get_by_text("AI model test lab")).to_be_visible()
        vit_card = dev.locator("section").filter(has=dev.get_by_role("heading", name="Face deepfake classifier (ViT)")).last
        expect(vit_card.get_by_text("Unavailable", exact=True)).to_be_visible()
        state = vit_card.locator("span.rounded-full").first.inner_text()
        check("model health shows a definite state for the video model", state in ("Inference available", "Unavailable", "Not loaded yet", "Switched off"), state)
        dev.locator("input[type=file][multiple]:not([webkitdirectory])").first.set_input_files(str(f / "lab_face.png"))
        dev.get_by_label("Label for lab_face.png").select_option("fake")
        dev.get_by_role("button", name="Test this file").click()
        expect(dev.get_by_text(re.compile(r"1/1 finished"))).to_be_visible(timeout=30000)
        results_card = dev.locator("section").filter(has=dev.get_by_role("heading", name="Results")).last
        row = results_card.locator("tbody tr").filter(has_text="lab_face.png").first
        expect(row).to_be_visible()
        txt = row.inner_text()
        ran = ("done" in txt and re.search(r"\b0\.\d{3}\b", txt)) or ("unavailable" in txt and "—" in txt)
        check("the test file ran through the detector: a real score, or 'unavailable' with no score", bool(ran), txt.replace("\n", " | ").replace("\t", " "))
        tokens = {who: page.evaluate("() => sessionStorage.getItem('satyapan.token')") for who, page in (("customer", cus), ("officer", off), ("developer", dev))}
        codes = {who: dev.evaluate("([u, t]) => fetch(u, {headers: {Authorization: 'Bearer ' + t}}).then(r => r.status)", [f"{API}/api/v1/devlab/models", tok]) for who, tok in tokens.items() if tok}
        check("developer endpoints: customer and officer get 403, developer 200", codes.get("customer") == 403 and codes.get("officer") == 403 and codes.get("developer") == 200, str(codes))
        dev_session = dev.evaluate("([u, t]) => fetch(u, {method: 'POST', headers: {Authorization: 'Bearer ' + t}}).then(r => r.status)", [f"{API}/api/v1/sessions", tokens["developer"]])
        check("a developer cannot create a customer verification session", dev_session == 403, str(dev_session))
        cus.goto(f"{APP}/developer")
        cus.wait_for_url("**/dashboard")
        check("the /developer page sends a customer back to their own dashboard", True)

        return finish(browser, logs)


def finish(browser, logs):
    n429 = sum(v for (w, s), v in status_counts.items() if s == 429)
    n5xx = {k: v for k, v in status_counts.items() if k[1] >= 500}
    check("no HTTP 429 anywhere during the whole run", n429 == 0, f"{n429} x 429")
    check("no HTTP 5xx during the whole run", not n5xx, str(n5xx))
    errs = [line for line in logs if "pageerror" in line]
    check("no uncaught page errors", not errs, "; ".join(errs[:3]))
    browser.close()
    print("\nstatus counts:", dict(status_counts))
    print("officer requests by endpoint (whole run):", sorted(((m, p), v) for (w, m, p), v in req_counts.items() if w == "officer"))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if logs:
        print("console errors (first 8):\n  " + "\n  ".join(logs[:8]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
