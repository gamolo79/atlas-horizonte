from django.urls import path

from .views import (
    AtlasInstitucionesListView,
    AtlasPersonasListView,
    atlas_home,
    index_apps,
    monitor_placeholder,
    privacy_notice,
    social_placeholder,
    terms_conditions,
)

urlpatterns = [
    path("", index_apps, name="index-apps"),
    path("aviso-privacidad/", privacy_notice, name="privacy-notice"),
    path("terminos-condiciones/", terms_conditions, name="terms-conditions"),
    path("apps/atlas/", atlas_home, name="atlas-home"),
    path("apps/atlas/personas/", AtlasPersonasListView.as_view(), name="atlas-personas-list"),
    path(
        "apps/atlas/instituciones/",
        AtlasInstitucionesListView.as_view(),
        name="atlas-instituciones-list",
    ),
    path("apps/monitor/", monitor_placeholder, name="monitor-home"),
    path("apps/social/", social_placeholder, name="social-home"),
]
