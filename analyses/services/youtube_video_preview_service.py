from analyses.providers.selenium_youtube_provider import (
    SeleniumYouTubeProvider,
)
from analyses.providers.youtube_provider import (
    YouTubeVideoPreviewData,
)


"""使用 Selenium 取得影片預覽資料。"""
def get_video_preview_with_selenium(youtube_video_id: str) -> YouTubeVideoPreviewData:
    selenium_youtube_provider = SeleniumYouTubeProvider()
    return selenium_youtube_provider.get_video_preview(youtube_video_id=youtube_video_id)