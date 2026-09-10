from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .models import ExperimentRun, SensorSample
from .hil import sequence_alignment
from .hil_models import HILReference
from .services import run_summary


@override_settings(INGEST_API_TOKEN="hil-test-token", SECURE_SSL_REDIRECT=False)
class HILTests(TestCase):
    def setUp(self):
        self.run = ExperimentRun.objects.create(
            run_name="HIL sequence test", source="HIL", run_type="HIL"
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer hil-test-token")

    def test_matching_uses_sequence_and_integer_codes(self):
        for sequence, output, code in [(2, 2.5, 25), (1, 1.0, 10), (3, 4.0, 40)]:
            SensorSample.objects.create(
                run=self.run,
                source="HIL",
                sequence_number=sequence,
                do_filtered=output,
                do_fpga_code=code,
            )
        data = [
            {
                "sensor": "do",
                "sequence_number": 1,
                "software_reference": 1,
                "software_integer_code": 10,
            },
            {
                "sensor": "do",
                "sequence_number": 2,
                "software_reference": 2,
                "software_integer_code": 20,
            },
        ]
        response = self.client.post(
            f"/api/v1/runs/{self.run.pk}/hil-references/", data, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        metrics = run_summary(self.run)["fixed_point"]["do"]
        self.assertEqual(metrics["paired_samples"], 2)
        self.assertEqual(metrics["unmatched_samples"], 1)
        self.assertEqual(metrics["mae"], 0.25)
        self.assertEqual(metrics["mse"], 0.125)
        self.assertEqual(metrics["bit_exact_agreement_percentage"], 50)

    def test_duplicate_sequences_are_ambiguous(self):
        rows = [
            {"sequence_number": 1, "do_filtered": 1},
            {"sequence_number": 1, "do_filtered": 2},
            {"sequence_number": None, "do_filtered": 3},
        ]
        refs = [
            {
                "sensor": "do",
                "sequence_number": 1,
                "software_reference": 1,
                "software_integer_code": None,
            }
        ]
        result = sequence_alignment(rows, refs, "do")
        self.assertEqual(result["paired_samples"], 0)
        self.assertEqual(result["ambiguous_samples"], 2)
        self.assertIsNone(result["bit_exact_agreement_percentage"])

    def test_duplicate_references_fail_atomically(self):
        data = {"sensor": "do", "sequence_number": 1, "software_reference": 1}
        url = f"/api/v1/runs/{self.run.pk}/hil-references/"
        self.assertEqual(
            self.client.post(url, [data, data], format="json").status_code, 400
        )
        self.assertEqual(HILReference.objects.count(), 0)
        self.assertEqual(self.client.post(url, data, format="json").status_code, 201)
        self.assertEqual(self.client.post(url, data, format="json").status_code, 400)

    def test_float_equality_is_not_bit_exact(self):
        result = sequence_alignment(
            [{"sequence_number": 1, "do_filtered": 1}],
            [
                {
                    "sensor": "do",
                    "sequence_number": 1,
                    "software_reference": 1,
                    "software_integer_code": None,
                }
            ],
            "do",
        )
        self.assertEqual(result["mae"], 0)
        self.assertIsNone(result["bit_exact_agreement_percentage"])
