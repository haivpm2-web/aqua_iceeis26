"""Pair independently imported software output with FPGA packets by sequence."""

from collections import defaultdict
from .analysis import compute_fixed_point_metrics


def sequence_alignment(rows, references, sensor):
    """Ambiguous duplicate packet sequences are excluded, never silently selected."""
    samples = defaultdict(list)
    missing_sequence = []
    for row in rows:
        sequence = row.get("sequence_number")
        if sequence is None:
            missing_sequence.append(row)
        else:
            samples[sequence].append(row)
    refs = {r["sequence_number"]: r for r in references if r["sensor"] == sensor}
    paired = [
        (packets[0], refs[seq])
        for seq, packets in sorted(samples.items())
        if len(packets) == 1 and seq in refs
    ]
    result = compute_fixed_point_metrics(
        [sample.get(sensor + "_filtered") for sample, ref in paired],
        [ref["software_reference"] for sample, ref in paired],
        [sample.get(sensor + "_fpga_code") for sample, ref in paired],
        [ref["software_integer_code"] for sample, ref in paired],
    )
    usable_pairs = sum(
        (
            sample.get(sensor + "_filtered") is not None
            and ref["software_reference"] is not None
        )
        or (
            sample.get(sensor + "_fpga_code") is not None
            and ref["software_integer_code"] is not None
        )
        for sample, ref in paired
    )
    result.update(
        sample_count=len(rows),
        paired_samples=usable_pairs,
        unmatched_samples=len(rows) - usable_pairs,
        matched_sequence_count=len(paired),
        reference_count=len(refs),
        unmatched_references=sum(
            seq not in samples or len(samples[seq]) != 1 for seq in refs
        ),
        missing_sequence_samples=len(missing_sequence),
        ambiguous_samples=sum(
            len(packets) for packets in samples.values() if len(packets) > 1
        ),
        bit_exact_matches=result["exact_matches"],
        bit_exact_mismatches=result["mismatch_count"],
        bit_exact_agreement_percentage=result["bit_exact_percent"],
        alignment="Exact run/sensor/sequence match; duplicate sample sequences excluded; no timestamp interpolation.",
    )
    return result
