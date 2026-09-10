import math
from collections.abc import Mapping
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from .models import ExperimentRun, SensorSample, FPGAImplementation, EventMarker


class ValidatedModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {"non_field_errors": ["Expected a JSON object."]}
            )
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"unknown_fields": sorted(unknown)})
        result = super().to_internal_value(data)
        for key, value in result.items():
            pending = [value]
            while pending:
                item = pending.pop()
                if isinstance(item, (float, int)) and (
                    abs(item) > 1e100 or not math.isfinite(item)
                ):
                    raise serializers.ValidationError(
                        {
                            key: "A finite measurement with magnitude <= 1e100 is required."
                        }
                    )
                if isinstance(item, Mapping):
                    pending.extend(item.values())
                elif isinstance(item, (list, tuple)):
                    pending.extend(item)
        return result


class RunSerializer(ValidatedModelSerializer):
    class Meta:
        model = ExperimentRun
        fields = "__all__"
        read_only_fields = (
            "locked_at",
            "locked_by",
            "dataset_sha256",
            "research_package_sha256",
            "integrity_generated_at",
        )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            protected = set(data) & set(self.Meta.read_only_fields)
            if protected:
                raise serializers.ValidationError(
                    {
                        name: "Managed by research finalization actions."
                        for name in protected
                    }
                )
        return super().to_internal_value(data)

    def validate(self, data):
        if self.instance and self.instance.status == "LOCKED":
            raise serializers.ValidationError(
                "Locked experiment evidence is immutable; explicitly unlock it first."
            )
        if data.get("status") == "LOCKED":
            raise serializers.ValidationError(
                {"status": "Use the protected Lock Experiment action."}
            )
        started = data.get(
            "started_at", self.instance.started_at if self.instance else timezone.now()
        )
        ended = data.get("ended_at", self.instance.ended_at if self.instance else None)
        if ended and ended < started:
            raise serializers.ValidationError("ended_at must not precede started_at.")
        if (
            self.instance
            and data.get("source", self.instance.source) != self.instance.source
            and (
                self.instance.samples.exists() or self.instance.hil_references.exists()
            )
        ):
            raise serializers.ValidationError(
                {"source": "Cannot change source after samples have been logged."}
            )
        config = data.get(
            "sensor_configuration",
            self.instance.sensor_configuration if self.instance else {},
        )
        if not isinstance(config, dict):
            raise serializers.ValidationError("sensor_configuration must be an object.")
        if not isinstance(
            data.get(
                "calibration_coefficients",
                getattr(self.instance, "calibration_coefficients", {}),
            ),
            dict,
        ):
            raise serializers.ValidationError(
                {"calibration_coefficients": "Must be an object."}
            )
        ranges = config.get("validity_ranges", {})
        if not isinstance(ranges, dict):
            raise serializers.ValidationError("validity_ranges must be an object.")
        for sensor, limits in ranges.items():
            if sensor not in ("do", "ph", "tds", "temperature"):
                raise serializers.ValidationError(
                    "Unsupported validity range sensor: " + str(sensor)
                )
            if (
                not isinstance(limits, list)
                or len(limits) != 2
                or not all(type(v) in (int, float) and math.isfinite(v) for v in limits)
                or limits[0] >= limits[1]
            ):
                raise serializers.ValidationError(
                    "Each validity range must be [minimum, maximum]."
                )
        return data


class CachedRunField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if "runs" in self.context:
            try:
                if isinstance(data, bool) or str(int(data)) != str(data):
                    raise ValueError()
                return self.context["runs"][int(data)]
            except (ValueError, TypeError, KeyError, OverflowError):
                raise serializers.ValidationError("Unknown or invalid run_id.")
        return super().to_internal_value(data)


class SampleSerializer(ValidatedModelSerializer):
    run_id = CachedRunField(source="run", queryset=ExperimentRun.objects.all())

    class Meta:
        model = SensorSample
        exclude = ("run",)
        read_only_fields = ("id", "received_at")

    def validate(self, data):
        run = data.get("run", self.instance.run if self.instance else None)
        if run is None:
            raise serializers.ValidationError({"run_id": "This field is required."})
        if run.status == "LOCKED" or (
            self.instance and self.instance.run.status == "LOCKED"
        ):
            raise serializers.ValidationError(
                "Cannot modify samples or references belonging to a locked experiment."
            )
        data.setdefault("source", run.source)
        if data["source"] != run.source:
            raise serializers.ValidationError(
                "Sample source must match its experiment source."
            )
        if data.get("timestamp", timezone.now()) > timezone.now() + timedelta(
            seconds=getattr(settings, "MAX_SAMPLE_FUTURE_SECONDS", 300)
        ):
            raise serializers.ValidationError(
                {
                    "timestamp": "Sample timestamp is too far in the future; check the device clock."
                }
            )
        if data.get("packet_valid", True):
            missing = [
                f
                for f in ("do_raw", "ph_raw", "tds_raw", "temperature_raw")
                if data.get(f) is None
            ]
            if missing:
                raise serializers.ValidationError({"missing_raw_channels": missing})
        for name in ("fpga_latency_us", "noise_estimate", "adaptive_threshold"):
            if data.get(name) is not None and data[name] < 0:
                raise serializers.ValidationError({name: "Must be nonnegative."})
        if data.get("alpha_value") is not None and not 0 <= data["alpha_value"] <= 1:
            raise serializers.ValidationError(
                {"alpha_value": "Must be between 0 and 1."}
            )
        statuses = data.get("sensor_status", {})
        if not isinstance(statuses, dict) or any(
            k not in ("do", "ph", "tds", "temperature")
            or s
            not in ("OK", "NOISY", "OUTLIER", "OUT_OF_RANGE", "SENSOR_FAULT", "OFFLINE")
            for k, s in statuses.items()
        ):
            raise serializers.ValidationError("Invalid per-sensor status.")
        if not isinstance(data.get("extra_sensors", {}), dict):
            raise serializers.ValidationError("extra_sensors must be an object.")
        return data


class ImplementationSerializer(ValidatedModelSerializer):
    class Meta:
        model = FPGAImplementation
        fields = "__all__"

    def validate(self, data):
        if (
            self.instance
            and ExperimentRun.objects.filter(
                implementation=self.instance, status="LOCKED"
            ).exists()
        ):
            raise serializers.ValidationError(
                "FPGA configuration is referenced by a locked experiment; create a separate implementation record for new experiments."
            )
        for key, value in data.items():
            if (
                isinstance(value, (int, float))
                and key != "timing_slack_ns"
                and value < 0
            ):
                raise serializers.ValidationError({key: "Must be nonnegative."})
        for resource in ("lut", "ff", "dsp", "bram"):
            used = data.get(
                resource + "_used", getattr(self.instance, resource + "_used", None)
            )
            available = data.get(
                resource + "_available",
                getattr(self.instance, resource + "_available", None),
            )
            if used is not None and available is not None and used > available:
                raise serializers.ValidationError(resource + " used exceeds available.")
        return data


class EventSerializer(ValidatedModelSerializer):
    class Meta:
        model = EventMarker
        fields = "__all__"

    def validate(self, data):
        run = data.get("run", self.instance.run if self.instance else None)
        if (run and run.status == "LOCKED") or (
            self.instance and self.instance.run.status == "LOCKED"
        ):
            raise serializers.ValidationError(
                "Cannot modify event markers belonging to a locked experiment."
            )
        meta = data.get("metadata", self.instance.metadata if self.instance else {})
        if not isinstance(meta, dict):
            raise serializers.ValidationError("metadata must be an object.")
        if data.get("event_type", getattr(self.instance, "event_type", None)) == "STEP":
            if data.get("sensor", getattr(self.instance, "sensor", None)) not in (
                "do",
                "ph",
                "tds",
                "temperature",
            ):
                raise serializers.ValidationError("STEP requires a supported sensor.")
            for key in ("initial", "target", "settling_band", "hold_seconds"):
                if (
                    key not in meta
                    or type(meta[key]) not in (float, int)
                    or not math.isfinite(meta[key])
                ):
                    raise serializers.ValidationError(
                        "STEP metadata requires finite " + key
                    )
            if meta["settling_band"] <= 0 or meta["hold_seconds"] <= 0:
                raise serializers.ValidationError(
                    "Settling band and hold seconds must be positive."
                )
            if meta["initial"] == meta["target"]:
                raise serializers.ValidationError(
                    "STEP target must differ from its initial value."
                )
        return data
