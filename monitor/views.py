from django.shortcuts import render


def home(request):
    return render(request, "monitor/monitor-home.html")


def feed(request):
    return render(request, "monitor/monitor-feed.html")


def dashboards(request):
    return render(request, "monitor/dashboards.html")


def dashboards_export(request):
    return render(request, "monitor/dashboards-export.html")


def benchmarks(request):
    return render(request, "monitor/benchmarks.html")


def benchmarks_export(request):
    return render(request, "monitor/benchmarks-export.html")


def revision(request):
    return render(request, "monitor/revision.html")


def procesos(request):
    return render(request, "monitor/procesos.html")


def sources(request):
    return render(request, "monitor/fuentes.html")
