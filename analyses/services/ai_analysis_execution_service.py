from dataclasses import asdict

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from analyses.models import (
    AnalysisJob,
    AnalysisResult,
    FetchRun,
)
from analyses.providers.ai_analysis_provider import (
    AIAnalysisMode,
    AIAnalysisProvider,
    AIAnalysisRequest,
    AIProviderResponse,
)

from .ai_analysis_request_service import (
    build_ai_analysis_request_from_fetch_run,
)


class AIAnalysisResponseValidationError(ValueError):
    """AI 回傳內容不符合本次分析輸入或資料契約。"""


"""執行 AI 分析、驗證結果並保存至資料庫。"""
def execute_ai_analysis(fetch_run: FetchRun, ai_provider: AIAnalysisProvider) -> AnalysisResult:

    analysis_job = fetch_run.analysis_job
    started_at = timezone.now()

    analysis_job.status = AnalysisJob.Status.RUNNING
    analysis_job.current_stage = AnalysisJob.Stage.AI_ANALYSIS
    analysis_job.started_at = (analysis_job.started_at or started_at)
    analysis_job.completed_at = None
    analysis_job.error_message = ""
    analysis_job.save(
        update_fields=[
            "status",
            "current_stage",
            "started_at",
            "completed_at",
            "error_message",
            "updated_at",
        ]
    )

    try:
        analysis_request = build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
        provider_response = ai_provider.analyze_comments(analysis_request=analysis_request)

        _validate_provider_response(analysis_request=analysis_request,provider_response=provider_response)

        analysis_result = _save_analysis_result(
            analysis_job=analysis_job,
            fetch_run=fetch_run,
            provider_response=provider_response,
        )

    except Exception as error:
        _mark_analysis_job_as_failed(analysis_job=analysis_job,error=error)
        raise

    return analysis_result

"""確認 AI 回傳數量、分析模式與證據 ID 都可信。"""
def _validate_provider_response(
    analysis_request: AIAnalysisRequest,
    provider_response: AIProviderResponse,
) -> None:
    report = provider_response.report

    if (
        report.analyzed_comment_count
        != analysis_request.comment_count
        or report.top_level_comment_count
        != analysis_request.top_level_comment_count
        or report.reply_comment_count
        != analysis_request.reply_comment_count
    ):
        raise AIAnalysisResponseValidationError("AI 回傳的留言數量與分析輸入不一致。")

    expected_analysis_mode = _get_analysis_mode(comment_count=analysis_request.comment_count)

    if report.analysis_mode != expected_analysis_mode:
        raise AIAnalysisResponseValidationError("AI 回傳的分析模式與留言數量不一致。")

    input_comment_ids = {comment.youtube_comment_id for comment in analysis_request.comments}

    evidence_comment_ids = set()

    for topic in report.topics:
        evidence_comment_ids.update(topic.evidence_comment_ids)

    for representative_comment in (report.representative_comments):
        evidence_comment_ids.add(representative_comment.youtube_comment_id )

    for repeated_content_finding in (report.repeated_content_findings):
        evidence_comment_ids.update(repeated_content_finding.comment_ids)

    unknown_comment_ids = sorted(evidence_comment_ids - input_comment_ids)

    if unknown_comment_ids:
        raise AIAnalysisResponseValidationError("AI 回傳了不屬於本次輸入的留言 ID："f"{unknown_comment_ids[0]}")


"""依留言數量選擇固定分析模式。"""
def _get_analysis_mode(comment_count: int) -> AIAnalysisMode:

    if comment_count < 30:
        return AIAnalysisMode.SMALL

    if comment_count <= 200:
        return AIAnalysisMode.MEDIUM

    return AIAnalysisMode.LARGE


"""保存已驗證結果並把任務推進到報告階段。"""
@transaction.atomic
def _save_analysis_result(
    analysis_job: AnalysisJob,
    fetch_run: FetchRun,
    provider_response: AIProviderResponse,
) -> AnalysisResult:

    locked_analysis_job = (
        AnalysisJob.objects
        .select_for_update()
        .get(pk=analysis_job.pk)
    )

    latest_attempt_number = (
        locked_analysis_job.analysis_results.aggregate(maximum_attempt_number=Max("attempt_number"))["maximum_attempt_number"] or 0
    )

    report_data = asdict(provider_response.report)

    analysis_result = AnalysisResult(
        analysis_job=locked_analysis_job,
        source_fetch_run=fetch_run,
        attempt_number=latest_attempt_number + 1,
        provider_name=provider_response.provider_name,
        model_name=provider_response.model_name,
        prompt_version=provider_response.prompt_version,
        schema_version="comment-analysis-result-v1",
        analysis_mode=(provider_response.report.analysis_mode.value),
        analyzed_comment_count=(provider_response.report.analyzed_comment_count),
        top_level_comment_count=(provider_response.report.top_level_comment_count),
        reply_comment_count=(provider_response.report.reply_comment_count),
        result_data=report_data,
        prompt_tokens=(provider_response.usage.prompt_tokens),
        completion_tokens=(provider_response.usage.completion_tokens),
        total_tokens=(provider_response.usage.total_tokens),
    )

    analysis_result.full_clean()
    analysis_result.save()

    locked_analysis_job.status = (AnalysisJob.Status.RUNNING)
    locked_analysis_job.current_stage = (AnalysisJob.Stage.REPORT_GENERATION)
    locked_analysis_job.completed_at = None
    locked_analysis_job.error_message = ""
    locked_analysis_job.save(
        update_fields=[
            "status",
            "current_stage",
            "completed_at",
            "error_message",
            "updated_at",
        ]
    )

    return analysis_result


"""保存 AI 分析失敗狀態與可理解的錯誤訊息。"""
def _mark_analysis_job_as_failed(analysis_job: AnalysisJob,error: Exception) -> None:

    analysis_job.status = AnalysisJob.Status.FAILED
    analysis_job.current_stage = (AnalysisJob.Stage.AI_ANALYSIS)
    analysis_job.completed_at = timezone.now()
    analysis_job.error_message = str(error)
    analysis_job.save(
        update_fields=[
            "status",
            "current_stage",
            "completed_at",
            "error_message",
            "updated_at",
        ]
    )
