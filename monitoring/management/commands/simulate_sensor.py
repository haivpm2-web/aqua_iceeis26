import math
import random
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from monitoring.models import ExperimentRun, EventMarker
from monitoring.services import ingest


class Command(BaseCommand):
    help = "Create an isolated, reproducible SIMULATED run for local interface testing."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1000)
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Simulation is restricted to DEBUG=true local development."
            )
        count = options["count"]
        if not 1 <= count <= 100000:
            raise CommandError("count must be between 1 and 100000.")
        rng = random.Random(options["seed"])
        start = timezone.now() - timedelta(seconds=count / 100)
        run = ExperimentRun.objects.create(
            run_name=f"UI validation · simulated {count} samples",
            run_type="SYNTHETIC",
            source="SIMULATED",
            status="RUNNING",
            started_at=start,
            filter_version="Demo software IIR (not FPGA evidence)",
            notes=f'Frontend testing only. Seed {options["seed"]}. Latency is simulated.',
            sensor_configuration={"sample_rate_hz": 100, "seed": options["seed"]},
        )
        batch, previous = [], {"do": 6.5, "ph": 7.4}
        step_index = count * 3 // 5
        EventMarker.objects.create(
            run=run,
            timestamp=start + timedelta(seconds=step_index / 100),
            sensor="do",
            event_type="STEP",
            metadata={
                "initial": 6.5,
                "target": 6.8,
                "settling_band": 0.08,
                "hold_seconds": 0.5,
                "source": "SIMULATED",
            },
        )
        for i in range(count):
            spike = i % 137 == 50
            transient = step_index <= i < step_index + 20
            payload = dict(
                run_id=run.pk,
                timestamp=(start + timedelta(seconds=i / 100)).isoformat(),
                sequence_number=i,
                source="SIMULATED",
                tds_raw=420 + rng.gauss(0, 2),
                temperature_raw=27.5 + rng.gauss(0, 0.03),
                fpga_latency_us=1.2 + rng.random() * 0.2,
                noise_estimate=0.05,
                adaptive_threshold=0.2,
                alpha_value=0.125,
                ground_truth_spike=spike,
                outlier_detected=spike,
                quality_flag="SPIKE" if spike else "NORMAL",
                signal_state=(
                    "OUTLIER" if spike else "TRANSIENT" if transient else "STABLE"
                ),
                transient_detected=transient,
                reference_source="Synthetic clean signal",
                sensor_status={
                    "do": "OUTLIER" if spike else "OK",
                    "ph": "OUTLIER" if spike else "OK",
                },
            )
            for sensor, base in [("do", 6.5), ("ph", 7.4)]:
                reference = base + 0.03 * math.sin(i / 100)
                if sensor == "do" and i >= step_index:
                    reference += 0.3
                raw = reference + rng.gauss(0, 0.05) + (1.5 if spike else 0)
                filtered = (
                    previous[sensor]
                    if spike
                    else previous[sensor] + 0.125 * (raw - previous[sensor])
                )
                previous[sensor] = filtered
                payload.update(
                    {
                        sensor + "_raw": raw,
                        sensor + "_filtered": filtered,
                        sensor + "_reference": reference,
                    }
                )
            batch.append(payload)
            if len(batch) == 1000:
                ingest(batch)
                batch = []
        if batch:
            ingest(batch)
        run.status = "COMPLETED"
        run.ended_at = start + timedelta(seconds=(count - 1) / 100)
        run.save(update_fields=["status", "ended_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Created SIMULATED run {run.pk}: {count} samples. Not publication evidence."
            )
        )
