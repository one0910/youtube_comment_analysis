from django.contrib import admin
from .models import AnalysisJob, Comment, CommentObservation, FetchRun, Video


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


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """設定 YouTube 留言在 Django Admin 裡的顯示方式。"""

    list_display = (
        "id",
        "youtube_comment_id",
        "author_display_name",
        "shortened_comment_text",
        "like_count",
        "is_pinned",
        "published_at",
    )

    list_filter = (
        "is_pinned",
        "published_at",
    )

    search_fields = (
        "youtube_comment_id",
        "author_display_name",
        "author_channel_id",
        "comment_text",
        "video__youtube_video_id",
        "video__video_title",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "video",
        "parent_comment",
    )

    ordering = (
        "-published_at",
        "-created_at",
    )

    @admin.display(description="留言內容")
    def shortened_comment_text(self, comment_record):
        """在列表中顯示單行且截短的留言內容。"""

        single_line_comment_text = comment_record.comment_text.strip().replace("\n", " ")

        return single_line_comment_text[:80]


@admin.register(CommentObservation)
class CommentObservationAdmin(admin.ModelAdmin):
    """設定留言觀察紀錄在 Django Admin 裡的顯示方式。"""

    list_display = (
        "id",
        "fetch_run",
        "comment",
        "observed_author_display_name",
        "observed_like_count",
        "observed_is_pinned",
        "observed_at",
    )

    list_filter = (
        "observed_is_pinned",
        "fetch_run__data_source",
        "fetch_run__status",
        "observed_at",
    )

    search_fields = (
        "comment__youtube_comment_id",
        "comment__author_display_name",
        "comment__comment_text",
        "fetch_run__analysis_job__video__youtube_video_id",
        "fetch_run__analysis_job__video__video_title",
    )

    readonly_fields = (
        "observed_at",
    )

    list_select_related = (
        "fetch_run",
        "comment",
    )

    ordering = (
        "-observed_at",
    )
