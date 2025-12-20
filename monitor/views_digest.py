from datetime import date as date_cls

from django.http import HttpResponse, Http404
from monitor.models import Digest


def digest_latest(request):
    d = Digest.objects.order_by("-date", "-id").first()
    if not d:
        raise Http404("No hay digest todavía")
    return HttpResponse(d.html_content, content_type="text/html; charset=utf-8")


def digest_by_date(request, y, m, d):
    target = date_cls(int(y), int(m), int(d))
    d_obj = Digest.objects.filter(date=target).order_by("-id").first()
    if not d_obj:
        raise Http404("No hay digest para esa fecha")
    return HttpResponse(d_obj.html_content, content_type="text/html; charset=utf-8")
