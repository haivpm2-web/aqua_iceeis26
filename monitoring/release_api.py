"""Finalization actions and immutable research-package download."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .api import ResearchAPI
from .models import ExperimentRun
from .serializers import RunSerializer


class RunLockAPI(ResearchAPI):
    def post(self, request, run_id, action="lock"):
        from .locking import lock_run, unlock_run

        get_object_or_404(ExperimentRun, pk=run_id)
        user = request.user if request.user and request.user.is_authenticated else None
        if action == "unlock":
            if not user or not user.is_superuser:
                raise PermissionDenied(
                    "Only an authenticated superuser may explicitly unlock evidence."
                )
            if (
                not isinstance(request.data, dict)
                or not isinstance(request.data.get("reason"), str)
                or not request.data["reason"].strip()
            ):
                raise ValidationError("Provide a nonempty reason for unlocking.")
            run = unlock_run(run_id, user, request.data["reason"])
        else:
            run = lock_run(run_id, user=user)
        return Response(RunSerializer(run).data)


class ResearchPackageAPI(ResearchAPI):
    def respond(self, request, run_id, persist=False):
        from .research_package import (
            generate_package,
            PackageIntegrityError,
            PackageStateError,
        )

        run = get_object_or_404(ExperimentRun, pk=run_id)
        try:
            data = generate_package(run, persist=persist)
        except (PackageIntegrityError, PackageStateError) as exc:
            return Response({"detail": str(exc)}, status=409)
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = (
            f'attachment; filename="run_{run_id}_research_package.zip"'
        )
        import hashlib

        response["X-Research-Package-SHA256"] = hashlib.sha256(data).hexdigest()
        return response

    def get(self, request, run_id):
        return self.respond(request, run_id, persist=False)

    def post(self, request, run_id):
        return self.respond(request, run_id, persist=True)
