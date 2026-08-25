from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _


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