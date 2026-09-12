from datetime import UTC, datetime

from django.test import TestCase
from django.urls import reverse

from ..models import AnalysisJob, AnalysisResult, Comment, CommentSnapshot, FetchRun, Video
from ..providers import ai_report_v2 as v2
from ..services.ai_report_preparation_service import prepare_report_facts
from ..services.analysis_job_creation_service import create_pending_analysis_job_for_video
from ..services.report_v2_artifact_service import load_report_v2_payload
from ..services.report_v2_execution_service import execute_report_v2_analysis
from ..services.report_v2_result_service import ReportV2UnavailableError, load_report_v2_from_result


class FakeReportV2Provider:
    def __init__(self, *, error=None, tokens=(101, 29, 130)):
        self.error = error
        self.tokens = tokens
        self.calls = []

    def analyze_report(self, analysis_request, video, *, sort_order, include_replies, source_label=None):
        self.calls.append({
            "analysis_request": analysis_request,
            "video": video,
            "sort_order": sort_order,
            "include_replies": include_replies,
            "source_label": source_label,
        })
        if self.error:
            raise self.error
        facts = prepare_report_facts(
            analysis_request,
            video,
            sort_order=sort_order,
            include_replies=include_replies,
        )
        prompt_tokens, completion_tokens, total_tokens = self.tokens
        return v2.AIReportV2(
            video=video,
            sample=facts.sample,
            provenance=v2.ReportProvenanceV2(
                "fake", "fake-v2", "test-v2", datetime.now(UTC).isoformat(), source_label,
                prompt_tokens, completion_tokens, total_tokens,
            ),
            overall_summary="測試整體摘要。",
            atmosphere="測試留言氣氛。",
            sentiment=None,
            topics=(v2.ReportTopicV2("測試議題", "測試摘要。", "測試論述。", ("comment-1",)),),
            top_liked_comments=tuple(
                v2.TopLikedCommentV2(
                    item.youtube_comment_id,
                    item.author_display_name,
                    item.comment_text,
                    item.like_count,
                    "測試解讀。",
                )
                for item in facts.top_liked_comments
            ),
            conclusions=(v2.ReportInsightV2("測試結論", "測試結論說明。", ("comment-1",)),),
            limitations=("這是測試報告。",),
        )


class ReportV2ExecutionServiceTests(TestCase):
    def setUp(self):
        video = Video.objects.create(
            youtube_video_id="abcdefghijk",
            video_title="正式 V2 報告測試影片",
            video_author_name="測試頻道",
            video_thumbnail_url="https://example.com/thumb.jpg",
            video_view_count=1234,
            video_like_count=56,
            video_comment_count=1,
        )
        self.job = create_pending_analysis_job_for_video(video_record=video)
        self.fetch_run = self.job.fetch_runs.get()
        comment = Comment.objects.create(
            youtube_comment_id="comment-1",
            video=video,
            author_display_name="@tester",
            comment_text="這是一則測試留言。",
            like_count=7,
        )
        CommentSnapshot.objects.create(
            fetch_run=self.fetch_run,
            comment=comment,
            snapshot_author_display_name="@tester",
            snapshot_comment_text="這是一則測試留言。",
            snapshot_like_count=7,
        )
        self.fetch_run.status = FetchRun.Status.COMPLETED
        self.fetch_run.fetched_comment_count = 1
        self.fetch_run.completed_at = datetime.now(UTC)
        self.fetch_run.save(update_fields=["status", "fetched_comment_count", "completed_at", "updated_at"])

    def test_valid_report_is_saved_and_job_is_completed(self):
        provider = FakeReportV2Provider()

        result = execute_report_v2_analysis(fetch_run=self.fetch_run, provider=provider)

        self.job.refresh_from_db()
        self.assertEqual(AnalysisResult.objects.count(), 1)
        self.assertEqual(result.schema_version, v2.REPORT_SCHEMA_VERSION)
        self.assertEqual(result.analysis_mode, AnalysisResult.AnalysisMode.SMALL)
        self.assertEqual(result.analyzed_comment_count, 1)
        self.assertEqual((result.prompt_tokens, result.completion_tokens, result.total_tokens), (101, 29, 130))
        restored_report = load_report_v2_payload(result.result_data)
        self.assertEqual(restored_report.video, provider.calls[0]["video"])
        self.assertEqual(restored_report.schema_version, v2.REPORT_SCHEMA_VERSION)
        self.assertEqual(self.job.status, AnalysisJob.Status.COMPLETED)
        self.assertEqual(self.job.current_stage, AnalysisJob.Stage.REPORT_GENERATION)
        self.assertEqual(self.job.progress_percentage, 100)
        self.assertIsNotNone(self.job.completed_at)

    def test_persisted_fetch_options_are_passed_to_provider(self):
        self.fetch_run.sort_order = FetchRun.SortOrder.TOP
        self.fetch_run.include_replies = True
        self.fetch_run.save(update_fields=["sort_order", "include_replies", "updated_at"])
        provider = FakeReportV2Provider()

        execute_report_v2_analysis(fetch_run=self.fetch_run, provider=provider)

        self.assertEqual(provider.calls[0]["sort_order"], "top")
        self.assertTrue(provider.calls[0]["include_replies"])
        self.assertIn(str(self.fetch_run.id), provider.calls[0]["source_label"])

    def test_missing_usage_remains_unknown_instead_of_zero(self):
        result = execute_report_v2_analysis(
            fetch_run=self.fetch_run,
            provider=FakeReportV2Provider(tokens=(None, None, None)),
        )

        self.assertIsNone(result.prompt_tokens)
        self.assertIsNone(result.completion_tokens)
        self.assertIsNone(result.total_tokens)

    def test_saved_result_renders_the_official_report_page(self):
        result = execute_report_v2_analysis(fetch_run=self.fetch_run, provider=FakeReportV2Provider())

        response = self.client.get(reverse("analyses:analysis_report_detail", args=[self.job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "analyses/report_v2.html")
        self.assertEqual(response.context["report"], load_report_v2_payload(result.result_data))
        self.assertContains(response, "影片分析報告 | TubeSense AI")
        self.assertContains(response, 'data-testid="desktop-report-nav"')

    def test_result_loader_rejects_tampered_index_metadata(self):
        result = execute_report_v2_analysis(fetch_run=self.fetch_run, provider=FakeReportV2Provider())
        AnalysisResult.objects.filter(pk=result.pk).update(model_name="tampered-model")
        result.refresh_from_db()

        with self.assertRaisesRegex(ReportV2UnavailableError, "索引欄位"):
            load_report_v2_from_result(result)

    def test_provider_failure_marks_job_failed_without_saving_result(self):
        with self.assertRaisesRegex(RuntimeError, "模擬 DeepSeek 失敗"):
            execute_report_v2_analysis(
                fetch_run=self.fetch_run,
                provider=FakeReportV2Provider(error=RuntimeError("模擬 DeepSeek 失敗")),
            )

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(self.job.current_stage, AnalysisJob.Stage.AI_ANALYSIS)
        self.assertEqual(self.job.error_message, "模擬 DeepSeek 失敗")
        self.assertFalse(self.job.analysis_results.exists())

    def test_incomplete_fetch_is_rejected_before_provider_call(self):
        self.fetch_run.status = FetchRun.Status.RUNNING
        self.fetch_run.save(update_fields=["status", "updated_at"])
        provider = FakeReportV2Provider()

        with self.assertRaisesRegex(ValueError, "已完成"):
            execute_report_v2_analysis(fetch_run=self.fetch_run, provider=provider)

        self.assertEqual(provider.calls, [])

    def test_completed_fetch_without_comments_marks_job_failed(self):
        CommentSnapshot.objects.filter(fetch_run=self.fetch_run).delete()
        provider = FakeReportV2Provider()

        with self.assertRaisesRegex(ValueError, "找不到"):
            execute_report_v2_analysis(fetch_run=self.fetch_run, provider=provider)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.Status.FAILED)
        self.assertIn("找不到", self.job.error_message)
        self.assertEqual(provider.calls, [])
