from analyses.models import Video
from analyses.providers.youtube_provider import (
    YouTubeVideoPreviewData,
)


def save_or_update_video_from_preview_data(video_preview_data: YouTubeVideoPreviewData) -> Video:
    """將 YouTube 預覽資料新增或更新到 Video 資料表。"""

    video_record, _ = Video.objects.update_or_create(
        # 使用 YouTube 影片 ID 判斷是不是同一支影片。
        youtube_video_id=video_preview_data.youtube_video_id,
        defaults={
            "video_title": video_preview_data.video_title,

            # Provider 可能取不到作者與縮圖，Model 以空字串保存。
            "video_author_name": video_preview_data.video_author_name or "",
            "video_thumbnail_url": video_preview_data.video_thumbnail_url or "",
            
            # 觀看數和留言數允許使用 None，表示目前無法取得。
            "video_view_count": video_preview_data.video_view_count,
            "video_like_count": video_preview_data.video_like_count,
            
            "video_comment_count": video_preview_data.video_comment_count
        },
    )

    return video_record