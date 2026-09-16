import logging
from collections.abc import Iterator
from time import sleep
from urllib.parse import parse_qs, urljoin, urlparse

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from analyses.services.youtube_count_parser import (
    InvalidYouTubeCountTextError,
    convert_youtube_count_text_to_integer,
)

from .selenium_driver_factory import create_local_chrome_driver
from .youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)


VIDEO_INFORMATION_WAIT_SECONDS = 20
COMMENT_REPLY_LOADING_WAIT_SECONDS = 10
YOUTUBE_PLAYABILITY_OK_STATUS = "OK"


VIDEO_TITLE_SELECTOR = 'meta[property="og:title"]'
VIDEO_AUTHOR_SELECTOR = (
    'span[itemprop="author"] '
    'link[itemprop="name"]'
)

VIDEO_LIKE_COUNT_SELECTOR = (
    'div[itemprop="interactionStatistic"] '
    'meta[itemprop="interactionType"][content="https://schema.org/LikeAction"] + '
    'meta[itemprop="userInteractionCount"]'
)

VIDEO_THUMBNAIL_SELECTOR = 'meta[property="og:image"]'
VIDEO_COMMENT_COUNT_SELECTOR = (
    "ytd-comments-header-renderer "
    "#count .count-text"
)

COMMENT_SORT_BUTTON_SELECTOR = "ytd-comments-header-renderer yt-dropdown-menu #label"
COMMENT_SORT_OPTION_SELECTOR = "ytd-comments-header-renderer yt-dropdown-menu #menu a.yt-simple-endpoint"
COMMENT_REPLY_BUTTON_SELECTOR = (
    "#replies #more-replies button, "
    "#replies #more-replies-sub-thread button"
)

COMMENT_REPLY_ELEMENT_SELECTOR = (
    "#replies ytd-comment-view-model#comment, "
    "#replies ytd-comment-renderer#comment"
)

COMMENT_REPLY_CONTINUATION_BUTTON_SELECTOR = (
    "#replies "
    "ytd-continuation-item-renderer.replies-continuation "
    "button"
)

COMMENT_SORT_OPTION_INDEX = {
    YouTubeCommentSortOrder.TOP: 0,
    YouTubeCommentSortOrder.NEWEST: 1,
}

VIDEO_COMMENT_THREAD_SELECTOR = (
    "ytd-comments "
    "ytd-item-section-renderer #contents "
    "> ytd-comment-thread-renderer:not([is-sub-thread])"
)

VIDEO_COMMENT_CONTINUATION_SELECTOR = (
    "ytd-comments "
    "ytd-item-section-renderer #contents "
    "> ytd-continuation-item-renderer"
)

MAIN_COMMENT_SELECTOR = "#comment-container > #comment"

COMMENT_SECTION_SCROLL_ATTEMPTS = 30
COMMENT_SECTION_SCROLL_DISTANCE = 1200
COMMENT_SECTION_SCROLL_DELAY_SECONDS = 0.5
COMMENT_BATCH_LOADING_WAIT_SECONDS = 10
COMMENT_LOADING_MAX_STALLED_ATTEMPTS = 3
COMMENT_REPLY_LOADING_MAX_ATTEMPTS = 2
ELEMENT_CLICK_MAX_ATTEMPTS = 3
ELEMENT_CLICK_RETRY_WAIT_SECONDS = 1


logger = logging.getLogger(__name__)


YOUTUBE_ORIGIN_URL = "https://www.youtube.com"

COMMENT_ELEMENT_DATA_SCRIPT = """
const commentElement = arguments[0];
const getText = (selector) => commentElement.querySelector(selector)?.textContent?.trim() || "";
const getAttribute = (selector, attributeName) => commentElement.querySelector(selector)?.getAttribute(attributeName) || "";
const getCommentText = () => {
    const contentElement = commentElement.querySelector("#content-text");
    if (!contentElement) {return ""}

    const contentClone = contentElement.cloneNode(true);
    contentClone.querySelectorAll("img[alt]").forEach((imageElement) => {
        imageElement.replaceWith(document.createTextNode(imageElement.getAttribute("alt") || ""));
    });
    return contentClone.textContent?.trim() || "";
};

return {
    comment_link_url: getAttribute("#published-time-text a", "href"),
    author_display_name: getText("#author-text span"),
    author_channel_url: getAttribute("#author-text", "href"),
    comment_text: getCommentText(),
    like_count_text: getText("#vote-count-middle"),
    published_time_text: getText("#published-time-text a"),
    is_pinned: commentElement.hasAttribute("pinned")
        || Boolean(commentElement.querySelector("#pinned-comment-badge ytw-pinned-comment-badge-renderer")),
};
"""

ELEMENT_RECEIVES_CLICK_SCRIPT = """
const targetElement = arguments[0];
if (!targetElement?.isConnected) {return false}

const targetRectangle = targetElement.getBoundingClientRect();
if (targetRectangle.width <= 0 || targetRectangle.height <= 0) {return false}

const targetX = Math.min(
    window.innerWidth - 1,
    Math.max(0, targetRectangle.left + targetRectangle.width / 2)
);
const targetY = Math.min(
    window.innerHeight - 1,
    Math.max(0, targetRectangle.top + targetRectangle.height / 2)
);
const topElement = document.elementFromPoint(targetX, targetY);
return topElement === targetElement || targetElement.contains(topElement);
"""

ELEMENT_CLICK_BLOCKER_SCRIPT = """
const targetElement = arguments[0];
const targetRectangle = targetElement.getBoundingClientRect();
const targetX = Math.min(
    window.innerWidth - 1,
    Math.max(0, targetRectangle.left + targetRectangle.width / 2)
);
const targetY = Math.min(
    window.innerHeight - 1,
    Math.max(0, targetRectangle.top + targetRectangle.height / 2)
);
const blockerElement = document.elementFromPoint(targetX, targetY);
if (!blockerElement) {return null}

return {
    tag_name: blockerElement.tagName?.toLowerCase() || "",
    element_id: blockerElement.id || "",
    class_name: String(blockerElement.className || ""),
    role: blockerElement.getAttribute("role") || "",
    aria_label: blockerElement.getAttribute("aria-label") || "",
};
"""


def _click_element_with_retry(
    chrome_driver: WebDriver,
    target_element: WebElement,
    element_description: str,
) -> None:
    """點擊動態頁面元素；被 tooltip 遮擋時等待、重試，最後才使用 JS click。"""

    for attempt_number in range(1, ELEMENT_CLICK_MAX_ATTEMPTS + 1):
        chrome_driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            target_element,
        )

        try:
            target_element.click()
            return
        except ElementClickInterceptedException:
            blocker_data = chrome_driver.execute_script(
                ELEMENT_CLICK_BLOCKER_SCRIPT,
                target_element,
            )
            logger.warning(
                "Selenium 點擊被其他元素遮擋；element=%s attempt=%s/%s blocker=%s",
                element_description,
                attempt_number,
                ELEMENT_CLICK_MAX_ATTEMPTS,
                blocker_data,
            )

            if attempt_number == ELEMENT_CLICK_MAX_ATTEMPTS:
                logger.warning(
                    "Selenium 一般點擊持續被遮擋，改用 JavaScript click；element=%s",
                    element_description,
                )
                chrome_driver.execute_script("arguments[0].click();", target_element)
                return

            try:
                WebDriverWait(
                    chrome_driver,
                    ELEMENT_CLICK_RETRY_WAIT_SECONDS,
                    poll_frequency=0.1,
                ).until(
                    lambda current_driver: bool(
                        current_driver.execute_script(
                            ELEMENT_RECEIVES_CLICK_SCRIPT,
                            target_element,
                        )
                    )
                )
            except TimeoutException:
                # YouTube tooltip 可能因滑鼠仍停在按鈕上而持續顯示；進入下一次重試。
                continue


"""YouTube 留言元素缺少建立 DTO 所需的必要資料。"""
class InvalidYouTubeCommentElementError(ValueError):


  """從留言時間連結的 lc 查詢參數取得穩定留言 ID。"""
def get_youtube_comment_id_from_url(comment_link_url: str) -> str:
    parsed_comment_link_url = urlparse(comment_link_url)
    youtube_comment_ids = parse_qs(parsed_comment_link_url.query).get("lc", [])

    if (not youtube_comment_ids or not youtube_comment_ids[0].strip()):  
        raise InvalidYouTubeCommentElementError("YouTube 留言連結缺少 lc 參數："f"{comment_link_url!r}")

    return youtube_comment_ids[0].strip()


"""將留言按讚文字轉成整數；空白代表尚無按讚。"""
def get_comment_like_count(like_count_text: str) -> int:

    normalized_like_count_text = (like_count_text.strip())

    if not normalized_like_count_text:
        return 0

    return convert_youtube_count_text_to_integer(normalized_like_count_text)

"""把一個已載入的 YouTube 留言元素轉成共用 DTO。"""
def get_youtube_comment_data_from_element(
    chrome_driver: WebDriver,
    comment_element: WebElement,
    youtube_video_id: str,
    parent_youtube_comment_id: str | None = None,
) -> YouTubeCommentData:

    comment_element_data = chrome_driver.execute_script(COMMENT_ELEMENT_DATA_SCRIPT,comment_element)

    if not isinstance(comment_element_data, dict):
        raise InvalidYouTubeCommentElementError("Selenium 無法從 YouTube 留言元素""取得結構化資料。")

    comment_link_url = comment_element_data.get("comment_link_url","").strip()
    author_channel_url = comment_element_data.get("author_channel_url","").strip()
    comment_text = comment_element_data.get("comment_text", "")

    if not isinstance(comment_text, str) or not comment_text.strip():
        raise InvalidYouTubeCommentElementError("YouTube 留言內容為空白或尚未載入。")
    
    if author_channel_url:
        complete_author_channel_url = urljoin(YOUTUBE_ORIGIN_URL, author_channel_url)
        
    else:
        complete_author_channel_url = None

    return YouTubeCommentData(
        youtube_comment_id=get_youtube_comment_id_from_url(comment_link_url),
        youtube_video_id=youtube_video_id,
        parent_youtube_comment_id=parent_youtube_comment_id,
        author_display_name=comment_element_data.get("author_display_name","",).strip() or None,
        author_channel_url=complete_author_channel_url,
        comment_text=comment_text.strip(),
        like_count=get_comment_like_count(comment_element_data.get("like_count_text" ,"",)),
        published_time_text=comment_element_data.get("published_time_text", "").strip() or None,
        is_pinned=bool(comment_element_data.get("is_pinned", False)),
    )


"""取得目前可見留言區中的主留言討論串，排除回覆子討論串與隱藏區域。"""
def get_loaded_main_comment_thread_elements(chrome_driver: WebDriver) -> list[WebElement]:

    return [
        comment_thread_element
        for comment_thread_element in chrome_driver.find_elements(
            By.CSS_SELECTOR,
            VIDEO_COMMENT_THREAD_SELECTOR,
        )
        if comment_thread_element.is_displayed()
    ]


"""依照 DOM 順序輸出已載入的主留言及其回覆。"""
def iter_loaded_main_comment_data(
    chrome_driver: WebDriver,
    youtube_video_id: str,
    maximum_comment_count: int | None = None,
    start_comment_thread_index: int = 0,
    include_replies: bool = False,
) -> Iterator[YouTubeCommentData]:
    

    comment_thread_elements = get_loaded_main_comment_thread_elements(chrome_driver=chrome_driver)[start_comment_thread_index:]
    yielded_comment_count = 0

    for comment_thread_element in comment_thread_elements:
        main_comment_element = comment_thread_element.find_element(By.CSS_SELECTOR, MAIN_COMMENT_SELECTOR)
        main_comment_data = get_youtube_comment_data_from_element(
            chrome_driver=chrome_driver,
            comment_element=main_comment_element,
            youtube_video_id=youtube_video_id,
        )

        yield main_comment_data
        yielded_comment_count += 1
        
        if maximum_comment_count is not None and yielded_comment_count >= maximum_comment_count:
            return

        if not include_replies:
            continue

        replies_expanded = expand_comment_replies(
            chrome_driver=chrome_driver,
            comment_thread_element=comment_thread_element,
        )

        if not replies_expanded:
            continue

        remaining_comment_count = None

        if maximum_comment_count is not None:
            remaining_comment_count = maximum_comment_count - yielded_comment_count

        load_remaining_comment_replies(
            chrome_driver=chrome_driver,
            comment_thread_element=comment_thread_element,
            maximum_reply_count=remaining_comment_count,
        )

        for reply_comment_data in iter_loaded_reply_comment_data(
            chrome_driver=chrome_driver,
            comment_thread_element=comment_thread_element,
            youtube_video_id=youtube_video_id,
            parent_youtube_comment_id=main_comment_data.youtube_comment_id,
            maximum_reply_count=remaining_comment_count,
        ):
            yield reply_comment_data
            yielded_comment_count += 1

            if maximum_comment_count is not None and yielded_comment_count >= maximum_comment_count:
                return

"""捲到留言 continuation，等待下一批主留言載入。"""
def load_next_comment_batch(chrome_driver: WebDriver,previous_comment_thread_count: int) -> bool:

    continuation_elements = chrome_driver.find_elements(By.CSS_SELECTOR,VIDEO_COMMENT_CONTINUATION_SELECTOR)

    visible_continuation = next(
        (continuation_element for continuation_element in continuation_elements
            if continuation_element.is_displayed()
        ),
        None,
    )

    if visible_continuation is None:
        return False

    chrome_driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        visible_continuation,
    )

    try:
        WebDriverWait(chrome_driver,COMMENT_BATCH_LOADING_WAIT_SECONDS).until(
            lambda current_driver: len(get_loaded_main_comment_thread_elements(chrome_driver=current_driver)) > previous_comment_thread_count
        )
    except TimeoutException:
        return False

    return True


"""展開一則主留言的回覆區；沒有回覆按鈕時回傳 False。"""
def expand_comment_replies(chrome_driver: WebDriver,comment_thread_element: WebElement) -> bool:
    reply_buttons = comment_thread_element.find_elements(By.CSS_SELECTOR,COMMENT_REPLY_BUTTON_SELECTOR)

    visible_reply_button = next(
        (reply_button for reply_button in reply_buttons if reply_button.is_displayed()),
        None,
    )

    if visible_reply_button is None:
        return False

    _click_element_with_retry(
        chrome_driver=chrome_driver,
        target_element=visible_reply_button,
        element_description=(
            visible_reply_button.get_attribute("aria-label")
            or "展開留言回覆"
        ),
    )

    for attempt_number in range(1, COMMENT_REPLY_LOADING_MAX_ATTEMPTS + 1):
        try:
            WebDriverWait(chrome_driver, COMMENT_REPLY_LOADING_WAIT_SECONDS).until(
                lambda _: any(
                    reply_element.is_displayed()
                    for reply_element in comment_thread_element.find_elements(
                        By.CSS_SELECTOR,
                        COMMENT_REPLY_ELEMENT_SELECTOR,
                    )
                )
            )
            return True
        except TimeoutException:
            logger.warning(
                "等待留言回覆載入逾時；reply_button=%s attempt=%s/%s",
                visible_reply_button.get_attribute("aria-label") or "展開留言回覆",
                attempt_number,
                COMMENT_REPLY_LOADING_MAX_ATTEMPTS,
            )

    logger.warning("略過未能載入回覆的留言串，繼續抓取其他留言。")
    return False


"""反覆點擊顯示更多回覆，直到全部載入或達到數量上限。"""
def load_remaining_comment_replies(
    chrome_driver: WebDriver,
    comment_thread_element: WebElement,
    maximum_reply_count: int | None = None,
) -> None:

    while True:
        loaded_reply_count = len(comment_thread_element.find_elements(By.CSS_SELECTOR, COMMENT_REPLY_ELEMENT_SELECTOR))

        if maximum_reply_count is not None and loaded_reply_count >= maximum_reply_count:
            return

        continuation_buttons = comment_thread_element.find_elements(By.CSS_SELECTOR, COMMENT_REPLY_CONTINUATION_BUTTON_SELECTOR)
        visible_continuation_button = next((button for button in continuation_buttons if button.is_displayed()), None)

        if visible_continuation_button is None:
            return

        _click_element_with_retry(
            chrome_driver=chrome_driver,
            target_element=visible_continuation_button,
            element_description=(
                visible_continuation_button.get_attribute("aria-label")
                or "載入更多留言回覆"
            ),
        )

        for attempt_number in range(1, COMMENT_REPLY_LOADING_MAX_ATTEMPTS + 1):
            try:
                WebDriverWait(chrome_driver, COMMENT_REPLY_LOADING_WAIT_SECONDS).until(
                    lambda _: len(
                        comment_thread_element.find_elements(
                            By.CSS_SELECTOR,
                            COMMENT_REPLY_ELEMENT_SELECTOR,
                        )
                    ) > loaded_reply_count
                )
                break
            except TimeoutException:
                logger.warning(
                    "等待更多留言回覆載入逾時；loaded_reply_count=%s attempt=%s/%s",
                    loaded_reply_count,
                    attempt_number,
                    COMMENT_REPLY_LOADING_MAX_ATTEMPTS,
                )
        else:
            logger.warning("略過未能繼續載入的回覆，保留已載入內容並繼續抓取其他留言。")
            return


def _find_visible_comment_sort_options(
    chrome_driver: WebDriver,
    target_option_index: int,
) -> list[WebElement] | bool:
    """等到目標排序選項已呈現，避免選單動畫只先顯示第一個選項。"""

    visible_sort_options = [
        option
        for option in chrome_driver.find_elements(
            By.CSS_SELECTOR,
            COMMENT_SORT_OPTION_SELECTOR,
        )
        if option.is_displayed()
    ]
    return (
        visible_sort_options
        if len(visible_sort_options) > target_option_index
        else False
    )


"""逐筆輸出一則主留言目前已載入的回覆留言。"""
def iter_loaded_reply_comment_data(
    chrome_driver: WebDriver,
    comment_thread_element: WebElement,
    youtube_video_id: str,
    parent_youtube_comment_id: str,
    maximum_reply_count: int | None = None,
) -> Iterator[YouTubeCommentData]:

    reply_comment_elements = comment_thread_element.find_elements(By.CSS_SELECTOR, COMMENT_REPLY_ELEMENT_SELECTOR)
    yielded_reply_count = 0

    for reply_comment_element in reply_comment_elements:
        yield get_youtube_comment_data_from_element(
            chrome_driver=chrome_driver,
            comment_element=reply_comment_element,
            youtube_video_id=youtube_video_id,
            parent_youtube_comment_id=parent_youtube_comment_id,
        )

        yielded_reply_count += 1

        if maximum_reply_count is not None and yielded_reply_count >= maximum_reply_count:
            return

"""依照抓取選項切換 YouTube 留言排序。"""
def select_comment_sort_order(
    chrome_driver: WebDriver,
    sort_order: YouTubeCommentSortOrder,
) -> None:

    wait = WebDriverWait(chrome_driver, VIDEO_INFORMATION_WAIT_SECONDS)
    sort_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, COMMENT_SORT_BUTTON_SELECTOR)))

    chrome_driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        sort_button,
    )
    target_option_index = COMMENT_SORT_OPTION_INDEX[sort_order]
    _click_element_with_retry(
        chrome_driver=chrome_driver,
        target_element=sort_button,
        element_description="YouTube 留言排序選單",
    )

    visible_sort_options = wait.until(
        lambda current_driver: _find_visible_comment_sort_options(
            chrome_driver=current_driver,
            target_option_index=target_option_index,
        ),
        message=f"YouTube 留言排序選單尚未顯示索引 {target_option_index}。",
    )

    target_sort_option = visible_sort_options[target_option_index]

    if target_sort_option.get_attribute("aria-selected") == "true":
        _click_element_with_retry(
            chrome_driver=chrome_driver,
            target_element=sort_button,
            element_description="關閉 YouTube 留言排序選單",
        )
        return

    _click_element_with_retry(
        chrome_driver=chrome_driver,
        target_element=target_sort_option,
        element_description=f"YouTube 留言排序選項 {target_option_index}",
    )

    wait.until(
        lambda current_driver: (
            len(current_driver.find_elements(By.CSS_SELECTOR, COMMENT_SORT_OPTION_SELECTOR)) > target_option_index
            and current_driver.find_elements(By.CSS_SELECTOR, COMMENT_SORT_OPTION_SELECTOR)[target_option_index].get_attribute("aria-selected") == "true"
        )
    )
    wait.until(EC.invisibility_of_element(target_sort_option))


"""讀取 YouTube 播放狀態，確認影片是否可以公開存取。"""
def check_youtube_video_is_available(chrome_driver: WebDriver, wait: WebDriverWait) -> None:

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


"""從 YouTube 原生結構化資料取得精確按讚數；未公開時回傳 None。"""
def get_video_like_count(chrome_driver: WebDriver) -> int | None:
    video_like_count_text = chrome_driver.execute_script(
        """
        return document.querySelector(
            'div[itemprop="interactionStatistic"] '
            + 'meta[itemprop="interactionType"][content="https://schema.org/LikeAction"] + '
            + 'meta[itemprop="userInteractionCount"]'
        )?.getAttribute("content") || null;
        """
    )

    if not video_like_count_text:
        return None

    return int(video_like_count_text)


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

    """開啟 YouTube 影片頁面並取得預覽資料。"""
    def get_video_preview(self,youtube_video_id: str) -> YouTubeVideoPreviewData:

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
            video_like_count = get_video_like_count(chrome_driver=chrome_driver)
            video_comment_count = get_video_comment_count(chrome_driver=chrome_driver)

            return YouTubeVideoPreviewData(
                youtube_video_id=youtube_video_id,
                video_title=video_title,
                video_author_name=video_author_name,
                video_thumbnail_url=video_thumbnail_url,
                video_view_count=video_view_count,
                video_like_count=video_like_count,
                video_comment_count=video_comment_count,
            )
        finally:
            # 成功或失敗都必須關閉 Chrome。
            chrome_driver.quit()


    """開啟 YouTube 影片並逐筆輸出目前已載入的主留言。"""
    def get_video_comments(
        self,
        youtube_video_id: str,
        fetch_options: YouTubeCommentFetchOptions,
    ) -> Iterator[YouTubeCommentData]:

        youtube_video_url = f"https://www.youtube.com/watch?v={youtube_video_id}"
        chrome_driver = create_local_chrome_driver(run_in_headless_mode=True)

        try:
            chrome_driver.get(youtube_video_url)
            wait = WebDriverWait(chrome_driver, VIDEO_INFORMATION_WAIT_SECONDS)
            check_youtube_video_is_available(chrome_driver=chrome_driver, wait=wait)
            video_comment_count = get_video_comment_count(chrome_driver=chrome_driver)

            if video_comment_count is None:
                return
            
            select_comment_sort_order(chrome_driver=chrome_driver, sort_order=fetch_options.sort_order)
            target_comment_count = video_comment_count

            if fetch_options.maximum_comment_count is not None:
                target_comment_count = min(video_comment_count, fetch_options.maximum_comment_count)

            yielded_comment_count = 0
            processed_comment_thread_count = 0
            stalled_attempt_count = 0
            seen_youtube_comment_ids: set[str] = set()

            while yielded_comment_count < target_comment_count:
                loaded_comment_thread_count = len(
                    get_loaded_main_comment_thread_elements(chrome_driver=chrome_driver)
                )
                remaining_comment_count = target_comment_count - yielded_comment_count

                # 透過iter_loaded_main_comment_data遍歷主留言及回覆
                for comment_data in iter_loaded_main_comment_data(
                    chrome_driver=chrome_driver,
                    youtube_video_id=youtube_video_id,
                    maximum_comment_count=remaining_comment_count,
                    start_comment_thread_index=processed_comment_thread_count,
                    include_replies=fetch_options.include_replies,
                ):
                    if comment_data.youtube_comment_id in seen_youtube_comment_ids:
                        continue

                    seen_youtube_comment_ids.add(comment_data.youtube_comment_id)
                    yield comment_data
                    yielded_comment_count += 1

                    if yielded_comment_count >= target_comment_count:
                        return

                processed_comment_thread_count = loaded_comment_thread_count

                if yielded_comment_count >= target_comment_count:
                    return

                new_comment_batch_loaded = load_next_comment_batch(
                    chrome_driver=chrome_driver,
                    previous_comment_thread_count=loaded_comment_thread_count,
                )

                if new_comment_batch_loaded:
                    stalled_attempt_count = 0
                    continue

                stalled_attempt_count += 1
                
                if stalled_attempt_count >= COMMENT_LOADING_MAX_STALLED_ATTEMPTS:
                    return
        finally:
            # Iterator 正常結束或中途發生錯誤，都必須關閉 Chrome。
            chrome_driver.quit()
    
