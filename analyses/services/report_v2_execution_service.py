from dataclasses import asdict
import json
from typing import Protocol
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from analyses.models import AnalysisJob, AnalysisResult, FetchRun
from analyses.providers.ai_analysis_provider import AIAnalysisRequest
from analyses.providers.ai_report_v2 import AIReportV2, REPORT_SCHEMA_VERSION, ReportVideoV2
from analyses.providers.deepseek_report_v2_provider import DeepSeekReportV2Provider

from .ai_analysis_request_service import build_ai_analysis_request_from_fetch_run
from .ai_report_preparation_service import prepare_report_facts, validate_report_source_facts


class ReportV2Provider(Protocol):
    def analyze_report(
        self,
        analysis_request: AIAnalysisRequest,
        video: ReportVideoV2,
        *,
        sort_order: str,
        include_replies: bool,
        source_label: str | None = None,
    ) -> AIReportV2: ...


def execute_report_v2_analysis(fetch_run: FetchRun, provider: ReportV2Provider) -> AnalysisResult:
    """建立、驗證並保存正式 V2 報告。"""
    if fetch_run.status != FetchRun.Status.COMPLETED:
        build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
    analysis_job = fetch_run.analysis_job

    analysis_job.status = AnalysisJob.Status.RUNNING
    analysis_job.current_stage = AnalysisJob.Stage.AI_ANALYSIS
    analysis_job.progress_percentage = 75
    analysis_job.completed_at = None
    analysis_job.error_message = ""
    analysis_job.save(update_fields=[
        "status", "current_stage", "progress_percentage", "completed_at", "error_message", "updated_at",
    ])

    try:
        analysis_request = build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
        report_video = build_report_video_from_fetch_run(fetch_run=fetch_run)
        report = provider.analyze_report(
            analysis_request,
            report_video,
            sort_order=fetch_run.sort_order,
            include_replies=fetch_run.include_replies,
            source_label=f"analysis-job:{analysis_job.id}/fetch-run:{fetch_run.id}",
        )
        facts = prepare_report_facts(
            analysis_request,
            report_video,
            sort_order=fetch_run.sort_order,
            include_replies=fetch_run.include_replies,
        )
        validate_report_source_facts(report, facts)
        return _save_report_v2_result(fetch_run=fetch_run, report=report)
    except Exception as error:
        mark_report_v2_analysis_failed(analysis_job=analysis_job, error=error)
        raise


def execute_report_v2_analysis_by_id(
    fetch_run_id: UUID | str,
    provider: ReportV2Provider | None = None,
) -> AnalysisResult:
    fetch_run = FetchRun.objects.select_related("analysis_job", "analysis_job__video").get(pk=fetch_run_id)
    return execute_report_v2_analysis(fetch_run=fetch_run, provider=provider or DeepSeekReportV2Provider())


def build_report_video_from_fetch_run(fetch_run: FetchRun) -> ReportVideoV2:
    """把資料庫中的影片資料轉成會永久保存於報告內的快照。"""
    video = fetch_run.analysis_job.video
    captured_at = fetch_run.completed_at or timezone.now()
    return ReportVideoV2(
        youtube_video_id=video.youtube_video_id,
        title=video.video_title,
        channel_name=video.video_author_name or None,
        thumbnail_url=video.video_thumbnail_url or None,
        view_count=video.video_view_count,
        like_count=video.video_like_count,
        displayed_comment_count=video.video_comment_count,
        captured_at=captured_at.isoformat(),
    )


@transaction.atomic
def _save_report_v2_result(fetch_run: FetchRun, report: AIReportV2) -> AnalysisResult:
    analysis_job = AnalysisJob.objects.select_for_update().get(pk=fetch_run.analysis_job_id)
    latest_attempt = analysis_job.analysis_results.aggregate(number=Max("attempt_number"))["number"] or 0
    provenance = report.provenance
    result = AnalysisResult(
        analysis_job=analysis_job,
        source_fetch_run=fetch_run,
        attempt_number=latest_attempt + 1,
        provider_name=provenance.provider_name,
        model_name=provenance.model_name,
        prompt_version=provenance.prompt_version,
        schema_version=REPORT_SCHEMA_VERSION,
        analysis_mode=report.sample.analysis_mode.value,
        analyzed_comment_count=report.sample.analyzed_comment_count,
        top_level_comment_count=report.sample.top_level_comment_count,
        reply_comment_count=report.sample.reply_comment_count,
        result_data=json.loads(json.dumps(asdict(report), ensure_ascii=False)),
        prompt_tokens=provenance.prompt_tokens,
        completion_tokens=provenance.completion_tokens,
        total_tokens=provenance.total_tokens,
    )
    result.full_clean()
    result.save()

    analysis_job.status = AnalysisJob.Status.COMPLETED
    analysis_job.current_stage = AnalysisJob.Stage.REPORT_GENERATION
    analysis_job.progress_percentage = 100
    analysis_job.completed_at = timezone.now()
    analysis_job.error_message = ""
    analysis_job.save(update_fields=[
        "status", "current_stage", "progress_percentage", "completed_at", "error_message", "updated_at",
    ])
    return result


def mark_report_v2_analysis_failed(analysis_job: AnalysisJob, error: Exception) -> None:
    analysis_job.status = AnalysisJob.Status.FAILED
    analysis_job.current_stage = AnalysisJob.Stage.AI_ANALYSIS
    analysis_job.completed_at = timezone.now()
    analysis_job.error_message = str(error)
    analysis_job.save(update_fields=["status", "current_stage", "completed_at", "error_message", "updated_at"])


def mark_report_v2_dispatch_failed(fetch_run_id: UUID | str, error: Exception) -> None:
    fetch_run = FetchRun.objects.select_related("analysis_job").get(pk=fetch_run_id)
    mark_report_v2_analysis_failed(analysis_job=fetch_run.analysis_job, error=error)
