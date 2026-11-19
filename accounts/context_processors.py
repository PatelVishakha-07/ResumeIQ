from .models import Profile


def current_user_avatar(request):
    """Makes `avatar_image_url` available in every template."""
    session = getattr(request, "session", None)
    user_id = session.get("user_id") if session else None
    if not user_id:
        return {}

    profile = Profile.objects.filter(user_id=user_id).first()
    if profile and profile.profile_image:
        return {"avatar_image_url": profile.get_image_url()}
    return {"avatar_image_url": None}