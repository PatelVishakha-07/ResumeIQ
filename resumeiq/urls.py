from django.contrib import admin
from django.urls import path, include
from . import views
from dashboard.views import dashboard_redirect          

urlpatterns = [    
    path('admin/', admin.site.urls),
    path('', views.home_view, name = 'home'),
    path('accounts/', include("accounts.urls")),

    path('resume/', include('resume.urls')),

    path("dashboard/", dashboard_redirect, name ="dashboard"),
    path('dashboard/', include("dashboard.urls")),

]
