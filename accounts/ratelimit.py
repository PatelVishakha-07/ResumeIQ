from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse


def _hit(key, limit, window):
    """Count one use of `key`. True once it goes over `limit` within `window` seconds."""
    if cache.add(key, 1, window):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, window)
        return False


def ai_rate_limit(bucket, user_limit=30, anon_limit=5, window=3600):
    """
    For JSON endpoints that call the AI or do heavy file parsing.
    Signed-in users are counted per account, visitors per IP address.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user_id = request.session.get("user_id")
            if user_id:
                key, limit = f"ai:{bucket}:user:{user_id}", user_limit
            else:
                ip = request.META.get("REMOTE_ADDR", "unknown")
                key, limit = f"ai:{bucket}:ip:{ip}", anon_limit

            if _hit(key, limit, window):
                return JsonResponse(
                    {"error": "You've reached the hourly limit for this feature. Please try again later."},
                    status=429,
                )
            return view(request, *args, **kwargs)
        return wrapper
    return decorator