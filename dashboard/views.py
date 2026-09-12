from django.shortcuts import redirect, render,get_object_or_404
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




# Admin URL
def adminOverview(request):
    return render(request,"dashboard_view/admin/overview.html",
                  {
                      'nav':{
                          'role':'admin'
                      }
                  })
def manageUsers(request):
    users = User.objects.filter(role = 'user').order_by('-created_at')
    return render(request,"dashboard_view/admin/manageUser.html",
        {
            'users':users,
            'nav': {
                'role': 'admin'
            }
        })

def toggleUserStatus(request, user_id):
    user = get_object_or_404(User, user_id=user_id)

    user.status = not user.status
    user.save()

    return redirect('manageUser')


def manageStaffRole(request):
    return render(request,"dashboard_view/admin/staff_roles.html",
        {
            'nav': {
                'role': 'admin'
            }
        })
def feedback(request):
    return render(request,"dashboard_view/admin/feedback.html",
        {
            'nav': {
                'role': 'admin'
            }
        })

