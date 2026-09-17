from django.conf import settings

from analyses.models import AnalysisJob
from analyses.providers.selenium.youtube_provider import SeleniumYouTubeProvider
from analyses.providers.youtube_data_api.youtube_provider import YouTubeDataAPIProvider
from analyses.providers.youtube_provider import YouTubeProvider


class YouTubeProviderUnavailableError(ValueError):
    """指定的 YouTube Provider 目前無法使用。"""


def get_configured_youtube_data_source() -> str:
    return settings.YOUTUBE_DATA_SOURCE


def create_youtube_provider(data_source: str) -> YouTubeProvider:
    if data_source == AnalysisJob.DataSource.SELENIUM:
        return SeleniumYouTubeProvider()
    if data_source == AnalysisJob.DataSource.YOUTUBE_API:
        return YouTubeDataAPIProvider()
    raise YouTubeProviderUnavailableError(f"不支援的 YouTube 資料來源：{data_source}")
