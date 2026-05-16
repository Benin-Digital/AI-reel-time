from app.services import rate_limit


def test_rate_limit_memory_fallback(monkeypatch):
    rate_limit._memory_limits.clear()

    def _boom():
        raise RuntimeError("no redis")

    monkeypatch.setattr(rate_limit, "_get_client", _boom)

    assert rate_limit.check_rate_limit("id", 2, 60) is True
    assert rate_limit.check_rate_limit("id", 2, 60) is True
    assert rate_limit.check_rate_limit("id", 2, 60) is False
