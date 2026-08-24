from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt

@xframe_options_exempt
def twa_dashboard_view(request):
    """Telegram Mini App (TWA) Dashboard sahifasi"""
    return render(request, "index.html")
