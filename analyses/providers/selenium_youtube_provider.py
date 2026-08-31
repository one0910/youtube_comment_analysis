from time import sleep

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from analyses.services.youtube_count_parser import (
    InvalidYouTubeCountTextError,
    convert_youtube_count_text_to_integer,
)

from .selenium_driver_factory import create_local_chrome_driver
from .youtube_provider import (
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)


VIDEO_INFORMATION_WAIT_SECONDS = 20
YOUTUBE_PLAYABILITY_OK_STATUS = "OK"

VIDEO_TITLE_SELECTOR = 'meta[property="og:title"]'
VIDEO_AUTHOR_SELECTOR = (
    'span[itemprop="author"] '
    'link[itemprop="name"]'
)
VIDEO_THUMBNAIL_SELECTOR = 'meta[property="og:image"]'
VIDEO_COMMENT_COUNT_SELECTOR = (
    "ytd-comments-header-renderer "
    "#count .count-text"
)

COMMENT_SECTION_SCROLL_ATTEMPTS = 30
COMMENT_SECTION_SCROLL_DISTANCE = 1200
COMMENT_SECTION_SCROLL_DELAY_SECONDS = 0.5


def check_youtube_video_is_available(chrome_driver: WebDriver, wait: WebDriverWait) -> None:
    """讀取 YouTube 播放狀態，確認影片是否可以公開存取。"""

    video_playability_data = wait.until(
        lambda current_driver: current_driver.execute_script(
            """
            const playabilityStatus = window.ytInitialPlayerResponse?.playabilityStatus;
            if (!playabilityStatus?.status) {return null}
            return {
                provider_status: playabilityStatus.status,
                provider_reason: playabilityStatus.reason || null,
            };
            """
        )
    )

    provider_status = video_playability_data["provider_status"]
    provider_reason = video_playability_data.get("provider_reason")

    if provider_status != YOUTUBE_PLAYABILITY_OK_STATUS:
        raise YouTubeVideoUnavailableError(provider_status=provider_status,provider_reason=provider_reason)

"""等待指定元素出現，並取得不能為空的 HTML Attribute。"""
def get_required_element_attribute(wait: WebDriverWait,css_selector: str, attribute_name: str) -> str:

    target_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,css_selector)))
    attribute_value = target_element.get_attribute(attribute_name)

    if not attribute_value:
        raise TimeoutException( f"元素 {css_selector!r} 的 "f"{attribute_name!r} 屬性沒有資料。")

    return attribute_value.strip()


"""從 YouTube 已載入的影片資料取得精確觀看數。"""
def get_video_view_count( chrome_driver: WebDriver, wait: WebDriverWait) -> int:

    video_view_count_text = wait.until(
        lambda current_driver: (
            current_driver.execute_script(
                """
                return window.ytInitialPlayerResponse?.videoDetails?.viewCount || null;
                """
            )
        )
    )

    return int(video_view_count_text)


"""捲動到留言區並取得留言總數；找不到時回傳 None。"""
def get_video_comment_count(chrome_driver: WebDriver) -> int | None:

    for _ in range(COMMENT_SECTION_SCROLL_ATTEMPTS):
        comment_count_elements = chrome_driver.find_elements( By.CSS_SELECTOR, VIDEO_COMMENT_COUNT_SELECTOR)

        for comment_count_element in comment_count_elements:
            video_comment_count_text = comment_count_element.text.strip()

            # 元素已經出現，但文字仍是空白，代表資料尚未載入完成。
            if not video_comment_count_text:
                continue

            try:
                return convert_youtube_count_text_to_integer(video_comment_count_text)
            except InvalidYouTubeCountTextError:
                # YouTube 可能先顯示「留言」或「Comments」，
                # 數字會在稍後由 JavaScript 動態填入，因此繼續等待。
                continue

        chrome_driver.execute_script(("window.scrollBy("f"0, {COMMENT_SECTION_SCROLL_DISTANCE}"");") )
        sleep(COMMENT_SECTION_SCROLL_DELAY_SECONDS)

    # 找不到不一定是錯誤，也可能是影片關閉留言。
    return None


class SeleniumYouTubeProvider(YouTubeProvider):
    """使用 Selenium 取得 YouTube 影片資料。"""

    def get_video_preview(self,youtube_video_id: str) -> YouTubeVideoPreviewData:
        """開啟 YouTube 影片頁面並取得預覽資料。"""

        youtube_video_url = ("https://www.youtube.com/watch"f"?v={youtube_video_id}")
        chrome_driver = create_local_chrome_driver(run_in_headless_mode=True)

        try:
            chrome_driver.get(youtube_video_url)
            wait = WebDriverWait(chrome_driver,VIDEO_INFORMATION_WAIT_SECONDS)

            check_youtube_video_is_available(chrome_driver=chrome_driver, wait=wait)

            video_title = get_required_element_attribute(
                wait=wait,
                css_selector=VIDEO_TITLE_SELECTOR,
                attribute_name="content",
            )

            video_author_name = (
                get_required_element_attribute(
                    wait=wait,
                    css_selector=VIDEO_AUTHOR_SELECTOR,
                    attribute_name="content",
                )
            )

            video_thumbnail_url = (
                get_required_element_attribute(
                    wait=wait,
                    css_selector=VIDEO_THUMBNAIL_SELECTOR,
                    attribute_name="content",
                )
            )

            video_view_count = get_video_view_count(chrome_driver=chrome_driver,wait=wait)
            video_comment_count = get_video_comment_count(chrome_driver=chrome_driver)

            return YouTubeVideoPreviewData(
                youtube_video_id=youtube_video_id,
                video_title=video_title,
                video_author_name=video_author_name,
                video_thumbnail_url=video_thumbnail_url,
                video_view_count=video_view_count,
                video_comment_count=video_comment_count,
            )
        finally:
            # 成功或失敗都必須關閉 Chrome。
            chrome_driver.quit()
