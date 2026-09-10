import hashlib
import json
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import SensorSample, EventMarker, ExperimentRun, invalidate_run_summary
from .serializers import SampleSerializer, ImplementationSerializer
from .analysis import (
    compute_noise_reduction,
    compute_packet_metrics,
    compute_latency_metrics,
    compute_outlier_metrics,
    compute_fixed_point_metrics,
    compute_transient_metrics,
)

SENSORS = {"do": "mg/L", "ph": "pH", "tds": "ppm", "temperature": "°C"}


@transaction.atomic
def ingest(payloads):
    ids = {str(d.get("run_id")) for d in payloads if isinstance(d, dict)}
    ids = [
        int(v)
        for v in ids
        if v.isdigit() and len(v) <= 19 and int(v) <= 9223372036854775807
    ]
    serializer = SampleSerializer(
        data=payloads,
        many=True,
        context={
            "runs": ExperimentRun.objects.select_for_update()
            .order_by("pk")
            .in_bulk(ids)
        },
    )
    serializer.is_valid(raise_exception=True)
    samples = SensorSample.objects.bulk_create(
        [SensorSample(**d) for d in serializer.validated_data], batch_size=500
    )
    events = []
    for sample in samples:
        event_type = (
            "PACKET_FAULT"
            if not sample.packet_valid or sample.packet_crc_ok is False
            else (
                "SPIKE"
                if sample.outlier_detected
                else (
                    "TRANSIENT"
                    if sample.transient_detected
                    else (
                        sample.quality_flag if sample.quality_flag != "NORMAL" else None
                    )
                )
            )
        )
        if event_type:
            events.append(
                EventMarker(
                    run_id=sample.run_id,
                    timestamp=sample.timestamp,
                    event_type=event_type,
                    state=sample.signal_state,
                    threshold=sample.adaptive_threshold,
                )
            )
        for sensor, state in sample.sensor_status.items():
            if state != "OK":
                events.append(
                    EventMarker(
                        run_id=sample.run_id,
                        timestamp=sample.timestamp,
                        sensor=sensor,
                        event_type=state,
                        state=sample.signal_state,
                        raw_value=getattr(sample, sensor + "_raw", None),
                        filtered_value=getattr(sample, sensor + "_filtered", None),
                        threshold=sample.adaptive_threshold,
                    )
                )
    EventMarker.objects.bulk_create(events, batch_size=500)
    for run_id in {sample.run_id for sample in samples}:
        invalidate_run_summary(run_id)
    return samples


def run_summary(run, queryset=None):
    qs = queryset.filter(run_id=run.pk) if queryset is not None else run.samples.all()
    signature = qs.aggregate(n=Count("id"), last=Max("id"))
    if signature["n"] > settings.ANALYSIS_MAX_SAMPLES:
        raise ValidationError(
            "Analysis exceeds configured sample limit; select start/end to analyze a smaller interval."
        )
    # Cache only whole-run analyses; include editable run and event inputs.
    inputs = dict(
        signature=signature,
        source=run.source,
        filter_version=run.filter_version,
        configuration=run.sensor_configuration,
        implementation=(
            ImplementationSerializer(run.implementation).data
            if run.implementation
            else None
        ),
        events=run.events.aggregate(n=Count("id"), last=Max("id")),
    )
    fingerprint = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, default=str).encode()
    ).hexdigest()
    key = f"summary:{run.pk}"
    if queryset is None:
        cached = cache.get(key)
        if cached is not None and cached["fingerprint"] == fingerprint:
            return cached["result"]
    rows = list(qs.order_by("received_at", "id").values())
    source_rows = [r for r in rows if r["source"] == run.source]
    received_good = [
        r for r in source_rows if r["packet_valid"] and r["packet_crc_ok"] is not False
    ]
    good = sorted(received_good, key=lambda r: (r["timestamp"], r["id"]))
    result = dict(
        run_id=run.pk,
        source=run.source,
        filter_version=run.filter_version,
        sample_count=len(rows),
        analysis_count=len(good),
        source_mismatch_count=len(rows) - len(source_rows),
        exclusion="Invalid packet/CRC rows excluded from signal metrics; retained in communication metrics. Rows with a mismatched source are excluded from all metrics.",
        statistics_convention="Population SD/variance; unscaled MAD; reductions on aligned raw/filtered pairs.",
        communication=compute_packet_metrics(source_rows),
        sensors={},
        fixed_point={},
        dynamic=[],
    )
    result["reference_alignment"] = dict(
        excluded_rows=sum(
            r["reference_timestamp"] is not None
            and r["reference_timestamp"] != r["timestamp"]
            and any(r[s + "_reference"] is not None for s in SENSORS)
            for r in good
        ),
        definition="Measurement references without a reference timestamp are explicitly supplied as row-aligned pairs. If provided, reference_timestamp must equal sample timestamp. No interpolation or clock synchronization is inferred. Software outputs are paired by sample row independently.",
    )
    for sensor in SENSORS:
        values = lambda suffix: [r[sensor + "_" + suffix] for r in good]
        references = [
            (
                r[sensor + "_reference"]
                if r["reference_timestamp"] is None
                or r["reference_timestamp"] == r["timestamp"]
                else None
            )
            for r in good
        ]
        result["sensors"][sensor] = compute_noise_reduction(
            values("raw"), values("filtered"), references
        )
        result["fixed_point"][sensor] = compute_fixed_point_metrics(
            values("filtered"),
            values("software_reference"),
            values("fpga_code"),
            values("software_code"),
        )
    hil_references = list(
        run.hil_references.order_by("sensor", "sequence_number").values()
    )
    if hil_references:
        from .hil import sequence_alignment

        result["hil_alignment"] = {}
        for sensor in SENSORS:
            if any(ref["sensor"] == sensor for ref in hil_references):
                aligned = sequence_alignment(good, hil_references, sensor)
                result["hil_alignment"][sensor] = aligned
                result["fixed_point"][sensor] = aligned
    result["latency"] = compute_latency_metrics(
        [r["fpga_latency_us"] for r in received_good], [r["timestamp"] for r in good]
    )
    result["outliers"] = compute_outlier_metrics(
        [r["outlier_detected"] for r in good],
        [r["ground_truth_spike"] for r in good],
        [r["spike_removed"] for r in good],
    )
    result["transient_flagged_samples"] = sum(r["transient_detected"] for r in good)
    result["transient_count"] = sum(
        r["transient_detected"] and (i == 0 or not good[i - 1]["transient_detected"])
        for i, r in enumerate(good)
    )
    result["transient_count_definition"] = (
        "Consecutive flagged samples form one observed episode; missing packets may conceal episode boundaries."
    )
    steps = list(
        run.events.filter(event_type="STEP").order_by("timestamp", "id").values()
    )
    for i, event in enumerate(steps):
        following = next(
            (e["timestamp"] for e in steps[i + 1 :] if e["sensor"] == event["sensor"]),
            None,
        )
        event_rows = [
            r for r in good if following is None or r["timestamp"] < following
        ]
        result["dynamic"].append(
            dict(
                event_id=event["id"],
                sensor=event["sensor"],
                **compute_transient_metrics(event_rows, event),
            )
        )
    result["duration_s"] = (
        (good[-1]["timestamp"] - good[0]["timestamp"]).total_seconds() if good else None
    )
    result["implementation"] = (
        ImplementationSerializer(run.implementation).data
        if run.implementation
        else None
    )
    if run.implementation:
        impl = result["implementation"]
        for resource in ("lut", "ff", "dsp", "bram"):
            used, available = impl[resource + "_used"], impl[resource + "_available"]
            impl[resource + "_percent"] = (
                100 * used / available if used is not None and available else None
            )
        cycles = next(
            (
                r["fpga_cycles"]
                for r in reversed(received_good)
                if r["fpga_cycles"] is not None
            ),
            None,
        )
        result["latency"]["processing_cycles"] = cycles
        result["latency"]["theoretical_us"] = (
            cycles / run.implementation.clock_mhz
            if cycles is not None and run.implementation.clock_mhz
            else None
        )
    if queryset is None:
        cache.set(key, {"fingerprint": fingerprint, "result": result}, 15)
    return result


def sensor_health(sample, run):
    if sample is None:
        return {s: "OFFLINE" for s in SENSORS}
    offline = (
        timezone.now() - sample.received_at
    ).total_seconds() > settings.SENSOR_OFFLINE_SECONDS
    configuration = (
        run.sensor_configuration if isinstance(run.sensor_configuration, dict) else {}
    )
    ranges = configuration.get("validity_ranges", {})
    if not isinstance(ranges, dict):
        ranges = {}
    result = {}
    for sensor in SENSORS:
        value = getattr(sample, sensor + "_raw")
        statuses = (
            sample.sensor_status if isinstance(sample.sensor_status, dict) else {}
        )
        state = statuses.get(sensor, "OK")
        if offline or value is None:
            state = "OFFLINE"
        elif not sample.packet_valid or sample.packet_crc_ok is False:
            state = "SENSOR_FAULT"
        elif (
            sensor in ranges
            and isinstance(ranges[sensor], list)
            and len(ranges[sensor]) == 2
            and all(isinstance(v, (float, int)) for v in ranges[sensor])
            and not ranges[sensor][0] <= value <= ranges[sensor][1]
        ):
            state = "OUT_OF_RANGE"
        result[sensor] = state
    return result
