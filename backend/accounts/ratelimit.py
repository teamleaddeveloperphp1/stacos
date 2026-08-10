from django.core.cache import cache


def increment_counter(key, period_seconds):
    """Bump-and-return a plain counter with no cap -- used where the caller
    decides what to do with the count (e.g. §6.1's "show a captcha after 3
    failed logins" is a UI decision, not a hard block, unlike
    `check_and_increment`'s pass/fail limits)."""
    if cache.add(key, 1, timeout=period_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=period_seconds)
        return 1


def get_counter(key):
    return cache.get(key, 0)


def reset_counter(key):
    cache.delete(key)


def check_and_increment(key, limit, period_seconds):
    """§11 rate limits (signup 10/hour/IP, security answers 5/hour/account,
    captcha regen 20/hour/IP, ...). Cache-backed counter -- correct for a
    single-process dev/test deployment; a multi-worker production deploy
    would want a shared cache backend (e.g. Redis) rather than LocMemCache,
    but the counting logic itself doesn't change.

    Returns True (and counts this call) if still under `limit` within the
    current `period_seconds` window, False if the caller should be blocked.
    """
    if cache.add(key, 1, timeout=period_seconds):
        return True
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=period_seconds)
        count = 1
    return count <= limit
