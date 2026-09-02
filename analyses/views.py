# views.py 決定「要呈現哪些資料」。

from .forms import NewAnalysisForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import require_GET, require_POST
from django.utils.translation import gettext as _
from .models import AnalysisJob, Video
from .services.analysis_job_creation_service import (
    create_pending_analysis_job_for_video,
)
from .services.youtube_video_preview_service import (
    get_video_preview_with_selenium,
)
from .services.youtube_video_storage_service import (
    save_or_update_video_from_preview_data,
)
from .services.analysis_job_progress_service import build_analysis_stage_presentations
from .providers.youtube_provider import (
    YouTubeVideoUnavailableError,
)


def overview(request: HttpRequest) -> HttpResponse:
    """顯示 TubeSense AI 分析總覽。"""
    context = {
        "page_title": _("分析總覽"),
        "overview_stats": [
            {
                "label": _("已分析影片"),
                "value": "0",
                "hint": _("尚無資料"),
            },
            {
                "label": _("已分析留言"),
                "value": "0",
                "hint": _("尚無資料"),
            },
            {
                "label": _("平均正面情緒"),
                "value": "--",
                "hint": _("等待分析"),
            },
            {
                "label": _("待處理任務"),
                "value": "0",
                "hint": _("目前無任務"),
            },
        ],
    }
    return render(request, "analyses/overview.html", context)
  

def new_analysis(request: HttpRequest) -> HttpResponse:
    """顯示新增分析頁面並驗證 YouTube 影片網址。"""
    form = NewAnalysisForm(
        request.POST if request.method == "POST" else None
    )
    validated_input_video_url = None
    youtube_video_id = None
    video_preview_data = None
    video_preview_error = None
    saved_video_record = None

    if request.method == "POST" and form.is_valid(): #執行form.is_valid()時就會呼叫NewAnalysisForm.clean()
        validated_input_video_url = form.cleaned_data["input_video_url"]
        youtube_video_id = form.cleaned_data["youtube_video_id"]
        try:
            video_preview_data = get_video_preview_with_selenium(youtube_video_id=youtube_video_id)

            # Selenium 成功取得影片資料後，將影片新增或更新到 Video 資料表。
            saved_video_record = save_or_update_video_from_preview_data(video_preview_data=video_preview_data)

        except YouTubeVideoUnavailableError:
            # 網址格式正確，但影片不存在、已刪除、私人或無法存取。
            form.add_error("input_video_url", _("無法取得這部 YouTube 影片。"))

            video_preview_error = {
                "error_code": "video_unavailable",
                "error_title": _("找不到影片或影片無法存取"),
                "error_message": _(
                    "無法取得這部影片的公開資訊。"
                    "請確認網址正確，且影片為公開、可觀看狀態。"
                ),
            }

    context = {
        "page_title": _("新增分析"),
        "form": form,
        "validated_input_video_url": validated_input_video_url,
        "youtube_video_id": youtube_video_id,
        "video_preview_data": video_preview_data,
        "saved_video_record": saved_video_record,
        "video_preview_error": video_preview_error,
    }
    # HTMX 只需要表單區域；一般瀏覽器請求仍回傳完整頁面。
    if request.headers.get("HX-Request") == "true":
        return render(request,"analyses/partials/video_check_panel.html", context)

    return render(request,"analyses/new_analysis.html",context)

@require_POST
def start_analysis(
    request: HttpRequest,
    video_id: int,
) -> HttpResponse:
    """收到開始分析請求後，建立一個等待處理的任務。"""

    video_record = get_object_or_404(
        Video,
        id=video_id,
    )

    created_analysis_job = (
        create_pending_analysis_job_for_video(
            video_record=video_record,
        )
    )

    return redirect(
        "analyses:analysis_job_detail",
        analysis_job_id=created_analysis_job.id,
    )


"""顯示指定分析任務目前的狀態。"""
def analysis_job_detail(request: HttpRequest, analysis_job_id) -> HttpResponse:

    analysis_job = get_object_or_404(AnalysisJob.objects.select_related("video"),id=analysis_job_id)
    context = {
        "page_title": _("分析進度"),
        "analysis_job": analysis_job,
        "analysis_stages": build_analysis_stage_presentations(analysis_job=analysis_job),
    }

    return render(request,"analyses/analysis_job_detail.html",context)


"""只回傳指定分析任務的進度區塊。"""
@require_GET
def analysis_job_progress(request: HttpRequest, analysis_job_id) -> HttpResponse:

    analysis_job = get_object_or_404(AnalysisJob.objects.select_related("video"),id=analysis_job_id)
    context = {
        "analysis_job": analysis_job,
        "analysis_stages": build_analysis_stage_presentations(analysis_job=analysis_job),
    }
    return render(request,"analyses/partials/analysis_job_progress_panel.html",context)