"""Scientific metrics. Population dispersion; aligned references; undefined = None."""

import math
import statistics as st


def finite_number(value):
    """Accept measurements only; missing/nonfinite values never enter metrics."""
    return type(value) in (int, float) and abs(value) <= 1e100 and math.isfinite(value)


def compute_basic_stats(values):
    x = [float(v) for v in values if finite_number(v)]
    result = dict.fromkeys(
        (
            "mean",
            "minimum",
            "maximum",
            "range",
            "sd",
            "variance",
            "median",
            "mad",
            "rms",
            "cv_percent",
        )
    )
    result["count"] = len(x)
    if not x:
        return result
    mean, median = st.mean(x), st.median(x)
    sd = st.pstdev(x)
    cv = 100 * sd / abs(mean) if mean else None
    result.update(
        mean=mean,
        minimum=min(x),
        maximum=max(x),
        range=max(x) - min(x),
        sd=sd,
        variance=st.pvariance(x),
        median=median,
        mad=st.median(abs(v - median) for v in x),
        rms=math.sqrt(st.mean(v * v for v in x)),
        cv_percent=cv if cv is not None and math.isfinite(cv) else None,
    )
    return result


def compute_error_metrics(values, references):
    pairs = [
        (a, b)
        for a, b in zip(values, references)
        if finite_number(a) and finite_number(b)
    ]
    if not pairs:
        return dict(count=0, mae=None, mse=None, rmse=None, max_absolute_error=None)
    errors = [a - b for a, b in pairs]
    mse = st.mean(e * e for e in errors)
    return dict(
        count=len(pairs),
        mae=st.mean(abs(e) for e in errors),
        mse=mse,
        rmse=math.sqrt(mse),
        max_absolute_error=max(abs(e) for e in errors),
    )


def reduction(raw, filtered):
    value = (
        100 * (raw - filtered) / raw
        if raw is not None and filtered is not None and raw > 0
        else None
    )
    return value if value is not None and math.isfinite(value) else None


def compute_snr_metrics(raw, filtered, references):
    triples = [
        (a, b, r)
        for a, b, r in zip(raw, filtered, references)
        if all(finite_number(v) for v in (a, b, r))
    ]
    result = dict(
        raw=None,
        filtered=None,
        improvement_db=None,
        count=len(triples),
        definition="10 log10(mean(reference²) / mean((observed-reference)²)); includes DC",
    )
    if not triples:
        return result
    power = st.mean(r * r for a, b, r in triples)
    for name, index in [("raw", 0), ("filtered", 1)]:
        noise = st.mean((t[index] - t[2]) ** 2 for t in triples)
        if power > 0 and noise > 0:
            result[name] = 10 * (math.log10(power) - math.log10(noise))
    if result["raw"] is not None and result["filtered"] is not None:
        result["improvement_db"] = result["filtered"] - result["raw"]
    return result


def compute_noise_reduction(raw, filtered, references=None):
    pairs = [
        (a, b) for a, b in zip(raw, filtered) if finite_number(a) and finite_number(b)
    ]
    a = compute_basic_stats([p[0] for p in pairs])
    b = compute_basic_stats([p[1] for p in pairs])
    refs = references if references is not None else [None] * len(raw)
    triples = [
        (x, y, r)
        for x, y, r in zip(raw, filtered, refs)
        if all(finite_number(v) for v in (x, y, r))
    ]
    raw_error = compute_error_metrics(raw, refs)
    filtered_error = compute_error_metrics(filtered, refs)
    paired_raw_error = compute_error_metrics(
        [t[0] for t in triples], [t[2] for t in triples]
    )
    paired_filtered_error = compute_error_metrics(
        [t[1] for t in triples], [t[2] for t in triples]
    )
    return dict(
        raw=compute_basic_stats(raw),
        filtered=compute_basic_stats(filtered),
        paired_count=len(pairs),
        sd_reduction_percent=reduction(a["sd"], b["sd"]),
        mad_reduction_percent=reduction(a["mad"], b["mad"]),
        peak_to_peak_reduction_percent=reduction(a["range"], b["range"]),
        raw_error=raw_error,
        filtered_error=filtered_error,
        error_paired_count=len(triples),
        rmse_improvement_percent=reduction(
            paired_raw_error["rmse"], paired_filtered_error["rmse"]
        ),
        snr=compute_snr_metrics(raw, filtered, refs),
    )


def compute_outlier_metrics(detected, labels, removed=None):
    pairs = [(bool(d), bool(t)) for d, t in zip(detected, labels) if t is not None]
    result = dict(
        detected=sum(detected),
        outlier_rate_percent=100 * sum(detected) / len(detected) if detected else None,
        labelled_count=len(pairs),
        true_positives=None,
        false_positives=None,
        true_negatives=None,
        false_negatives=None,
        precision=None,
        recall=None,
        f1=None,
        spike_rejection_rate=None,
        false_removal_rate=None,
    )
    if pairs:
        tp = sum(d and t for d, t in pairs)
        fp = sum(d and not t for d, t in pairs)
        tn = sum(not d and not t for d, t in pairs)
        fn = sum(not d and t for d, t in pairs)
        result.update(
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        )
    removal_pairs = [
        (r, t) for r, t in zip(removed or [], labels) if r is not None and t is not None
    ]
    spikes = [r for r, t in removal_pairs if t]
    clean = [r for r, t in removal_pairs if not t]
    result.update(
        spike_rejection_rate=sum(spikes) / len(spikes) if spikes else None,
        false_removal_rate=sum(clean) / len(clean) if clean else None,
    )
    return result


def compute_packet_metrics(rows):
    seen, high, duplicates, out_of_order = set(), None, 0, 0
    reset_suspected = False
    total = valid = sequenced = 0
    for row in rows:
        total += 1
        valid += bool(row["packet_valid"] and row.get("packet_crc_ok") is not False)
        seq = row.get("sequence_number")
        if seq is None:
            continue
        sequenced += 1
        if high is not None and high > 1 and seq in (0, 1) and seq < high:
            # A reboot/wrap cannot be distinguished from a late early packet.
            reset_suspected = True
        if seq in seen:
            duplicates += 1
        elif high is not None and seq < high:
            out_of_order += 1
        seen.add(seq)
        high = seq if high is None else max(high, seq)
    gaps = (
        max(seen) - min(seen) + 1 - len(seen) if seen and not reset_suspected else None
    )
    return dict(
        received=total,
        valid=valid,
        invalid=total - valid,
        duplicates=duplicates,
        out_of_order=out_of_order,
        sequenced=sequenced,
        sequence_gaps=gaps,
        dropped=None,
        success_percent=100 * valid / total if total else None,
        denominator="received packets",
        sequence_reset_suspected=reset_suspected,
        sequence_assumption="Within observed min/max; one monotonic sequence per run, no resets/wrap. Gaps are N/A if an early sequence suggests reset/wrap. Repeated sequence values are not proven duplicate packets across a reset; gaps are not proven packet loss.",
    )


def percentile(values, p):
    if not values:
        return None
    x = sorted(values)
    pos = (len(x) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return x[lo] + (x[hi] - x[lo]) * (pos - lo)


def compute_latency_metrics(values, timestamps=None):
    x = [v for v in values if finite_number(v) and v >= 0]
    times = [t for t in (timestamps or []) if t is not None]
    duration = (max(times) - min(times)).total_seconds() if len(times) > 1 else 0
    return dict(
        count=len(x),
        current=x[-1] if x else None,
        mean=st.mean(x) if x else None,
        minimum=min(x) if x else None,
        maximum=max(x) if x else None,
        p50=percentile(x, 0.5),
        p95=percentile(x, 0.95),
        p99=percentile(x, 0.99),
        throughput_samples_s=(len(times) - 1) / duration if duration > 0 else None,
        throughput_definition="Observed sample timestamp rate; not FPGA maximum capacity",
    )


def compute_fixed_point_metrics(
    outputs, references, fpga_codes=None, software_codes=None
):
    result = compute_error_metrics(outputs, references)
    pairs = [
        (a, b)
        for a, b in zip(fpga_codes or [], software_codes or [])
        if type(a) is int and type(b) is int
    ]
    exact = sum(a == b for a, b in pairs)
    relative = [
        abs((a - b) / b)
        for a, b in zip(outputs, references)
        if finite_number(a)
        and finite_number(b)
        and b != 0
        and math.isfinite((a - b) / b)
    ]
    result.update(
        code_count=len(pairs),
        exact_matches=exact if pairs else None,
        mismatch_count=len(pairs) - exact if pairs else None,
        bit_exact_percent=100 * exact / len(pairs) if pairs else None,
        mean_relative_error=st.mean(relative) if relative else None,
    )
    return result


def compute_transient_metrics(rows, event=None):
    result = dict(
        detected_transition_time=None,
        response_delay_s=None,
        rise_time_s=None,
        fall_time_s=None,
        settling_time_s=None,
        overshoot_percent=None,
        steady_state_error=None,
    )
    if (
        not event
        or not isinstance(event.get("metadata"), dict)
        or not all(
            finite_number(event["metadata"].get(k))
            for k in ("initial", "target", "settling_band", "hold_seconds")
        )
    ):
        return result
    meta, start = event["metadata"], event["timestamp"]
    sensor = event["sensor"]
    initial, target = meta["initial"], meta["target"]
    if (
        sensor not in ("do", "ph", "tds", "temperature")
        or meta["settling_band"] <= 0
        or meta["hold_seconds"] <= 0
    ):
        return result
    delta = target - initial
    points = sorted(
        [
            (
                r["timestamp"],
                r.get(sensor + "_filtered"),
                r.get("transient_detected", False),
            )
            for r in rows
            if r["timestamp"] >= start and finite_number(r.get(sensor + "_filtered"))
        ],
        key=lambda p: p[0],
    )
    if not points or not delta:
        return result
    detected = next((t for t, v, flag in points if flag), None)
    result.update(
        detected_transition_time=detected,
        response_delay_s=(detected - start).total_seconds() if detected else None,
    )

    def crossing(level):
        for before, after in zip(points, points[1:]):
            if (before[1] - initial) / delta < level <= (after[1] - initial) / delta:
                return after[0]
        return None

    t10, t90 = crossing(0.1), crossing(0.9)
    if t10 and t90 and t90 > t10:
        result["rise_time_s" if delta > 0 else "fall_time_s"] = (
            t90 - t10
        ).total_seconds()
    # Do not report zero overshoot for a response that has not reached target.
    observed_overshoot = max((v - target) / delta for t, v, f in points) * 100
    if observed_overshoot > 0:
        result["overshoot_percent"] = observed_overshoot
    last_outside = max(
        (
            i
            for i, (t, v, f) in enumerate(points)
            if abs(v - target) > meta["settling_band"]
        ),
        default=-1,
    )
    tail = points[last_outside + 1 :]
    if tail and (tail[-1][0] - tail[0][0]).total_seconds() >= meta["hold_seconds"]:
        if last_outside >= 0 or tail[0][0] == start:
            result["settling_time_s"] = (tail[0][0] - start).total_seconds()
        result["steady_state_error"] = st.mean(v - target for t, v, f in tail)
        result["overshoot_percent"] = max(0, observed_overshoot)
    result["definition"] = (
        "Observed 10%-90% threshold crossings without interpolation; settling requires an in-band tail spanning hold_seconds. Metrics describe the sampled observation window."
    )
    return result
