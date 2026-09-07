from analyses.models import AnalysisJob, AnalysisResult
from analyses.providers.ai_analysis_provider import AIAnalysisRequest
from analyses.providers.ai_report_v2 import AIReportV2, REPORT_SCHEMA_VERSION

from .ai_analysis_request_service import build_ai_analysis_request_from_fetch_run
from .ai_report_preparation_service import PreparedReportFacts, prepare_report_facts, validate_report_source_facts
from .report_v2_artifact_service import load_report_v2_payload


class ReportV2UnavailableError(ValueError):
    """任務尚無可驗證的正式 V2 報告。"""


def load_latest_report_v2_for_job(analysis_job: AnalysisJob) -> tuple[AIReportV2, PreparedReportFacts]:
    result = (
        analysis_job.analysis_results
        .filter(schema_version=REPORT_SCHEMA_VERSION)
        .select_related("source_fetch_run", "source_fetch_run__analysis_job", "source_fetch_run__analysis_job__video")
        .order_by("-attempt_number")
        .first()
    )
    if result is None:
        raise ReportV2UnavailableError("此分析任務尚無 V2 報告。")
    return load_report_v2_from_result(result)


def load_report_v2_from_result(result: AnalysisResult) -> tuple[AIReportV2, PreparedReportFacts]:
    """從資料庫還原報告，並重新核對欄位、抓取設定及留言來源。"""
    try:
        report = load_report_v2_payload(result.result_data)
        _validate_result_metadata(result=result, report=report)
        fetch_run = result.source_fetch_run
        if result.analysis_job_id != fetch_run.analysis_job_id:
            raise ReportV2UnavailableError("報告與來源抓取紀錄不屬於同一個分析任務。")
        if report.video.youtube_video_id != fetch_run.analysis_job.video.youtube_video_id:
            raise ReportV2UnavailableError("報告影片與來源抓取紀錄不一致。")
        if fetch_run.sort_order != report.sample.sort_order or fetch_run.include_replies != report.sample.include_replies:
            raise ReportV2UnavailableError("報告樣本設定與來源抓取紀錄不一致。")
        stored_request = build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
        analysis_request = AIAnalysisRequest(
            youtube_video_id=report.video.youtube_video_id,
            video_title=report.video.title,
            comments=stored_request.comments,
        )
        facts = prepare_report_facts(
            analysis_request,
            report.video,
            sort_order=fetch_run.sort_order,
            include_replies=fetch_run.include_replies,
        )
        validate_report_source_facts(report, facts)
        return report, facts
    except ReportV2UnavailableError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ReportV2UnavailableError("資料庫中的 V2 報告無法通過來源驗證。") from error


def _validate_result_metadata(result: AnalysisResult, report: AIReportV2) -> None:
    provenance = report.provenance
    sample = report.sample
    stored = (
        result.schema_version,
        result.provider_name,
        result.model_name,
        result.prompt_version,
        result.analysis_mode,
        result.analyzed_comment_count,
        result.top_level_comment_count,
        result.reply_comment_count,
        result.prompt_tokens,
        result.completion_tokens,
        result.total_tokens,
    )
    expected = (
        report.schema_version,
        provenance.provider_name,
        provenance.model_name,
        provenance.prompt_version,
        sample.analysis_mode.value,
        sample.analyzed_comment_count,
        sample.top_level_comment_count,
        sample.reply_comment_count,
        provenance.prompt_tokens,
        provenance.completion_tokens,
        provenance.total_tokens,
    )
    if stored != expected:
        raise ReportV2UnavailableError("V2 報告欄位與資料庫索引欄位不一致。")
