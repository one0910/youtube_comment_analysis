# views.py 決定「要呈現哪些資料」。

from .forms import NewAnalysisForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from .services.youtube_video_preview_service import (
    get_video_preview_with_selenium,
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

    if request.method == "POST" and form.is_valid(): #執行form.is_valid()時就會呼叫NewAnalysisForm.clean()
        validated_input_video_url = form.cleaned_data["input_video_url"]
        youtube_video_id = form.cleaned_data["youtube_video_id"]
        video_preview_data = (get_video_preview_with_selenium(youtube_video_id=youtube_video_id))

    context = {
        "page_title": _("新增分析"),
        "form": form,
        "validated_input_video_url": validated_input_video_url,
        "youtube_video_id": youtube_video_id,
        "video_preview_data": video_preview_data,
    }
    return render(request, "analyses/new_analysis.html", context)