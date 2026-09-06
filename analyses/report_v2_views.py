from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .services.report_v2_artifact_service import load_real_report_preview
from .services.report_v2_preview_service import build_report_preview_context, build_report_preview_fixture


@require_GET
@never_cache
def report_v2_preview(request):
    """開發模式限定的固定 UI fixture，不允許指定任意檔案或呼叫 API。"""
    if not settings.DEBUG:
        raise Http404
    sample = request.GET.get("sample", "medium")
    if sample not in ("small", "medium"):
        raise Http404
    report, facts = build_report_preview_fixture(small=sample == "small")
    return render(request, "analyses/report_v2_preview.html", build_report_preview_context(report, facts))


@require_GET
@never_cache
def report_v2_real_preview(request):
    """開發模式限定，顯示已儲存且重新驗證過的真實 API Smoke Test 成品。"""
    if not settings.DEBUG:
        raise Http404
    try:
        report, facts = load_real_report_preview()
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        raise Http404 from None
    context = build_report_preview_context(report, facts, is_fixture=False)
    return render(request, "analyses/report_v2_preview.html", context)
