"""Experiment records preserve transmitted values; references are never inferred."""

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from .locking import LockProtectedModel


def choices(values):
    return [(v, v.replace("_", " ").title()) for v in values.split()]


def positive_frequency(value):
    if value <= 0:
        raise ValidationError("Frequency must be positive.")


class FPGAImplementation(LockProtectedModel):
    lock_relation = "implementation"
    name = models.CharField(max_length=160)
    report_source = models.CharField(max_length=250, blank=True)
    clock_mhz = models.FloatField(null=True, blank=True)
    max_clock_mhz = models.FloatField(null=True, blank=True)
    timing_slack_ns = models.FloatField(null=True, blank=True)
    power_w = models.FloatField(null=True, blank=True)
    for resource in ("lut", "ff", "dsp", "bram"):
        locals()[resource + "_used"] = models.FloatField(null=True, blank=True)
        locals()[resource + "_available"] = models.FloatField(null=True, blank=True)
    del resource

    def __str__(self):
        return self.name


class ExperimentRun(LockProtectedModel):
    lock_relation = "self"
    run_name = models.CharField(max_length=200)
    run_type = models.CharField(
        max_length=20,
        choices=choices(
            "SYNTHETIC STABLE INTERVENTION IMPULSE MIXED_NOISE HIL REAL_WORLD CALIBRATION OTHER"
        ),
        default="OTHER",
    )
    description = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=12,
        choices=choices("CREATED RUNNING COMPLETED LOCKED FAILED"),
        default="CREATED",
    )
    source = models.CharField(
        max_length=12, choices=choices("REAL SIMULATED HIL SYNTHETIC"), default="REAL"
    )
    sensor_configuration = models.JSONField(default=dict, blank=True)
    filter_version = models.CharField(max_length=160, blank=True)
    fpga_bitstream_version = models.CharField(max_length=160, blank=True)
    firmware_version = models.CharField(max_length=160, blank=True)
    sampling_rate_hz = models.FloatField(
        null=True, blank=True, validators=[positive_frequency]
    )
    for _field in (
        "input_q_format",
        "output_q_format",
        "accumulator_q_format",
        "coefficient_q_format",
        "rounding_mode",
        "saturation_mode",
    ):
        locals()[_field] = models.CharField(max_length=100, blank=True)
    fpga_clock_hz = models.FloatField(
        null=True, blank=True, validators=[positive_frequency]
    )
    for _field in (
        "alpha_stable",
        "alpha_normal",
        "alpha_noisy",
        "alpha_transient",
        "beta_noise",
    ):
        locals()[_field] = models.FloatField(
            null=True,
            blank=True,
            validators=[MinValueValidator(0), MaxValueValidator(1)],
        )
    for _field in ("threshold_base", "threshold_multiplier"):
        locals()[_field] = models.FloatField(
            null=True, blank=True, validators=[MinValueValidator(0)]
        )
    for _field in ("median_window", "persistence_samples"):
        locals()[_field] = models.PositiveIntegerField(
            null=True, blank=True, validators=[MinValueValidator(1)]
        )
    for _field in (
        "software_git_commit",
        "fpga_git_commit",
        "stm32_git_commit",
        "gateway_git_commit",
    ):
        locals()[_field] = models.CharField(max_length=64, blank=True)
    del _field
    sensor_model = models.CharField(max_length=250, blank=True)
    calibration_date = models.DateField(null=True, blank=True)
    calibration_method = models.TextField(blank=True)
    calibration_coefficients = models.JSONField(default=dict, blank=True)
    reference_instrument = models.CharField(max_length=250, blank=True)
    experiment_notes = models.TextField(blank=True)
    locked_at = models.DateTimeField(null=True, blank=True, editable=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="locked_experiments",
    )
    dataset_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    research_package_sha256 = models.CharField(
        max_length=64, blank=True, editable=False
    )
    integrity_generated_at = models.DateTimeField(null=True, blank=True, editable=False)
    notes = models.TextField(blank=True)
    implementation = models.ForeignKey(
        FPGAImplementation, null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self):
        return self.run_name

    def clean(self):
        super().clean()
        if self.pk and self.samples.exists():
            original = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("source", flat=True)
                .first()
            )
            if original is not None and self.source != original:
                raise ValidationError(
                    {"source": "Cannot change source after samples have been logged."}
                )


class SensorSample(LockProtectedModel):
    run = models.ForeignKey(
        ExperimentRun, on_delete=models.CASCADE, related_name="samples"
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    sequence_number = models.PositiveBigIntegerField(null=True, blank=True)
    for sensor in ("do", "ph", "tds", "temperature"):
        for kind in ("raw", "filtered", "reference", "software_reference"):
            locals()[sensor + "_" + kind] = models.FloatField(null=True, blank=True)
        locals()[sensor + "_fpga_code"] = models.BigIntegerField(null=True, blank=True)
        locals()[sensor + "_software_code"] = models.BigIntegerField(
            null=True, blank=True
        )
    del sensor, kind
    extra_sensors = models.JSONField(default=dict, blank=True)
    sensor_status = models.JSONField(default=dict, blank=True)
    reference_timestamp = models.DateTimeField(null=True, blank=True)
    reference_source = models.CharField(max_length=200, blank=True)
    fpga_latency_us = models.FloatField(null=True, blank=True)
    fpga_cycles = models.PositiveIntegerField(null=True, blank=True)
    quality_flag = models.CharField(
        max_length=20,
        choices=choices("NORMAL SPIKE OUT_OF_RANGE SENSOR_FAULT TRANSIENT NOISY"),
        default="NORMAL",
    )
    signal_state = models.CharField(
        max_length=12,
        choices=choices("STABLE NORMAL NOISY TRANSIENT OUTLIER UNKNOWN"),
        default="UNKNOWN",
    )
    outlier_detected = models.BooleanField(default=False)
    transient_detected = models.BooleanField(default=False)
    ground_truth_spike = models.BooleanField(null=True, blank=True)
    spike_removed = models.BooleanField(null=True, blank=True)
    noise_estimate = models.FloatField(null=True, blank=True)
    adaptive_threshold = models.FloatField(null=True, blank=True)
    alpha_code = models.PositiveIntegerField(null=True, blank=True)
    alpha_value = models.FloatField(null=True, blank=True)
    packet_valid = models.BooleanField(default=True)
    packet_crc_ok = models.BooleanField(null=True, blank=True)
    source = models.CharField(
        max_length=12, choices=choices("REAL SIMULATED HIL SYNTHETIC"), default="REAL"
    )
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["run", "timestamp"]),
            models.Index(fields=["run", "sequence_number"]),
        ]

    def clean(self):
        super().clean()
        if self.run_id and self.source != self.run.source:
            raise ValidationError(
                {"source": "Sample source must match its experiment source."}
            )


class EventMarker(LockProtectedModel):
    run = models.ForeignKey(
        ExperimentRun, on_delete=models.CASCADE, related_name="events"
    )
    timestamp = models.DateTimeField(db_index=True)
    sensor = models.CharField(max_length=40, blank=True)
    event_type = models.CharField(max_length=40)
    raw_value = models.FloatField(null=True, blank=True)
    filtered_value = models.FloatField(null=True, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    state = models.CharField(max_length=30, blank=True)
    metadata = models.JSONField(default=dict, blank=True)


class ImmutableAuditQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Unlock audit records are immutable.")
        return super().bulk_create(objs, **kwargs)

    def update(self, **kwargs):
        raise ValidationError("Unlock audit records are immutable.")

    def delete(self):
        raise ValidationError("Unlock audit records are immutable.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Unlock audit records are immutable.")


class ExperimentUnlockAudit(models.Model):
    run = models.ForeignKey(
        ExperimentRun, on_delete=models.PROTECT, related_name="unlock_audit"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    unlocked_at = models.DateTimeField(auto_now_add=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    dataset_sha256 = models.CharField(max_length=64)
    research_package_sha256 = models.CharField(max_length=64)
    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-unlocked_at", "-pk")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Unlock audit records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Unlock audit records are immutable.")


from .hil_models import HILReference


def invalidate_run_summary(run_id):
    """Invalidate immediately and again after commit to cover concurrent reads."""
    from django.core.cache import cache
    from django.db import transaction

    key = f"summary:{run_id}"
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


def _invalidate_analysis(sender, instance, **kwargs):
    if sender is FPGAImplementation:
        for run_id in ExperimentRun.objects.filter(implementation=instance).values_list(
            "pk", flat=True
        ):
            invalidate_run_summary(run_id)
    else:
        invalidate_run_summary(
            instance.pk if sender is ExperimentRun else instance.run_id
        )


from django.db.models.signals import post_delete, post_save

for _model in (
    ExperimentRun,
    SensorSample,
    EventMarker,
    FPGAImplementation,
    HILReference,
):
    post_save.connect(_invalidate_analysis, sender=_model, weak=False)
    post_delete.connect(_invalidate_analysis, sender=_model, weak=False)
