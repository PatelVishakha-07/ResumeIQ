from django.shortcuts import render

def home_view(request):
    return render(request, "home.html")

def login_view(request):
    return render(request, 'authentication/login.html')

def register_view(request):
    return render(request, 'authentication/register.html')