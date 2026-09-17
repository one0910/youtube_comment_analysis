from datetime import UTC, datetime
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.apps import apps
from django.db import connection
from types import SimpleNamespace
from django.urls import reverse

from ..models import AnalysisJob, AnalysisResult, Comment, CommentSnapshot, FetchRun, Video
from ..providers import ai_report as report_types
from ..services.ai.report_preparation import create_validation_criteria
from ..services.analysis_job_creation_service import create_pending_analysis_job_for_video
from ..services.ai.report_artifact import load_report_payload
from ..services.ai.report_execution import execute_report_analysis
from ..services.ai.report_result import ReportUnavailableError, load_report_from_result


class FakeReportProvider:
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
        facts = create_validation_criteria(
            analysis_request,
            video,
            sort_order=sort_order,
            include_replies=include_replies,
        )
        prompt_tokens, completion_tokens, total_tokens = self.tokens
        return report_types.AIReport(
            video=video,
            sample=facts.sample,
            provenance=report_types.ReportProvenance(
                "fake", "fake", "test", datetime.now(UTC).isoformat(), source_label,
                prompt_tokens, completion_tokens, total_tokens,
            ),
            overall_summary="測試整體摘要。",
            atmosphere="測試留言氣氛。",
            sentiment=None,
            topics=(report_types.ReportTopic("測試議題", "測試摘要。", "測試論述。", ("comment-1",)),),
            top_liked_comments=tuple(
                report_types.TopLikedComment(
                    item.youtube_comment_id,
                    item.author_display_name,
                    item.comment_text,
                    item.like_count,
                    "測試解讀。",
                )
                for item in facts.top_liked_comments
            ),
            conclusions=(report_types.ReportInsight("測試結論", "測試結論說明。", ("comment-1",)),),
            limitations=("這是測試報告。",),
        )


class ReportExecutionServiceTests(TestCase):
    def setUp(self):
        video = Video.objects.create(
            youtube_video_id="abcdefghijk",
            video_title="正式 報告測試影片",
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

    def test_main_comment_migration_preserves_report_payload(self):
        result = execute_report_analysis(
            fetch_run_id=self.fetch_run.id, provider=FakeReportProvider(),
        )
        expected = result.result_data
        migration = import_module("analyses.migrations.0013_main_comment")
        schema_editor = SimpleNamespace(connection=connection)

        migration.backwards(apps, schema_editor)
        result.refresh_from_db()
        self.assertEqual(result.result_data["sample"]["top_level_comment_count"], 1)
        self.assertNotIn("main_comment_count", result.result_data["sample"])

        migration.forwards(apps, schema_editor)
        result.refresh_from_db()
        self.assertEqual(result.result_data, expected)
        report, _ = load_report_from_result(result)
        self.assertEqual(report.sample.main_comment_count, 1)

    def test_string_id_uses_default_provider(self):
        provider = FakeReportProvider()
        with patch(
            "analyses.services.ai.report_execution.DeepSeekReportProvider",
            return_value=provider,
        ) as provider_factory:
            result = execute_report_analysis(fetch_run_id=str(self.fetch_run.id))

        provider_factory.assert_called_once_with()
        self.assertEqual(result.source_fetch_run_id, self.fetch_run.id)
        self.assertEqual(len(provider.calls), 1)

    def test_report_schema_migration_preserves_report(self):
        result = execute_report_analysis(
            fetch_run_id=self.fetch_run.id, provider=FakeReportProvider(),
        )
        expected = result.result_data
        migration = import_module("analyses.migrations.0014_report_names")
        editor = SimpleNamespace(connection=connection)
        migration.backwards(apps, editor)
        result.refresh_from_db()
        self.assertNotEqual(result.schema_version, report_types.REPORT_SCHEMA_VERSION)
        migration.forwards(apps, editor)
        result.refresh_from_db()
        self.assertEqual(result.result_data, expected)
        report, _ = load_report_from_result(result)
        self.assertEqual(report.schema_version, report_types.REPORT_SCHEMA_VERSION)

    def test_queued_legacy_task_uses_renamed_service(self):
        from ..tasks import legacy_report_analysis_task
        from config.celery import app

        app.finalize()
        self.assertIn(legacy_report_analysis_task.name, app.tasks)
        with patch("analyses.tasks.execute_report_analysis") as execute:
            execute.return_value = SimpleNamespace(id="report-id")
            self.assertEqual(legacy_report_analysis_task.run(fetch_run_id="fetch-id"), "report-id")
            execute.assert_called_once_with(fetch_run_id="fetch-id")

    def test_missing_fetch_run_does_not_call_provider(self):
        provider = FakeReportProvider()
        with self.assertRaises(FetchRun.DoesNotExist):
            execute_report_analysis(fetch_run_id=uuid4(), provider=provider)
        self.assertEqual(provider.calls, [])
        self.assertFalse(AnalysisResult.objects.exists())

    def test_valid_report_is_saved_and_job_is_completed(self):
        provider = FakeReportProvider()

        result = execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=provider)

        self.job.refresh_from_db()
        self.assertEqual(AnalysisResult.objects.count(), 1)
        self.assertEqual(result.schema_version, report_types.REPORT_SCHEMA_VERSION)
        self.assertEqual(result.analysis_mode, AnalysisResult.AnalysisMode.SMALL)
        self.assertEqual(result.analyzed_comment_count, 1)
        self.assertEqual((result.prompt_tokens, result.completion_tokens, result.total_tokens), (101, 29, 130))
        restored_report = load_report_payload(result.result_data)
        self.assertEqual(restored_report.video, provider.calls[0]["video"])
        self.assertEqual(restored_report.schema_version, report_types.REPORT_SCHEMA_VERSION)
        self.assertEqual(self.job.status, AnalysisJob.Status.COMPLETED)
        self.assertEqual(self.job.current_stage, AnalysisJob.Stage.REPORT_GENERATION)
        self.assertEqual(self.job.progress_percentage, 100)
        self.assertIsNotNone(self.job.completed_at)

    def test_persisted_fetch_options_are_passed_to_provider(self):
        self.fetch_run.sort_order = FetchRun.SortOrder.TOP
        self.fetch_run.include_replies = True
        self.fetch_run.save(update_fields=["sort_order", "include_replies", "updated_at"])
        provider = FakeReportProvider()

        execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=provider)

        self.assertEqual(provider.calls[0]["sort_order"], "top")
        self.assertTrue(provider.calls[0]["include_replies"])
        self.assertIn(str(self.fetch_run.id), provider.calls[0]["source_label"])

    def test_missing_usage_remains_unknown_instead_of_zero(self):
        result = execute_report_analysis(
            fetch_run_id=self.fetch_run.id,
            provider=FakeReportProvider(tokens=(None, None, None)),
        )

        self.assertIsNone(result.prompt_tokens)
        self.assertIsNone(result.completion_tokens)
        self.assertIsNone(result.total_tokens)

    def test_saved_result_renders_the_official_report_page(self):
        result = execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=FakeReportProvider())

        response = self.client.get(reverse("analyses:analysis_report_detail", args=[self.job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "analyses/report.html")
        self.assertEqual(response.context["report"], load_report_payload(result.result_data))
        self.assertContains(response, "影片分析報告 | TubeSense AI")
        self.assertContains(response, 'data-testid="desktop-report-nav"')

    def test_result_loader_rejects_tampered_index_metadata(self):
        result = execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=FakeReportProvider())
        AnalysisResult.objects.filter(pk=result.pk).update(model_name="tampered-model")
        result.refresh_from_db()

        with self.assertRaisesRegex(ReportUnavailableError, "索引欄位"):
            load_report_from_result(result)

    def test_provider_failure_marks_job_failed_without_saving_result(self):
        with self.assertRaisesRegex(RuntimeError, "模擬 DeepSeek 失敗"):
            execute_report_analysis(
                fetch_run_id=self.fetch_run.id,
                provider=FakeReportProvider(error=RuntimeError("模擬 DeepSeek 失敗")),
            )

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(self.job.current_stage, AnalysisJob.Stage.AI_ANALYSIS)
        self.assertEqual(self.job.error_message, "模擬 DeepSeek 失敗")
        self.assertFalse(self.job.analysis_results.exists())

    def test_incomplete_fetch_is_rejected_before_provider_call(self):
        self.fetch_run.status = FetchRun.Status.RUNNING
        self.fetch_run.save(update_fields=["status", "updated_at"])
        provider = FakeReportProvider()

        with self.assertRaisesRegex(ValueError, "已完成"):
            execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=provider)

        self.assertEqual(provider.calls, [])

    def test_completed_fetch_without_comments_marks_job_failed(self):
        CommentSnapshot.objects.filter(fetch_run=self.fetch_run).delete()
        provider = FakeReportProvider()

        with self.assertRaisesRegex(ValueError, "找不到"):
            execute_report_analysis(fetch_run_id=self.fetch_run.id, provider=provider)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.Status.FAILED)
        self.assertIn("找不到", self.job.error_message)
        self.assertEqual(provider.calls, [])
