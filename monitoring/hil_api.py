from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .api import ResearchAPI
from .hil_models import HILReference
from .models import ExperimentRun
from .serializers import ValidatedModelSerializer


class HILReferenceSerializer(ValidatedModelSerializer):
    class Meta:
        model = HILReference
        exclude = ("run",)
        read_only_fields = ("id", "created_at")
        validators = []

    def validate(self, data):
        if (
            data.get("software_reference") is None
            and data.get("software_integer_code") is None
        ):
            raise serializers.ValidationError(
                "Supply software_reference or software_integer_code."
            )
        return data


class HILReferenceAPI(ResearchAPI):
    def post(self, request, run_id):
        payloads = request.data if isinstance(request.data, list) else [request.data]
        if not 1 <= len(payloads) <= 5000:
            raise ValidationError("Provide 1–5000 sequence-keyed references.")
        serializer = HILReferenceSerializer(data=payloads, many=True)
        serializer.is_valid(raise_exception=True)
        keys = [
            (row["sensor"], row["sequence_number"]) for row in serializer.validated_data
        ]
        if len(set(keys)) != len(keys):
            raise ValidationError("Duplicate sensor/sequence reference in batch.")
        try:
            with transaction.atomic():
                run = get_object_or_404(
                    ExperimentRun.objects.select_for_update(), pk=run_id
                )
                if run.status == "LOCKED":
                    raise ValidationError(
                        "Run is LOCKED; references cannot be changed."
                    )
                if run.source not in ("HIL", "SIMULATED", "SYNTHETIC"):
                    raise ValidationError(
                        "Sequence software references require HIL, SYNTHETIC or SIMULATED source."
                    )
                refs = HILReference.objects.bulk_create(
                    [HILReference(run=run, **row) for row in serializer.validated_data],
                    batch_size=500,
                )
                from .models import invalidate_run_summary

                invalidate_run_summary(run.pk)
        except IntegrityError:
            raise ValidationError(
                "A reference already exists for this sensor/sequence. No records imported."
            )
        return Response({"created": len(refs)}, status=201)

    def get(self, request, run_id):
        from .api import integer

        get_object_or_404(ExperimentRun, pk=run_id)
        page, limit = integer(request, "page", 1, 1000000), integer(
            request, "limit", 500, 5000
        )
        qs = HILReference.objects.filter(run_id=run_id).order_by(
            "sensor", "sequence_number"
        )
        return Response(
            {
                "count": qs.count(),
                "results": HILReferenceSerializer(
                    qs[(page - 1) * limit : page * limit], many=True
                ).data,
            }
        )
