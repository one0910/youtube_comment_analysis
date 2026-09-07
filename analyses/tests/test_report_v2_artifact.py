"""已儲存 v2 報告的離線載入測試，不呼叫 DeepSeek。"""

from copy import deepcopy
from dataclasses import asdict
import json

from django.test import SimpleTestCase

from ..services.report_v2_artifact_service import load_report_v2_payload
from .report_v2_factory import build_report_test_fixture


class ReportV2ArtifactLoaderTests(SimpleTestCase):
    def setUp(self):
        self.report, self.facts = build_report_test_fixture()
        self.payload = json.loads(json.dumps(asdict(self.report), ensure_ascii=False))

    def test_round_trip_restores_validated_report(self):
        self.assertEqual(load_report_v2_payload(self.payload), self.report)

    def test_legacy_empty_report_sections_are_ignored(self):
        self.payload.update(risks=[], recommendations=[])
        self.assertEqual(load_report_v2_payload(self.payload), self.report)

    def test_derived_and_unknown_fields_cannot_be_changed(self):
        cases = (
            ("schema", lambda data: data.update(schema_version="wrong")),
            ("mode", lambda data: data["sample"].update(analysis_mode="large")),
            ("sentiment method", lambda data: data["sentiment"].update(method="manual")),
            ("repeated count", lambda data: data["repeated_text_groups"][0].update(occurrence_count=99)),
            ("unknown field", lambda data: data.update(unexpected=True)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                payload = deepcopy(self.payload)
                mutate(payload)
                with self.assertRaises(ValueError):
                    load_report_v2_payload(payload)

    def test_reference_fields_must_remain_arrays(self):
        payload = deepcopy(self.payload)
        payload["topics"][0]["evidence_comment_ids"] = "demo-1"
        with self.assertRaises(ValueError):
            load_report_v2_payload(payload)
