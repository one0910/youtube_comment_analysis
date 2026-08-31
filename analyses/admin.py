from django.contrib import admin
from .models import AnalysisJob, FetchRun, Video


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    """設定影片資料在 Django Admin 裡的顯示方式。"""

    list_display = (
        "id",
        "video_title",
        "video_author_name",
        "video_view_count",
        "video_comment_count",
        "updated_at",
    )

    search_fields = (
        "youtube_video_id",
        "video_title",
        "video_author_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = ("-updated_at",)


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    """設定分析任務在 Django Admin 裡的顯示方式。"""

    list_display = (
        "id",
        "video",
        "data_source",
        "status",
        "progress_percentage",
        "created_at",
    )

    list_filter = (
        "data_source",
        "status",
    )

    search_fields = (
        "video__youtube_video_id",
        "video__video_title",
        "video__video_author_name",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    )

    # 查詢任務時一併取得影片，避免每一列各查一次資料庫。
    list_select_related = ("video",)

    ordering = ("-created_at",)

@admin.register(FetchRun)
class FetchRunAdmin(admin.ModelAdmin):
    """設定留言抓取紀錄在 Django Admin 裡的顯示方式。"""

    list_display = (
        "id",
        "analysis_job",
        "data_source",
        "status",
        "attempt_number",
        "fetched_comment_count",
        "created_at",
    )

    list_filter = (
        "data_source",
        "status",
    )

    search_fields = (
        "analysis_job__video__youtube_video_id",
        "analysis_job__video__video_title",
        "analysis_job__video__video_author_name",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    )

    list_select_related = (
        "analysis_job",
        "analysis_job__video",
    )

    ordering = ("-created_at",)
