"""Paper table definitions shared by HTML and CSV."""


def paper_tables(summary):
    method = summary["filter_version"] or "Unspecified"
    a, b, d = [], [], []
    for sensor in ("do", "ph"):
        s = summary["sensors"][sensor]
        a.append(
            [
                sensor.upper(),
                method,
                s["raw"]["sd"],
                s["filtered"]["sd"],
                s["sd_reduction_percent"],
                s["raw"]["mad"],
                s["filtered"]["mad"],
                s["snr"]["improvement_db"],
                s["filtered_error"]["rmse"],
            ]
        )
        f = summary["fixed_point"][sensor]
        d.append(
            [
                sensor.upper(),
                method,
                f["count"],
                f["code_count"],
                f["mae"],
                f["rmse"],
                f["max_absolute_error"],
                f["bit_exact_percent"],
            ]
        )
    for event in summary["dynamic"]:
        b.append(
            [
                method,
                event["sensor"],
                event["response_delay_s"],
                event["rise_time_s"],
                event["fall_time_s"],
                event["settling_time_s"],
                event["overshoot_percent"],
            ]
        )
    impl = summary["implementation"] or {}
    lat, comm = summary["latency"], summary["communication"]
    return {
        "A": dict(
            title="Denoising performance",
            headers=[
                "Sensor",
                "Method",
                "Raw SD",
                "Filtered SD",
                "SD reduction %",
                "Raw MAD",
                "Filtered MAD",
                "Delta-SNR (dB)",
                "RMSE",
            ],
            rows=a,
        ),
        "B": dict(
            title="Dynamic response",
            headers=[
                "Method",
                "Sensor",
                "Delay (s)",
                "Rise (s)",
                "Fall (s)",
                "Settling (s)",
                "Overshoot %",
            ],
            rows=b,
        ),
        "C": dict(
            title="FPGA performance",
            headers=[
                "Method",
                "LUT",
                "FF",
                "DSP",
                "BRAM",
                "Mean latency (us)",
                "Observed samples/s",
            ],
            rows=[
                [
                    method,
                    impl.get("lut_used"),
                    impl.get("ff_used"),
                    impl.get("dsp_used"),
                    impl.get("bram_used"),
                    lat["mean"],
                    lat["throughput_samples_s"],
                ]
            ],
        ),
        "D": dict(
            title="Fixed-point verification",
            headers=[
                "Sensor",
                "Method",
                "Numeric pairs",
                "Integer code pairs",
                "MAE",
                "RMSE",
                "Max error",
                "Bit-exact %",
            ],
            rows=d,
        ),
        "E": dict(
            title="Communication reliability",
            headers=[
                "Received",
                "Valid",
                "Invalid",
                "Dropped (unproven)",
                "Sequence gaps",
                "Success % (received denominator)",
            ],
            rows=[
                [
                    comm["received"],
                    comm["valid"],
                    comm["invalid"],
                    comm["dropped"],
                    comm["sequence_gaps"],
                    comm["success_percent"],
                ]
            ],
        ),
    }
