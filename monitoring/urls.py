from django.urls import path

from . import views, api, hil_api, release_api

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
]
for page in (
    "runs",
    "live",
    "analysis",
    "compare",
    "fpga",
    "events",
    "paper",
    "system",
):
    urlpatterns.append(path(page + "/", views.dashboard, {"page": page}, name=page))
urlpatterns += [
    path("api/v1/runs/<int:run_id>/lock/", release_api.RunLockAPI.as_view()),
    path(
        "api/v1/runs/<int:run_id>/unlock/",
        release_api.RunLockAPI.as_view(),
        {"action": "unlock"},
    ),
    path(
        "api/v1/runs/<int:run_id>/research-package/",
        release_api.ResearchPackageAPI.as_view(),
    ),
    path("api/v1/runs/<int:run_id>/hil-references/", hil_api.HILReferenceAPI.as_view()),
    path("runs/<int:run_id>/", views.dashboard, {"page": "detail"}, name="run-detail"),
    path(
        "runs/<int:run_id>/paper/", views.dashboard, {"page": "paper"}, name="run-paper"
    ),
    path("api/v1/samples/", api.SamplesAPI.as_view()),
    path("api/v1/samples/batch/", api.SamplesAPI.as_view(), {"batch": True}),
    path("api/v1/history/", api.HistoryAPI.as_view()),
    path("api/v1/latest/", api.LatestAPI.as_view()),
    path("api/v1/runs/", api.RunsAPI.as_view()),
    path("api/v1/runs/<int:run_id>/", api.RunsAPI.as_view()),
    path("api/v1/runs/<int:run_id>/samples/", api.HistoryAPI.as_view()),
    path("api/v1/runs/<int:run_id>/stats/", api.SummaryAPI.as_view()),
    path("api/v1/runs/<int:run_id>/summary/", api.SummaryAPI.as_view()),
    path("api/v1/runs/<int:run_id>/export/", api.ExportAPI.as_view()),
    path("api/v1/runs/<int:run_id>/import/", api.ImportAPI.as_view()),
    path("api/v1/runs/<int:run_id>/tables/", api.TablesAPI.as_view()),
    path("api/v1/status/", api.StatusAPI.as_view()),
    path(
        "api/v1/implementations/", api.CatalogAPI.as_view(), {"kind": "implementations"}
    ),
    path("api/v1/events/", api.CatalogAPI.as_view(), {"kind": "events"}),
]
