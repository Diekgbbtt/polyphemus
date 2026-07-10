import json


def test_notify_posts_content_with_viewer_url():
    from agent.recon import notify
    sent = {}

    class _Resp:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["body"] = json.loads(req.data.decode())
        return _Resp()

    ok = notify.notify_awaiting_auth(
        "run-1", 4, "steel_crawl", "https://app.steel.dev/sessions/abc",
        webhook_url="https://example.test/hook", urlopen=fake_urlopen,
    )
    assert ok is True
    assert sent["url"] == "https://example.test/hook"
    assert "login" in sent["body"]["content"].lower()
    assert "https://app.steel.dev/sessions/abc" in sent["body"]["content"]


def test_notify_noop_when_unconfigured():
    from agent.recon import notify
    called = []
    ok = notify.notify_awaiting_auth(
        "run-1", 4, "steel_crawl", "https://v", webhook_url="",
        urlopen=lambda *a, **k: called.append(1),
    )
    assert ok is False
    assert called == []


def test_notify_swallows_post_errors():
    from agent.recon import notify

    def boom(req, timeout=None):
        raise OSError("network down")

    ok = notify.notify_awaiting_auth(
        "run-1", 4, "steel_crawl", "https://v",
        webhook_url="https://example.test/hook", urlopen=boom,
    )
    assert ok is False  # swallowed, no raise
