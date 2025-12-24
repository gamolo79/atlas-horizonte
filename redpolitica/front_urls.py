from django.urls import path

from .views import (
    AtlasInstitucionesListView,
    AtlasPersonasListView,
    atlas_home,
    atlas_topic_create,
    atlas_topic_detail,
    atlas_topic_edit,
    atlas_topic_graph_json,
    atlas_topic_link_institution,
    atlas_topic_link_person,
    atlas_topic_unlink_institution,
    atlas_topic_unlink_person,
    atlas_topics_list,
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
    path("apps/atlas/temas/", atlas_topics_list, name="atlas-topics-list"),
    path("apps/atlas/temas/nuevo/", atlas_topic_create, name="atlas-topic-create"),
    path("apps/atlas/temas/<slug:slug>/", atlas_topic_detail, name="atlas-topic-detail"),
    path(
        "apps/atlas/temas/<slug:slug>/editar/",
        atlas_topic_edit,
        name="atlas-topic-edit",
    ),
    path(
        "apps/atlas/temas/<slug:slug>/grafo.json",
        atlas_topic_graph_json,
        name="atlas-topic-graph-json",
    ),
    path(
        "apps/atlas/temas/<slug:slug>/vincular-institucion/",
        atlas_topic_link_institution,
        name="atlas-topic-link-institution",
    ),
    path(
        "apps/atlas/temas/<slug:slug>/vincular-persona/",
        atlas_topic_link_person,
        name="atlas-topic-link-person",
    ),
    path(
        "apps/atlas/temas/<slug:slug>/eliminar-vinculo-institucion/<int:link_id>/",
        atlas_topic_unlink_institution,
        name="atlas-topic-unlink-institution",
    ),
    path(
        "apps/atlas/temas/<slug:slug>/eliminar-vinculo-persona/<int:link_id>/",
        atlas_topic_unlink_person,
        name="atlas-topic-unlink-person",
    ),
    path("apps/monitor/", monitor_placeholder, name="monitor-home"),
    path("apps/social/", social_placeholder, name="social-home"),
]
