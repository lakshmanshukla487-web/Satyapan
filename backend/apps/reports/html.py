"""Self-contained HTML version of the officer report (no scripts, no external files). Every value is escaped."""
from html import escape as e

COLOURS = {"GREEN": "#1a7f37", "AMBER": "#b26b00", "RED": "#c62828", "GREY": "#5f6b7a"}


def _c(level) -> str:
    return COLOURS.get(str(level or "").upper(), "#5f6b7a")


def _table(head: list[str], rows: list[list]) -> str:
    th = "".join(f"<th>{e(str(h))}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{e(str(x)) if x is not None else '-'}</td>" for x in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def render_html(r: dict) -> str:
    o, s = r.get("outcome", {}), r.get("session", {})
    pl = r.get("plain_language") or {}
    lvl = o.get("risk_level", "")
    parts = [f"<h1>Satyapan verification report</h1><p class=m>Session {e(str(s.get('id', '')))} · generated {e(str(r.get('generated_at', '')))} · {e(str(r.get('snapshot', '')))}</p>",
             f"<div class=banner style='background:{_c(lvl)}'>{e(str(lvl))}<span>{e(str(o.get('headline', '')))}</span></div>",
             f"<p>{e(str(o.get('summary', '')))}</p><p class=m>Decision support only. A human officer decides. Rule: {e(str(o.get('rule_text', '')))}</p>",
             "<h2>Session</h2>" + _table(["Field", "Value"], [[k, v] for k, v in s.items()])]
    if r.get("families"):
        parts.append("<h2>Checks</h2>" + _table(["Check", "Colour", "Score", "Samples", "Positive"], [[f["label"], f["status"].upper(), f.get("score"), f.get("samples"), "yes" if f.get("positive") else ""] for f in r["families"]]))
    parts.append("<h2>Reasons</h2><ul>" + "".join(f"<li><b>{e(str(x.get('title', '')))}</b> ({e(str(x.get('severity', '')))}): {e(str(x.get('detail', '')))}</li>" for x in r.get("reasons", [])) + "</ul>")
    parts.append("<h2>Next steps</h2><ol>" + "".join(f"<li>{e(str(x))}</li>" for x in r.get("next_steps", [])) + "</ol>")
    if r.get("challenges"):
        parts.append("<h2>Challenges</h2>" + _table(["#", "Type", "Result", "Reason"], [[c["number"], c["type"], c["result"], c.get("reason")] for c in r["challenges"]]))
    if r.get("timeline"):
        parts.append("<h2>Timeline</h2>" + _table(["Time", "Event", "Detail"], [[t["time"], t["event"], t["detail"]] for t in r["timeline"]]))
    ei = r.get("evidence_integrity", {})
    parts.append(f"<h2>Evidence log</h2><p>{e(str(ei.get('events_checked')))} events checked; chain valid: {e(str(ei.get('chain_valid')))}. {e(str(ei.get('note', '')))}</p>")
    parts.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in r.get("limitations", [])) + "</ul>")
    if pl:
        parts.append("<h2>In plain words</h2>" + f"<p>{e(str(pl.get('overall', '')))}</p><h3>What the colours mean</h3>"
                     + "".join(f"<p><b style='color:{_c(x['colour'])}'>{e(x['colour'])}</b> - {e(x['meaning'])}</p>" for x in pl.get("colour_legend", []))
                     + "<h3>What each check found</h3>" + "".join(f"<p><b style='color:{_c(x['colour'])}'>{e(x['colour'])}</b> <b>{e(x['check'])}</b>: {e(x['in_plain_words'])}</p>" for x in pl.get("by_check", []))
                     + f"<h3>How this result was decided</h3><p>{e(str(pl.get('how_decided', '')))}</p><h3>What to do now</h3><ol>"
                     + "".join(f"<li>{e(str(x))}</li>" for x in pl.get("what_to_do", [])) + "</ol>")
    css = ("body{font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1b1f24}"
           "table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid #d0d7de;padding:5px 8px;text-align:left;font-size:13px;vertical-align:top}"
           "th{background:#f3f4f6}.m{color:#5f6b7a;font-size:13px}.banner{color:#fff;padding:14px 18px;border-radius:8px;font-size:22px;font-weight:700}"
           ".banner span{display:block;font-size:14px;font-weight:400;margin-top:4px}h2{margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}")
    return f"<!doctype html><html lang=en><head><meta charset=utf-8><title>Satyapan report</title><meta name=viewport content='width=device-width,initial-scale=1'><style>{css}</style></head><body>{''.join(parts)}</body></html>"
