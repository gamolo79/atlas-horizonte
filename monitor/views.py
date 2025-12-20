from django.shortcuts import render

# Create your views here.

from django.http import HttpResponse

def monitor_health(request):
    return HttpResponse("Monitor OK")
