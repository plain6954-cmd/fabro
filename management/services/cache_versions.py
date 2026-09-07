from django.core.cache import cache


VERSION_KEY = 'fabro:cache-version'


def cache_version():
    return cache.get_or_set(VERSION_KEY, 1, timeout=None)


def bump_cache_version():
    try:
        return cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, timeout=None)
        return 2
