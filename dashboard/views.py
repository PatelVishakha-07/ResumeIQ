from django.shortcuts import redirect, render
from accounts.models import User


def dashboard_redirect(request):
    """
    Sends the user to the right section based on the role stored in
    their session at login.
    """
    user_id = request.session.get("user_id")

    if not user_id:
        return redirect("login")

    user = User.objects.get(user_id = user_id)

    role = request.session.get("role")
    nav = {
        'role': role,
        'avatar_initial': user.name[0].upper() if user.name else "",
        'avatar_name': user.name
    }

    if role == "admin":        
        return render(request, "dashboard_view/admin/overview.html", {'nav':nav})
        
    return render(request, "dashboard_view/user/overview.html", {'nav':nav})


