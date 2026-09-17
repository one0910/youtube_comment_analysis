from analyses.providers.youtube_provider import (
    YouTubeVideoPreviewData,
)
from .provider_factory import (
    create_youtube_provider,
    get_configured_youtube_data_source,
)




"""使用目前環境設定的 Provider 取得影片預覽資料。"""
def get_youtube_video_preview(youtube_video_id: str) -> YouTubeVideoPreviewData:
    youtube_provider = create_youtube_provider(get_configured_youtube_data_source())
    return youtube_provider.get_video_preview(youtube_video_id=youtube_video_id)
