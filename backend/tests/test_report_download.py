from tests.conftest import pass_challenge, running_session


def _finished(client):
    sid = running_session(client)
    pass_challenge(client, sid)
    assert client.post(f"/api/v1/sessions/{sid}/complete").status_code == 200
    return sid


def test_officer_downloads_pdf_html_json_with_plain_language_ending(client):
    sid = _finished(client)
    for fmt, ctype in (("pdf", "application/pdf"), ("html", "text/html"), ("json", "application/json")):
        r = client.officer._c.get(f"/api/v1/sessions/{sid}/report/download?format={fmt}")
        assert r.status_code == 200 and r["Content-Type"].startswith(ctype)
        assert "attachment" in r["Content-Disposition"] and sid[:8] in r["Content-Disposition"]
    body = client.officer._c.get(f"/api/v1/sessions/{sid}/report/download?format=json").json()
    assert body["plain_language"]["colour_legend"] and body["plain_language"]["overall"]
    assert list(body.keys()).index("plain_language") > list(body.keys()).index("limitations")  # the plain explanation is the last section
    assert client.officer._c.get(f"/api/v1/sessions/{sid}/report/download?format=exe").status_code == 400


def test_customer_cannot_download_the_report(client):
    sid = _finished(client)
    assert client.get(f"/api/v1/sessions/{sid}/report/download?format=pdf").status_code == 403
