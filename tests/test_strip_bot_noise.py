from app.retrieval.summarize import strip_bot_noise


def test_strips_vercel_status_token():
    assert "[vc]" not in strip_bot_noise("hello [vc]:#abc123 world")


def test_strips_long_base64_blobs():
    blob = "A" * 90
    out = strip_bot_noise(f"before {blob} after")
    assert blob not in out
    assert "before" in out and "after" in out


def test_strips_html_comments():
    out = strip_bot_noise("keep <!-- hidden bot note --> keep")
    assert "hidden bot note" not in out
    assert "keep" in out


def test_collapses_excess_blank_lines():
    out = strip_bot_noise("a\n\n\n\n\nb")
    assert "\n\n\n" not in out


def test_empty_input():
    assert strip_bot_noise("") == ""
    assert strip_bot_noise(None) == ""
