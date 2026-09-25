from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from analyses.models import AnalysisJob, AnalysisResult, Comment, CommentSnapshot, FetchRun, Video


class AnalysisResultAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="report-admin", email="admin@example.com", password="test-password"
        )
        self.client.force_login(user)
        self.video = Video.objects.create(youtube_video_id="testvideo01", video_title="測試報告影片")
        self.job = AnalysisJob.objects.create(video=self.video)
        self.fetch_run = FetchRun.objects.create(
            analysis_job=self.job, data_source=AnalysisJob.DataSource.YOUTUBE_API
        )
        self.comment = Comment.objects.create(
            video=self.video, youtube_comment_id="test-comment-01", comment_text="測試留言"
        )
        self.snapshot = CommentSnapshot.objects.create(
            fetch_run=self.fetch_run, comment=self.comment, snapshot_comment_text="測試留言"
        )
        self.result = AnalysisResult.objects.create(
            analysis_job=self.job,
            source_fetch_run=self.fetch_run,
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

    def test_deleting_video_cascades_to_job_comments_snapshots_and_report(self):
        url = reverse("admin:analyses_video_changelist")
        selection = {"action": "delete_selected", "_selected_action": [str(self.video.pk)]}

        preview = self.client.post(url, selection)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "AI 分析結果")
        self.assertNotContains(preview, "無法刪除")

        confirmed = self.client.post(url, {**selection, "post": "yes"})
        self.assertEqual(confirmed.status_code, 302)
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
        self.assertFalse(AnalysisJob.objects.filter(pk=self.job.pk).exists())
        self.assertFalse(FetchRun.objects.filter(pk=self.fetch_run.pk).exists())
        self.assertFalse(Comment.objects.filter(pk=self.comment.pk).exists())
        self.assertFalse(CommentSnapshot.objects.filter(pk=self.snapshot.pk).exists())
        self.assertFalse(AnalysisResult.objects.filter(pk=self.result.pk).exists())

    def test_deleting_job_cascades_to_fetch_run_snapshot_and_report_but_keeps_video_comment(self):
        url = reverse("admin:analyses_analysisjob_changelist")
        selection = {"action": "delete_selected", "_selected_action": [str(self.job.pk)]}

        preview = self.client.post(url, selection)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "AI 分析結果")
        self.assertNotContains(preview, "無法刪除")

        confirmed = self.client.post(url, {**selection, "post": "yes"})
        self.assertEqual(confirmed.status_code, 302)
        self.assertTrue(Video.objects.filter(pk=self.video.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())
        self.assertFalse(AnalysisJob.objects.filter(pk=self.job.pk).exists())
        self.assertFalse(FetchRun.objects.filter(pk=self.fetch_run.pk).exists())
        self.assertFalse(CommentSnapshot.objects.filter(pk=self.snapshot.pk).exists())
        self.assertFalse(AnalysisResult.objects.filter(pk=self.result.pk).exists())

    def test_single_video_delete_is_allowed_with_related_report(self):
        url = reverse("admin:analyses_video_delete", args=[self.video.pk])

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertNotContains(preview, "無法刪除")

        confirmed = self.client.post(url, {"post": "yes"})
        self.assertEqual(confirmed.status_code, 302)
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
        self.assertFalse(AnalysisResult.objects.filter(pk=self.result.pk).exists())

    def test_single_job_delete_is_allowed_with_related_report(self):
        url = reverse("admin:analyses_analysisjob_delete", args=[self.job.pk])

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertNotContains(preview, "無法刪除")

        confirmed = self.client.post(url, {"post": "yes"})
        self.assertEqual(confirmed.status_code, 302)
        self.assertTrue(Video.objects.filter(pk=self.video.pk).exists())
        self.assertFalse(AnalysisJob.objects.filter(pk=self.job.pk).exists())
        self.assertFalse(AnalysisResult.objects.filter(pk=self.result.pk).exists())
