"""Independent sequence-keyed software outputs for deterministic HIL matching."""

from django.db import models
from .models import LockProtectedModel, ExperimentRun, choices


class HILReference(LockProtectedModel):
    lock_relation = "run"
    run = models.ForeignKey(
        ExperimentRun, on_delete=models.CASCADE, related_name="hil_references"
    )
    sensor = models.CharField(max_length=20, choices=choices("do ph tds temperature"))
    sequence_number = models.PositiveBigIntegerField()
    software_reference = models.FloatField(null=True, blank=True)
    software_integer_code = models.BigIntegerField(null=True, blank=True)
    reference_source = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sensor", "sequence_number"],
                name="hil_reference_unique_sequence",
            )
        ]
        indexes = [models.Index(fields=["run", "sensor"])]
