from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from .models import ExperimentRun


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ok", "database": "ok"})
    except DatabaseError:
        return JsonResponse(
            {"status": "unavailable", "database": "unavailable"}, status=503
        )


def dashboard(request, page="dashboard", run_id=None):
    selected = get_object_or_404(ExperimentRun, pk=run_id) if run_id else None
    return render(
        request,
        "monitoring/dashboard.html",
        {
            "page": page,
            "selected": selected,
            "runs": ExperimentRun.objects.order_by("-created_at")[:500],
            "paper": page == "paper",
            "title": page.replace("_", " ").title(),
        },
    )
