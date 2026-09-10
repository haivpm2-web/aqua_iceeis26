"""Root URL configuration."""

from django.contrib import admin
from monitoring.views import health_check
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("", include("monitoring.urls")),
]
