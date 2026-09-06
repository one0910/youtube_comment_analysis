"""已儲存 v2 報告的離線載入測試，不呼叫 DeepSeek。"""

from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .services.report_v2_artifact_service import load_report_v2_payload
from .services.report_v2_preview_service import build_report_preview_fixture


class ReportV2ArtifactLoaderTests(SimpleTestCase):
    def setUp(self):
        self.report, self.facts = build_report_preview_fixture()
        self.payload = json.loads(json.dumps(asdict(self.report), ensure_ascii=False))

    def test_round_trip_restores_validated_report(self):
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


@override_settings(DEBUG=True)
class ReportV2RealPreviewTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("analyses:report_v2_real_preview")
        self.report, self.facts = build_report_preview_fixture()

    @patch("analyses.report_v2_views.load_real_report_preview")
    def test_real_preview_renders_validated_artifact_without_api_call(self, load_artifact):
        load_artifact.return_value = self.report, self.facts
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_fixture"])
        self.assertContains(response, "新版報告・真實資料預覽")
        self.assertNotContains(response, "模擬資料 · 未呼叫 DeepSeek API")
        self.assertIn("no-store", response["Cache-Control"])

    @patch("analyses.report_v2_views.load_real_report_preview", side_effect=ValueError("invalid"))
    def test_invalid_artifact_is_not_rendered(self, load_artifact):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        load_artifact.assert_called_once_with()

    @override_settings(DEBUG=False)
    @patch("analyses.report_v2_views.load_real_report_preview")
    def test_real_preview_is_disabled_outside_debug(self, load_artifact):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        load_artifact.assert_not_called()
