from django.contrib import admin
from django.urls import path, include
from . import views   

urlpatterns = [    
    path('admin/', admin.site.urls),
    path('', views.home_view, name = 'home'),
    path('accounts/', include("accounts.urls")),
    path('resume/', include('resume.urls')),
    path('dashboard/', include("dashboard.urls")),
    path('questions/', include("questions.urls")),
]
