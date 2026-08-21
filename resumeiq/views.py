from django.shortcuts import render

def login_view(request):
    return render(request, 'authentication/login.html')

def register_view(request):
    return render(request, 'authentication/register.html')