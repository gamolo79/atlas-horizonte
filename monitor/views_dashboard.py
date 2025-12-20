from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.shortcuts import get_object_or_404, redirect, render

from .forms_dashboard import OpsForm

# Import de modelos: intenta con los nombres más probables.
# Si esto falla en el paso 5, ajustamos nombres.
from .models import DigestClient


@staff_member_required
def dashboard_home(request):
    return render(request, "monitor/dashboard/home.html", {})


@staff_member_required
def client_list(request):
    clients = DigestClient.objects.all().order_by("id")
    return render(request, "monitor/dashboard/client_list.html", {"clients": clients})


@staff_member_required
def client_create(request):
    # MVP: por ahora solo muestra pantalla (sin formulario real)
    messages.info(request, "client_create: pendiente de integrar formulario/modelo.")
    return redirect("monitor_dashboard_client_list")


@staff_member_required
def client_edit(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    return render(request, "monitor/dashboard/client_form.html", {"client": client})


@staff_member_required
def client_generate_digest(request, client_id: int):
    # MVP: comando existente en tu repo (lo vimos en management/commands)
    try:
        call_command("generate_client_digest", "--client-id", str(client_id))
        messages.success(request, "Digest generado.")
    except Exception as e:
        messages.error(request, f"Error generando digest: {e}")
    return redirect("monitor_dashboard_client_edit", client_id=client_id)

@staff_member_required
def digest_view(request, digest_id: int):
    return render(request, "monitor/dashboard/digest_view.html", {"digest": f"Digest ID: {digest_id}"})

@staff_member_required
def ops_run(request):
    if request.method == "POST":
        form = OpsForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data.get("action")
            messages.info(
                request,
                "[DEBUG] action recibida = %s" % action
            )
            limit = int(form.cleaned_data.get("limit") or 200)

            try:
                if action == "fetch_sources":
                    call_command("fetch_sources", "--limit", str(limit))
                    messages.success(request, "fetch_sources OK")

                elif action == "fetch_article_bodies":
                    call_command("fetch_article_bodies", "--limit", str(limit))
                    messages.success(request, "fetch_article_bodies OK")

                elif action == "embed_articles":
                    call_command("embed_articles")
                    messages.success(request, "embed_articles OK")

                elif action == "cluster_articles_ai":
                    call_command("cluster_articles_ai")
                    messages.success(request, "cluster_articles_ai OK")

                else:
                    messages.error(request, f"Acción no reconocida: {action}")

            except Exception as e:
                messages.error(request, f"Error: {e}")

            return redirect("monitor_dashboard_ops")
    else:
        form = OpsForm()

    return render(request, "monitor/dashboard/ops.html", {"form": form})
