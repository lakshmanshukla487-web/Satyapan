"""PDF version of the officer report (reportlab, pure Python). Ends with the plain-language explanation."""
import io
from xml.sax.saxutils import escape

COLOURS = {"GREEN": "#1a7f37", "AMBER": "#b26b00", "RED": "#c62828", "GREY": "#5f6b7a"}


def _t(v, n: int = 600) -> str:
    """Text safe for reportlab's built-in Latin-1 fonts and its XML-like paragraph markup."""
    s = "-" if v is None else str(v)
    s = s.replace("—", "-").replace("–", "-").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.encode("latin-1", "replace").decode("latin-1")
    return escape(s[:n])


def render_pdf(r: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#5f6b7a"))
    cell = ParagraphStyle("c", parent=body, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12.5, spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#1b1f24"))
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=10.5, spaceBefore=6, spaceAfter=2)
    W = A4[0] - 30 * mm

    def P(x, st=body):
        return Paragraph(_t(x), st)

    def table(head, rows, widths, colour_col=None):
        data = [[Paragraph(f"<b>{_t(h)}</b>", cell) for h in head]] + [[Paragraph(_t(c, 300), cell) for c in row] for row in rows]
        t = Table(data, colWidths=[w * W for w in widths], repeatRows=1)
        st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if colour_col is not None:
            for i, row in enumerate(rows, 1):
                c = COLOURS.get(str(row[colour_col]).upper())
                if c:
                    st.append(("BACKGROUND", (colour_col, i), (colour_col, i), colors.HexColor(c)))
                    st.append(("TEXTCOLOR", (colour_col, i), (colour_col, i), colors.white))
        t.setStyle(TableStyle(st))
        return t

    o, s = r.get("outcome", {}), r.get("session", {})
    pl = r.get("plain_language") or {}
    lvl = str(o.get("risk_level", "")).upper()
    el = [Paragraph("Satyapan verification report", h1),
          P(f"Session {s.get('id', '')} | generated {r.get('generated_at', '')} | {r.get('snapshot', '')} | report v{r.get('report_version', '')}", small), Spacer(1, 6)]
    banner = Table([[Paragraph(f'<font color="white" size="16"><b>{_t(lvl)}</b></font>', body),
                     Paragraph(f'<font color="white">{_t(o.get("headline", ""), 400)}</font>', body)]], colWidths=[0.2 * W, 0.8 * W])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLOURS.get(lvl, "#5f6b7a"))), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    el += [banner, Spacer(1, 6), P(o.get("summary", "")), P("Decision support only: a human officer makes the decision. " + str(o.get("rule_text", "")), small)]

    el += [Paragraph("Session", h2), table(["Field", "Value"], [[k, v] for k, v in s.items()], [0.3, 0.7])]
    if r.get("families"):
        el += [Paragraph("Checks (colour per evidence family)", h2),
               table(["Check", "Colour", "Score", "Samples", "Positive", "What it means"],
                     [[f["label"], str(f["status"]).upper(), f.get("score"), f.get("samples"), "yes" if f.get("positive") else "", f.get("explain", "")] for f in r["families"]],
                     [0.16, 0.09, 0.07, 0.1, 0.09, 0.49], colour_col=1)]
    el.append(Paragraph("Reasons", h2))
    for x in r.get("reasons", []):
        el.append(P(f"[{x.get('severity', '')}] {x.get('title', '')}: {x.get('detail', '')}"))
    el.append(Paragraph("Next steps", h2))
    for i, x in enumerate(r.get("next_steps", []), 1):
        el.append(P(f"{i}. {x}"))

    sa = r.get("session_analysis") or {}
    if sa:
        el.append(Paragraph("Session-length analysis", h2))
        el.append(P(f"Duration: {sa.get('duration_seconds')} s. Median challenge response time: {sa.get('median_response_ms')} ms. Challenge stats: {sa.get('challenge_stats')}"))
        if sa.get("coverage"):
            el.append(P(f"Media coverage: {sa['coverage']}", small))
    if r.get("challenges"):
        el += [Paragraph("Challenges", h2), table(["#", "Type", "Result", "Reason"], [[c["number"], c["type"], c["result"], c.get("reason")] for c in r["challenges"]], [0.05, 0.2, 0.15, 0.6])]
    idn = r.get("identity") or {}
    if idn:
        fm, rp = idn.get("face_match", {}), idn.get("reference_photo", {})
        el += [Paragraph("Identity", h2),
               P(f"Start photo uploaded: {rp.get('uploaded')}; iris usable in start photo: {rp.get('iris_usable')}. Face match samples: {fm.get('samples')}, "
                 f"median similarity {fm.get('median_similarity')}, minimum {fm.get('min_similarity')} (threshold {fm.get('threshold')}).")]
        for it in idn.get("iris_scans", []):
            el.append(P(f"Iris scan: verdict {it.get('verdict')}, distance {it.get('hamming_distance')}", small))
    nw = r.get("network") or {}
    if nw:
        el += [Paragraph("Network and camera", h2), P(f"IP addresses seen: {', '.join(str(i) for i in nw.get('ips_seen', [])) or 'none'}"),
               P(f"IP check: {nw.get('ip_check')}", small), P(f"Camera check: {nw.get('camera_check')}", small)]
    if r.get("detectors"):
        el += [Paragraph("Detectors", h2), table(["Detector", "Status", "Samples", "Median", "Highest", "Threshold"],
                                                 [[d["label"], d["status"], d["samples"], d["median_score"], d["highest_score"], d["threshold"]] for d in r["detectors"]], [0.3, 0.17, 0.1, 0.13, 0.13, 0.17])]
    if r.get("timeline"):
        el += [Paragraph("Timeline", h2), table(["Time", "Event", "Detail"], [[t["time"], t["event"], t["detail"]] for t in r["timeline"]], [0.25, 0.3, 0.45])]
    ei = r.get("evidence_integrity", {})
    el += [Paragraph("Evidence log", h2), P(f"{ei.get('events_checked')} events checked; hash chain valid: {ei.get('chain_valid')}. {ei.get('note', '')}"),
           P(f"Report SHA-256: {(r.get('integrity') or {}).get('report_sha256')}", small), Paragraph("Limitations", h2)]
    el += [P("- " + x, small) for x in r.get("limitations", [])]

    if pl:  # the last section: plain words
        el.append(Paragraph("In plain words (no technical knowledge needed)", h2))
        el.append(P(pl.get("overall", "")))
        el.append(Paragraph("What the colours mean", h3))
        for x in pl.get("colour_legend", []):
            el.append(Paragraph(f'<font color="{COLOURS.get(x["colour"], "#000000")}"><b>{_t(x["colour"])}</b></font> - {_t(x["meaning"])}', body))
        el.append(Paragraph("What each check found", h3))
        for x in pl.get("by_check", []):
            el.append(Paragraph(f'<font color="{COLOURS.get(x["colour"], "#000000")}"><b>{_t(x["colour"])}</b></font> <b>{_t(x["check"])}</b>: {_t(x["in_plain_words"])}', body))
        el.append(Paragraph("How this result was decided", h3))
        el.append(P(pl.get("how_decided", "")))
        el.append(KeepTogether([Paragraph("What to do now", h3)] + [P(f"{i}. {x}") for i, x in enumerate(pl.get("what_to_do", []), 1)]))

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5f6b7a"))
        canvas.drawString(15 * mm, 8 * mm, "Satyapan - decision support, not a final KYC decision")
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                      title="Satyapan verification report", author="Satyapan").build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
