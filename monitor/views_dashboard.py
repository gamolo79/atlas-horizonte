from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms_dashboard import DigestClientConfigForm, DigestClientForm, OpsForm

# Import de modelos: intenta con los nombres más probables.
# Si esto falla en el paso 5, ajustamos nombres.
from .models import Digest, DigestClient, DigestClientConfig


@staff_member_required
def dashboard_home(request):
    recent_digests = Digest.objects.all()[:10]
    return render(
        request,
        "monitor/dashboard/home.html",
        {"recent_digests": recent_digests},
    )


@staff_member_required
def client_list(request):
    clients = DigestClient.objects.all().order_by("id")
    client_rows = []
    for client in clients:
        config = getattr(client, "config", None)
        last_digest = None
        if config and config.title:
            last_digest = Digest.objects.filter(title=config.title).order_by("-date", "-id").first()
        client_rows.append(
            {
                "client": client,
                "config": config,
                "last_digest": last_digest,
            }
        )
    return render(
        request,
        "monitor/dashboard/client_list.html",
        {"clients": clients, "client_rows": client_rows},
    )


@staff_member_required
def client_create(request):
    if request.method == "POST":
        form_client = DigestClientForm(request.POST)
        form_cfg = DigestClientConfigForm(request.POST)
        if form_client.is_valid() and form_cfg.is_valid():
            with transaction.atomic():
                client = form_client.save()
                cfg = form_cfg.save(commit=False)
                cfg.client = client
                cfg.save()
                form_cfg.save_m2m()
            messages.success(request, "Cliente creado.")
            return redirect("monitor_dashboard_client_edit", client_id=client.id)
        messages.error(request, "Revisa los errores del formulario.")
    else:
        form_client = DigestClientForm()
        form_cfg = DigestClientConfigForm()

    return render(
        request,
        "monitor/dashboard/client_edit.html",
        {
            "client": None,
            "form_client": form_client,
            "form_cfg": form_cfg,
            "last_digest": None,
            "digests": [],
            "is_create": True,
        },
    )


@staff_member_required
def client_edit(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    config, _ = DigestClientConfig.objects.get_or_create(client=client)

    if request.method == "POST":
        form_client = DigestClientForm(request.POST, instance=client)
        form_cfg = DigestClientConfigForm(request.POST, instance=config)
        if form_client.is_valid() and form_cfg.is_valid():
            with transaction.atomic():
                form_client.save()
                form_cfg.save()
                form_cfg.save_m2m()
            messages.success(request, "Cliente actualizado.")
            return redirect("monitor_dashboard_client_edit", client_id=client.id)
        messages.error(request, "Revisa los errores del formulario.")
    else:
        form_client = DigestClientForm(instance=client)
        form_cfg = DigestClientConfigForm(instance=config)

    digests = []
    last_digest = None
    if config.title:
        digests = list(Digest.objects.filter(title=config.title).order_by("-date", "-id")[:10])
        last_digest = digests[0] if digests else None

    return render(
        request,
        "monitor/dashboard/client_edit.html",
        {
            "client": client,
            "form_client": form_client,
            "form_cfg": form_cfg,
            "last_digest": last_digest,
            "digests": digests,
            "is_create": False,
        },
    )


@staff_member_required
def client_generate_digest(request, client_id: int):
    # Usa configuración del cliente para ejecutar generate_client_digest.
    try:
        client = get_object_or_404(DigestClient, id=client_id)
        config = getattr(client, "config", None)
        if not config:
            messages.error(request, "El cliente no tiene configuración de digest.")
            return redirect("monitor_dashboard_client_edit", client_id=client_id)

        person_ids = list(config.personas.values_list("id", flat=True))
        institution_ids = list(config.instituciones.values_list("id", flat=True))

        if not person_ids and not institution_ids:
            messages.warning(request, "Config vacía: selecciona personas o instituciones.")
            return redirect("monitor_dashboard_client_edit", client_id=client_id)

        cmd_args = {
            "title": config.title,
            "top": config.top_n,
            "hours": config.hours,
            "person_id": person_ids,
            "institution_id": institution_ids,
        }
        call_command("generate_client_digest", **cmd_args)
        messages.success(request, "Digest generado.")
    except Exception as e:
        messages.error(request, f"Error generando digest: {e}")
    return redirect("monitor_dashboard_client_edit", client_id=client_id)

@staff_member_required
def digest_view(request, digest_id: int):
    digest = get_object_or_404(Digest, id=digest_id)
    return render(request, "monitor/dashboard/digest_view.html", {"digest": digest})

@staff_member_required
def ops_run(request):
    if request.method == "POST":
        form = OpsForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data.get("action")
            limit = int(form.cleaned_data.get("limit") or 200)
            source_id = form.cleaned_data.get("source_id")
            force = form.cleaned_data.get("force")
            hours = int(form.cleaned_data.get("hours") or 72)
            threshold = form.cleaned_data.get("threshold")
            dry_run = form.cleaned_data.get("dry_run")

            try:
                if action == "fetch_sources":
                    call_kwargs = {"limit": limit}
                    if source_id:
                        call_kwargs["source_id"] = source_id
                    call_command("fetch_sources", **call_kwargs)
                    messages.success(request, "fetch_sources OK")

                elif action == "fetch_article_bodies":
                    call_kwargs = {"limit": limit}
                    if force:
                        call_kwargs["force"] = True
                    call_command("fetch_article_bodies", **call_kwargs)
                    messages.success(request, "fetch_article_bodies OK")

                elif action == "embed_articles":
                    call_kwargs = {"limit": limit}
                    if force:
                        call_kwargs["force"] = True
                    call_command("embed_articles", **call_kwargs)
                    messages.success(request, "embed_articles OK")

                elif action == "cluster_articles_ai":
                    call_kwargs = {"limit": limit, "hours": hours}
                    if threshold is not None:
                        call_kwargs["threshold"] = threshold
                    if dry_run:
                        call_kwargs["dry_run"] = True
                    call_command("cluster_articles_ai", **call_kwargs)
                    messages.success(request, "cluster_articles_ai OK")

                elif action == "link_atlas_entities":
                    call_kwargs = {"limit": limit, "hours": hours}
                    call_command("link_atlas_entities", **call_kwargs)
                    messages.success(request, "link_atlas_entities OK")

                else:
                    messages.error(request, f"Acción no reconocida: {action}")

            except Exception as e:
                messages.error(request, f"Error: {e}")

            return redirect("monitor_dashboard_ops")
    else:
        form = OpsForm()

    return render(request, "monitor/dashboard/ops.html", {"form": form})
