from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from analyses.models import AnalysisJob, AnalysisResult, FetchRun, Video


class AnalysisResultAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="report-admin", email="admin@example.com", password="test-password"
        )
        self.client.force_login(user)
        video = Video.objects.create(youtube_video_id="testvideo01", video_title="測試報告影片")
        job = AnalysisJob.objects.create(video=video)
        fetch_run = FetchRun.objects.create(analysis_job=job, data_source=AnalysisJob.DataSource.YOUTUBE_API)
        self.result = AnalysisResult.objects.create(
            analysis_job=job,
            source_fetch_run=fetch_run,
            provider_name="deepseek",
            model_name="test-model",
            prompt_version="test-prompt",
            schema_version="test-schema",
            analysis_mode=AnalysisResult.AnalysisMode.SMALL,
            analyzed_comment_count=1,
            main_comment_count=1,
            result_data={"overall_summary": "測試摘要 <script>alert(1)</script>"},
        )

    def test_saved_report_is_visible_and_searchable_in_admin(self):
        url = reverse("admin:analyses_analysisresult_changelist")

        response = self.client.get(url, {"q": "測試報告影片"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "測試報告影片")
        self.assertContains(response, "deepseek")

    def test_report_detail_is_read_only_and_escapes_report_text(self):
        url = reverse("admin:analyses_analysisresult_change", args=[self.result.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "結構化報告 JSON")
        self.assertContains(response, "測試摘要")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, 'name="result_data"')
        self.assertEqual(self.client.post(url, {"result_data": "{}"}).status_code, 403)
        self.result.refresh_from_db()
        self.assertIn("測試摘要", self.result.result_data["overall_summary"])

    def test_report_cannot_be_added_or_deleted_in_admin(self):
        add_url = reverse("admin:analyses_analysisresult_add")
        delete_url = reverse("admin:analyses_analysisresult_delete", args=[self.result.pk])

        self.assertEqual(self.client.get(add_url).status_code, 403)
        self.assertEqual(self.client.get(delete_url).status_code, 403)
