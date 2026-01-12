from django.contrib import messages
from django.core.management import call_command
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from .forms import (
    SynthesisClientForm,
    SynthesisClientInterestForm,
    SynthesisRunForm,
    SynthesisScheduleForm,
)
from .models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisRun,
    SynthesisSchedule,
    SynthesisStory,
)




@ensure_csrf_cookie
def home(request):
    clients = SynthesisClient.objects.filter(is_active=True)
    stories = (
        SynthesisStory.objects.select_related("client")
        .prefetch_related("story_articles")
        .order_by("-created_at")[:6]
    )
    return render(
        request,
        "sintesis/home.html",
        {"clients": clients, "stories": stories, "active_tab": "home"},
    )


@ensure_csrf_cookie
def clients(request):
    if request.method == "POST":
        form = SynthesisClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, "Cliente creado correctamente.")
            return redirect("sintesis:client_detail", client_id=client.id)
    else:
        form = SynthesisClientForm()

    clients_list = SynthesisClient.objects.order_by("name")
    return render(
        request,
        "sintesis/clients.html",
        {"clients": clients_list, "form": form, "active_tab": "clients"},
    )


@ensure_csrf_cookie
def client_detail(request, client_id):
    client = get_object_or_404(SynthesisClient, pk=client_id)
    interest_form = SynthesisClientInterestForm(prefix="interest")
    schedule_form = SynthesisScheduleForm(prefix="schedule", initial={"client": client})
    run_form = SynthesisRunForm(prefix="run", initial={"client": client})

    if request.method == "POST":
        if "save_client" in request.POST:
            client_form = SynthesisClientForm(request.POST, instance=client, prefix="client")
            if client_form.is_valid():
                client_form.save()
                messages.success(request, "Cliente actualizado.")
                return redirect("sintesis:client_detail", client_id=client.id)
        elif "add_interest" in request.POST:
            interest_form = SynthesisClientInterestForm(request.POST, prefix="interest")
            if interest_form.is_valid():
                interest = interest_form.save(commit=False)
                interest.client = client
                interest.save()
                messages.success(request, "Interés agregado.")
                return redirect("sintesis:client_detail", client_id=client.id)
        elif "add_schedule" in request.POST:
            schedule_form = SynthesisScheduleForm(request.POST, prefix="schedule")
            if schedule_form.is_valid():
                schedule = schedule_form.save(commit=False)
                if request.user.is_authenticated:
                    schedule.created_by = request.user
                schedule.save()
                messages.success(request, "Programación guardada.")
                return redirect("sintesis:client_detail", client_id=client.id)
        elif "run_manual" in request.POST:
            run_form = SynthesisRunForm(request.POST, prefix="run")
            if run_form.is_valid():
                data = run_form.cleaned_data
                call_command(
                    "run_sintesis",
                    client_id=data["client"].id,
                    date_from=data.get("date_from"),
                    date_to=data.get("date_to"),
                )
                messages.success(request, "Síntesis ejecutada.")
                return redirect("sintesis:client_detail", client_id=client.id)

    client_form = SynthesisClientForm(instance=client, prefix="client")
    interests = (
        SynthesisClientInterest.objects.filter(client=client)
        .select_related("persona", "institucion", "topic")
        .order_by("-created_at")
    )
    schedules = SynthesisSchedule.objects.filter(client=client).order_by("-run_at")
    runs = SynthesisRun.objects.filter(client=client).order_by("-started_at")[:6]
    stories = (
        SynthesisStory.objects.filter(client=client)
        .prefetch_related("story_articles")
        .order_by("-created_at")[:6]
    )

    return render(
        request,
        "sintesis/client_detail.html",
        {
            "client": client,
            "client_form": client_form,
            "interest_form": interest_form,
            "schedule_form": schedule_form,
            "run_form": run_form,
            "interests": interests,
            "schedules": schedules,
            "runs": runs,
            "stories": stories,
            "active_tab": "clients",
        },
    )


@ensure_csrf_cookie
def client_stories(request, client_id):
    client = get_object_or_404(SynthesisClient, pk=client_id)
    stories = (
        SynthesisStory.objects.filter(client=client)
        .prefetch_related(
            Prefetch("story_articles"),
        )
        .order_by("-created_at")
    )
    return render(
        request,
        "sintesis/client_stories.html",
        {"client": client, "stories": stories, "active_tab": "clients"},
    )


@ensure_csrf_cookie
def procesos(request):
    schedule_form = SynthesisScheduleForm(prefix="schedule")
    run_form = SynthesisRunForm(prefix="run")

    if request.method == "POST":
        if "add_schedule" in request.POST:
            schedule_form = SynthesisScheduleForm(request.POST, prefix="schedule")
            if schedule_form.is_valid():
                schedule = schedule_form.save(commit=False)
                if request.user.is_authenticated:
                    schedule.created_by = request.user
                schedule.save()
                messages.success(request, "Programación agregada.")
                return redirect("sintesis:procesos")
        elif "run_manual" in request.POST:
            run_form = SynthesisRunForm(request.POST, prefix="run")
            if run_form.is_valid():
                data = run_form.cleaned_data
                call_command(
                    "run_sintesis",
                    client_id=data["client"].id,
                    date_from=data.get("date_from"),
                    date_to=data.get("date_to"),
                )
                messages.success(request, "Síntesis ejecutada.")
                return redirect("sintesis:procesos")

    schedules = SynthesisSchedule.objects.select_related("client").order_by("-run_at")
    runs = SynthesisRun.objects.select_related("client").order_by("-started_at")[:20]

    return render(
        request,
        "sintesis/procesos.html",
        {
            "schedule_form": schedule_form,
            "run_form": run_form,
            "schedules": schedules,
            "runs": runs,
            "active_tab": "procesos",
        },
    )


@ensure_csrf_cookie
def run_report(request, run_id):
    run = get_object_or_404(SynthesisRun, pk=run_id)
    stories = (
        SynthesisStory.objects.filter(run=run)
        .prefetch_related("story_articles")
        .order_by("-created_at")
    )
    
    date_str = timezone.localtime(run.started_at).strftime("%d de %B de %Y")
    
    return render(
        request,
        "sintesis/sintesis_pdf.html",
        {
            "client": run.client,
            "stories": stories,
            "date_str": date_str,
        },
    )
