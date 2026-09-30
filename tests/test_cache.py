from unlock_bot.ad.backend import cache


def test_cache_reuses_value_for_same_key():
    calls = 0

    @cache()
    def cached(username):
        nonlocal calls
        calls += 1
        return f"{username} data"

    assert cached("username") == "username data"
    assert cached("username") == "username data"
    assert calls == 1
