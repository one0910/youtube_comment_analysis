import uuid

from django.db import models
from django.utils.translation import gettext_lazy


class Video(models.Model):
    """保存已確認過的 YouTube 影片基本資料。"""

    youtube_video_id = models.CharField(
        max_length=11,
        unique=True,
        verbose_name=gettext_lazy("YouTube 影片 ID"),
    )

    video_title = models.CharField(
        max_length=500,
        verbose_name=gettext_lazy("影片標題"),
    )

    video_author_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=gettext_lazy("影片作者"),
    )

    video_thumbnail_url = models.URLField(
        max_length=2048,
        blank=True,
        verbose_name=gettext_lazy("影片縮圖網址"),
    )

    video_view_count = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name=gettext_lazy("觀看數"),
    )

    video_comment_count = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name=gettext_lazy("留言數"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=gettext_lazy("建立時間"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=gettext_lazy("更新時間"),
    )

    class Meta:
        verbose_name = gettext_lazy("影片")
        verbose_name_plural = gettext_lazy("影片")
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        """在 Django Admin 及 Shell 中顯示容易辨識的名稱。"""

        return f"{self.video_title} ({self.youtube_video_id})"


class AnalysisJob(models.Model):
    """保存一個影片留言抓取及 AI 分析任務的執行狀態。"""
    class DataSource(models.TextChoices):
        """這次任務使用哪一種 YouTube 資料來源。"""

        SELENIUM = "selenium", gettext_lazy("Selenium")
        YOUTUBE_API = "youtube_api", gettext_lazy("YouTube API")

    class Status(models.TextChoices):
        """分析任務目前的執行狀態。"""

        PENDING = "pending", gettext_lazy("等待處理")
        RUNNING = "running", gettext_lazy("執行中")
        AWAITING_ANALYSIS = (
            "awaiting_analysis",
            gettext_lazy("等待 AI 分析"),
        )
        COMPLETED = "completed", gettext_lazy("已完成")
        FAILED = "failed", gettext_lazy("執行失敗")
        CANCELLED = "cancelled", gettext_lazy("已取消")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=gettext_lazy("任務 ID"),
    )

    video = models.ForeignKey(
        Video,
        on_delete=models.PROTECT,
        related_name="analysis_jobs",
        verbose_name=gettext_lazy("影片"),
    )

    data_source = models.CharField(
        max_length=20,
        choices=DataSource.choices,
        default=DataSource.SELENIUM,
        verbose_name=gettext_lazy("資料來源"),
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name=gettext_lazy("任務狀態"),
    )

    progress_percentage = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=gettext_lazy("目前進度百分比"),
    )

    error_message = models.TextField(
        blank=True,
        verbose_name=gettext_lazy("錯誤訊息"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=gettext_lazy("建立時間"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=gettext_lazy("更新時間"),
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=gettext_lazy("開始時間"),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=gettext_lazy("完成時間"),
    )

    class Meta:
        verbose_name = gettext_lazy("分析任務")
        verbose_name_plural = gettext_lazy("分析任務")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    progress_percentage__gte=0,
                    progress_percentage__lte=100,
                ),
                name="analysis_job_progress_percentage_range",
            ),
        ]

    def __str__(self) -> str:
        """顯示影片名稱與目前任務狀態。"""
        return (
            f"{self.video.video_title} - "
            f"{self.get_status_display()}"
        )