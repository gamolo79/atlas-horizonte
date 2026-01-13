import logging
import subprocess

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.templatetags.static import static
from django.views.decorators.csrf import ensure_csrf_cookie

logger = logging.getLogger(__name__)

from .forms import (
    SynthesisClientForm,
    SynthesisClientInterestForm,
    SynthesisRunForm,
    SynthesisScheduleForm,
    SynthesisSectionTemplateForm,
)
from redpolitica.models import Institucion, Persona, Topic

from .models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisRun,
    SynthesisRunSection,
    SynthesisSchedule,
    SynthesisSectionTemplate,
    SynthesisStory,
)
from .run_builder import ensure_run_pdf, resolve_date_range




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
    editing_section = None
    section_form = SynthesisSectionTemplateForm(
        prefix="section",
        persona_queryset=Persona.objects.all(),
        institucion_queryset=Institucion.objects.all(),
        topic_queryset=Topic.objects.all(),
    )

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
        elif "add_section" in request.POST:
            section_form = SynthesisSectionTemplateForm(
                request.POST,
                prefix="section",
                persona_queryset=Persona.objects.all(),
                institucion_queryset=Institucion.objects.all(),
                topic_queryset=Topic.objects.all(),
            )
            if section_form.is_valid():
                section = section_form.save(commit=False)
                section.client = client
                section.save()
                section_form.save_filters(section)
                messages.success(request, "Sección agregada.")
                return redirect("sintesis:client_detail", client_id=client.id)
        elif "update_section" in request.POST:
            section_id = request.POST.get("section_id")
            editing_section = get_object_or_404(
                SynthesisSectionTemplate,
                pk=section_id,
                client=client,
            )
            section_form = SynthesisSectionTemplateForm(
                request.POST,
                instance=editing_section,
                prefix="section",
                persona_queryset=Persona.objects.all(),
                institucion_queryset=Institucion.objects.all(),
                topic_queryset=Topic.objects.all(),
            )
            if section_form.is_valid():
                section = section_form.save(commit=False)
                section.client = client
                section.save()
                section_form.save_filters(section)
                messages.success(request, "Sección actualizada.")
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
                date_from, date_to = resolve_date_range(
                    data.get("date_from"),
                    data.get("date_to"),
                )
                run = SynthesisRun.objects.create(
                    client=data["client"],
                    date_from=date_from,
                    date_to=date_to,
                    run_type="manual",
                    status="queued",
                )
                subprocess.Popen(  # noqa: S603
                    [
                        "/srv/atlas/venv/bin/python",
                        "manage.py",
                        "run_sintesis",
                        "--run-id",
                        str(run.id),
                    ],
                    cwd="/srv/atlas",
                    close_fds=True,
                )
                messages.success(request, "Síntesis en cola.")
                return redirect("sintesis:client_detail", client_id=client.id)
    else:
        section_id = request.GET.get("edit_section")
        if section_id:
            editing_section = get_object_or_404(
                SynthesisSectionTemplate,
                pk=section_id,
                client=client,
            )
            filters = editing_section.filters.all()
            section_form = SynthesisSectionTemplateForm(
                prefix="section",
                instance=editing_section,
                initial={
                    "personas": [item.persona_id for item in filters if item.persona_id],
                    "instituciones": [
                        item.institucion_id for item in filters if item.institucion_id
                    ],
                    "topics": [item.topic_id for item in filters if item.topic_id],
                },
                persona_queryset=Persona.objects.all(),
                institucion_queryset=Institucion.objects.all(),
                topic_queryset=Topic.objects.all(),
            )

    client_form = SynthesisClientForm(instance=client, prefix="client")
    interests = (
        SynthesisClientInterest.objects.filter(client=client)
        .select_related("persona", "institucion", "topic")
        .order_by("-created_at")
    )
    priority_interests = interests.filter(interest_group="priority")
    general_interests = interests.filter(interest_group="general")
    schedules = SynthesisSchedule.objects.filter(client=client).order_by("-run_at")
    runs = SynthesisRun.objects.filter(client=client).order_by("-started_at")[:6]
    stories = (
        SynthesisStory.objects.filter(client=client)
        .prefetch_related("story_articles")
        .order_by("-created_at")[:6]
    )
    sections = (
        SynthesisSectionTemplate.objects.filter(client=client)
        .prefetch_related("filters")
        .order_by("order", "id")
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
            "priority_interests": priority_interests,
            "general_interests": general_interests,
            "schedules": schedules,
            "runs": runs,
            "stories": stories,
            "sections": sections,
            "section_form": section_form,
            "editing_section": editing_section,
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
                date_from, date_to = resolve_date_range(
                    data.get("date_from"),
                    data.get("date_to"),
                )
                run = SynthesisRun.objects.create(
                    client=data["client"],
                    date_from=date_from,
                    date_to=date_to,
                    run_type="manual",
                    status="queued",
                )
                subprocess.Popen(  # noqa: S603
                    [
                        "/srv/atlas/venv/bin/python",
                        "manage.py",
                        "run_sintesis",
                        "--run-id",
                        str(run.id),
                    ],
                    cwd="/srv/atlas",
                    close_fds=True,
                )
                messages.success(request, "Síntesis en cola.")
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
    return run_detail(request, run_id)


@ensure_csrf_cookie
def run_detail(request, run_id):
    run = get_object_or_404(SynthesisRun, pk=run_id)
    ordered_stories = SynthesisStory.objects.order_by(
        "group_label",
        "-created_at",
        "id",
    ).prefetch_related("story_articles")
    sections = (
        SynthesisRunSection.objects.filter(run=run)
        .prefetch_related(Prefetch("stories", queryset=ordered_stories))
        .order_by("order", "id")
    )
    date_str = timezone.localtime(run.started_at).strftime("%d/%m/%Y - %H:%M")
    return render(
        request,
        "sintesis/run_detail.html",
        {
            "run": run,
            "sections": sections,
            "date_str": date_str,
            "sources": run.stats_json.get("sources", []),
            "logo_href": static("img/logo-Horizonte-sintesis-dark.png"),
            "active_tab": "procesos",
        },
    )


@ensure_csrf_cookie
def run_pdf(request, run_id):
    run = get_object_or_404(SynthesisRun, pk=run_id)
    
    # Check if PDF generation is enabled
    if not settings.SINTESIS_ENABLE_PDF:
        logger.warning("PDF generation requested but SINTESIS_ENABLE_PDF is disabled")
        raise Http404("La generación de PDF está deshabilitada. Configure SINTESIS_ENABLE_PDF=true en el archivo .env")
    
    # Check if run has any stories
    if not run.output_count:
        logger.warning(f"PDF requested for run {run_id} but it has no stories")
        raise Http404("Este reporte no tiene historias para generar PDF.")
    
    pdf_file = ensure_run_pdf(run)
    if not pdf_file:
        logger.error(f"Failed to generate PDF for run {run_id}")
        raise Http404("Error al generar el PDF. Verifique que WeasyPrint esté instalado.")
    
    return FileResponse(pdf_file.open("rb"), as_attachment=True, filename=pdf_file.name)


@ensure_csrf_cookie
def run_status(request, run_id):
    run = get_object_or_404(SynthesisRun, pk=run_id)
    return JsonResponse(
        {
            "id": run.id,
            "status": run.status,
            "output_count": run.output_count,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error_message": run.error_message,
        }
    )


@ensure_csrf_cookie
def delete_interest(request, interest_id):
    interest = get_object_or_404(SynthesisClientInterest, pk=interest_id)
    client_id = interest.client_id
    if request.method == "POST":
        interest.delete()
        messages.success(request, "Interés eliminado.")
    return redirect("sintesis:client_detail", client_id=client_id)


@ensure_csrf_cookie
def delete_section(request, section_id):
    section = get_object_or_404(SynthesisSectionTemplate, pk=section_id)
    client_id = section.client_id
    if request.method == "POST":
        section.delete()
        messages.success(request, "Sección eliminada.")
    return redirect("sintesis:client_detail", client_id=client_id)
