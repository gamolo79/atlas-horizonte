import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from redpolitica.models import Institucion, Persona, Topic
from sintesis.forms import (
    SynthesisClientForm,
    SynthesisRunForm,
    SynthesisScheduleForm,
    SynthesisSectionTemplateForm,
)
from django.db.models import Prefetch

from sintesis.models import (
    SynthesisClient,
    SynthesisRun,
    SynthesisRunSection,
    SynthesisSchedule,
    SynthesisSectionTemplate,
    SynthesisStory,
)
from sintesis.services.pipeline import generate_pdf as generate_pdf_service
from sintesis.tasks import generate_synthesis_run

logger = logging.getLogger(__name__)


@ensure_csrf_cookie
def home(request):
    clients = SynthesisClient.objects.filter(is_active=True).order_by("name")[:6]
    return render(
        request,
        "sintesis/home.html",
        {
            "clients": clients,
            "active_tab": "home",
        },
    )


@ensure_csrf_cookie
def clients(request):
    clients_list = SynthesisClient.objects.order_by("-is_active", "name")
    return render(
        request,
        "sintesis/clients.html",
        {"clients": clients_list, "active_tab": "clients"},
    )


@ensure_csrf_cookie
def client_detail(request, client_id):
    client = get_object_or_404(SynthesisClient, pk=client_id)
    sections = (
        SynthesisSectionTemplate.objects.filter(client=client)
        .prefetch_related("filters")
        .order_by("order", "id")
    )
    schedules = SynthesisSchedule.objects.filter(client=client).order_by("-next_run_at")
    runs = SynthesisRun.objects.filter(client=client).order_by("-started_at")[:6]
    return render(
        request,
        "sintesis/client_detail.html",
        {
            "client": client,
            "sections": sections,
            "schedules": schedules,
            "runs": runs,
            "active_tab": "clients",
        },
    )


@ensure_csrf_cookie
def client_form(request, client_id=None):
    client = None
    if client_id:
        client = get_object_or_404(SynthesisClient, pk=client_id)

    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"save_client", "create_client"}:
            form = SynthesisClientForm(request.POST, instance=client)
            if form.is_valid():
                saved = form.save()
                messages.success(request, "Cliente guardado correctamente.")
                return redirect("sintesis:client_edit", client_id=saved.id)
        elif action == "add_section" and client:
            section_form = SynthesisSectionTemplateForm(
                request.POST,
                persona_queryset=Persona.objects.all(),
                institucion_queryset=Institucion.objects.all(),
                topic_queryset=Topic.objects.all(),
            )
            if section_form.is_valid():
                section = section_form.save(commit=False)
                section.client = client
                section.save()
                section_form.save_filters(section)
                messages.success(request, "Sección guardada.")
                return redirect("sintesis:client_edit", client_id=client.id)
        elif action == "update_section" and client:
            section_id = request.POST.get("section_id")
            section = get_object_or_404(SynthesisSectionTemplate, pk=section_id, client=client)
            section_form = SynthesisSectionTemplateForm(
                request.POST,
                instance=section,
                persona_queryset=Persona.objects.all(),
                institucion_queryset=Institucion.objects.all(),
                topic_queryset=Topic.objects.all(),
            )
            if section_form.is_valid():
                section_form.save()
                messages.success(request, "Sección actualizada.")
                return redirect("sintesis:client_edit", client_id=client.id)
        elif action == "delete_section" and client:
            section_id = request.POST.get("section_id")
            section = get_object_or_404(SynthesisSectionTemplate, pk=section_id, client=client)
            section.delete()
            messages.success(request, "Sección eliminada.")
            return redirect("sintesis:client_edit", client_id=client.id)
        elif action == "add_schedule" and client:
            schedule_form = SynthesisScheduleForm(request.POST)
            if schedule_form.is_valid():
                schedule = schedule_form.save(commit=False)
                schedule.client = client
                schedule.next_run_at = timezone.now()
                schedule.save()
                messages.success(request, "Programación guardada.")
                return redirect("sintesis:client_edit", client_id=client.id)
        elif action == "update_schedule" and client:
            schedule_id = request.POST.get("schedule_id")
            schedule = get_object_or_404(SynthesisSchedule, pk=schedule_id, client=client)
            schedule_form = SynthesisScheduleForm(request.POST, instance=schedule)
            if schedule_form.is_valid():
                schedule = schedule_form.save(commit=False)
                if not schedule.next_run_at:
                    schedule.next_run_at = timezone.now()
                schedule.save()
                messages.success(request, "Programación actualizada.")
                return redirect("sintesis:client_edit", client_id=client.id)
        elif action == "delete_schedule" and client:
            schedule_id = request.POST.get("schedule_id")
            schedule = get_object_or_404(SynthesisSchedule, pk=schedule_id, client=client)
            schedule.delete()
            messages.success(request, "Programación eliminada.")
            return redirect("sintesis:client_edit", client_id=client.id)

    form = SynthesisClientForm(instance=client)
    section_form = SynthesisSectionTemplateForm(
        persona_queryset=Persona.objects.all(),
        institucion_queryset=Institucion.objects.all(),
        topic_queryset=Topic.objects.all(),
    )
    schedule_form = SynthesisScheduleForm(instance=None)
    sections = []
    schedules = []
    if client:
        schedule_form.fields["client"].initial = client
        schedule_form.fields["client"].widget.attrs.update({"hidden": "hidden"})
        sections = (
            SynthesisSectionTemplate.objects.filter(client=client)
            .prefetch_related("filters")
            .order_by("order", "id")
        )
        schedules = SynthesisSchedule.objects.filter(client=client).order_by("-next_run_at")

    return render(
        request,
        "sintesis/client_form.html",
        {
            "client": client,
            "form": form,
            "section_form": section_form,
            "schedule_form": schedule_form,
            "sections": sections,
            "schedules": schedules,
            "active_tab": "clients",
        },
    )


@ensure_csrf_cookie
def client_reports(request, client_id):
    client = get_object_or_404(SynthesisClient, pk=client_id)
    runs = SynthesisRun.objects.filter(client=client).order_by("-started_at")
    return render(
        request,
        "sintesis/client_reports.html",
        {"client": client, "runs": runs, "active_tab": "clients"},
    )


@ensure_csrf_cookie
def reports(request):
    client_id = request.GET.get("client")
    start = request.GET.get("start")
    end = request.GET.get("end")
    runs = SynthesisRun.objects.select_related("client").order_by("-started_at")
    if client_id:
        runs = runs.filter(client_id=client_id)
    if start:
        runs = runs.filter(started_at__date__gte=start)
    if end:
        runs = runs.filter(started_at__date__lte=end)

    clients_list = SynthesisClient.objects.order_by("name")
    return render(
        request,
        "sintesis/reports.html",
        {
            "runs": runs,
            "clients": clients_list,
            "active_tab": "reports",
        },
    )


@ensure_csrf_cookie
def report_detail(request, run_id):
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
    stats = run.stats_json or {}
    routing = stats.get("routing", {})
    dedupe = stats.get("dedupe", {})
    clusters = stats.get("clusters", {})
    metrics = stats.get("metrics", {})
    off_section = metrics.get("off_section_rate", {})
    dup_rate = metrics.get("dup_rate", {})
    cluster_purity = metrics.get("cluster_purity", {})

    def _metric(mapping, template_id, default=0):
        if template_id is None:
            return default
        return mapping.get(template_id, mapping.get(str(template_id), default))

    section_metrics = []
    for section in sections:
        template_id = section.template_id
        routing_data = _metric(routing, template_id, {})
        if not isinstance(routing_data, dict):
            routing_data = {}
        section_metrics.append(
            {
                "section_id": section.id,
                "title": section.title,
                "routing_total": routing_data.get("total", 0),
                "routing_included": routing_data.get("included", 0),
                "dedupe_count": _metric(dedupe, template_id, 0),
                "cluster_count": _metric(clusters, template_id, 0),
                "off_section_rate": _metric(off_section, template_id, 0),
                "dup_rate": _metric(dup_rate, template_id, 0),
                "cluster_purity": _metric(cluster_purity, template_id, 0),
            }
        )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_review":
            run.review_text = request.POST.get("review_text", "")
            run.save(update_fields=["review_text"])
            for section in sections:
                section.review_text = request.POST.get(f"section_review_{section.id}", "")
                section.save(update_fields=["review_text"])
            messages.success(request, "Revisión guardada.")
            return redirect("sintesis:report_detail", run_id=run.id)
        if action == "regenerate_section":
            template_id = request.POST.get("template_id")
            generate_synthesis_run.delay(
                regeneration_run_id=run.id,
                regeneration_template_id=int(template_id),
            )
            messages.success(request, "Regeneración en cola.")
            return redirect("sintesis:report_detail", run_id=run.id)
        if action == "send_email":
            if not getattr(settings, "SINTESIS_ENABLE_EMAIL_SHARE", False):
                messages.error(request, "El envío por correo está deshabilitado temporalmente.")
                return redirect("sintesis:report_detail", run_id=run.id)
            email_to = request.POST.get("email_to")
            if not email_to:
                messages.error(request, "Ingresa un correo válido.")
            else:
                try:
                    pdf_file = run.pdf_file if run.pdf_file else None
                    email = EmailMessage(
                        subject=f"Reporte Síntesis #{run.id}",
                        body="Adjuntamos el reporte de Síntesis.",
                        to=[email_to],
                    )
                    if pdf_file:
                        pdf_file.open("rb")
                        email.attach(pdf_file.name, pdf_file.read(), "application/pdf")
                        pdf_file.close()
                    email.send()
                    messages.success(request, "Correo enviado.")
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error al enviar correo")
                    messages.error(request, f"No se pudo enviar el correo: {exc}")
            return redirect("sintesis:report_detail", run_id=run.id)

    date_str = timezone.localtime(run.started_at).strftime("%d/%m/%Y - %H:%M")
    return render(
        request,
        "sintesis/report_detail.html",
        {
            "run": run,
            "sections": sections,
            "date_str": date_str,
            "logo_href": static("img/horizonte-sintesis-dark.svg"),
            "share_url": request.build_absolute_uri(),
            "active_tab": "reports",
            "section_metrics": section_metrics,
        },
    )


@ensure_csrf_cookie
def manual_run(request, client_id):
    client = get_object_or_404(SynthesisClient, pk=client_id)
    if request.method != "POST":
        return redirect("sintesis:client_detail", client_id=client.id)

    form = SynthesisRunForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Formulario inválido: {form.errors}")
        return redirect("sintesis:client_detail", client_id=client.id)

    data = form.cleaned_data
    window_start = data.get("window_start")
    window_end = data.get("window_end")
    run = SynthesisRun.objects.create(
        client=client,
        run_type="manual",
        status="queued",
        window_start=window_start,
        window_end=window_end,
        date_from=window_start.date() if window_start else None,
        date_to=window_end.date() if window_end else None,
    )
    try:
        generate_synthesis_run.delay(run_id=run.id)
        messages.success(request, "Síntesis en cola.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("No se pudo encolar la síntesis")
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        messages.error(
            request,
            "No se pudo encolar la síntesis. Revisa Celery/Redis.",
        )
    return redirect("sintesis:client_detail", client_id=client.id)


@ensure_csrf_cookie
def procesos(request):
    runs = SynthesisRun.objects.select_related("client").order_by("-started_at")[:50]
    return render(
        request,
        "sintesis/procesos.html",
        {"runs": runs, "active_tab": "procesos"},
    )


@ensure_csrf_cookie
def run_pdf(request, run_id):
    run = get_object_or_404(SynthesisRun, pk=run_id)

    if not settings.SINTESIS_ENABLE_PDF or not getattr(settings, "SINTESIS_ENABLE_PDF_EXPORT", False):
        logger.warning("PDF export requested but it is disabled")
        raise Http404("La exportación de PDF está deshabilitada temporalmente.")

    if not run.output_count:
        logger.warning("PDF requested for run %s but it has no stories", run_id)
        raise Http404("Este reporte no tiene historias para generar PDF.")

    # Si no existe PDF, generarlo
    if not run.pdf_file:
        generate_pdf_service(run.id)
        # Recargar el objeto run desde la DB para obtener el archivo generado
        run.refresh_from_db()

    if not run.pdf_file:
        logger.error("Failed to generate PDF for run %s", run_id)
        raise Http404("Error al generar el PDF. Verifique que WeasyPrint esté instalado.")

    return FileResponse(run.pdf_file.open("rb"), as_attachment=True, filename=run.pdf_file.name)
