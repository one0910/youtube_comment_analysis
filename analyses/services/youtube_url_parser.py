import re
from urllib.parse import parse_qs, urlparse


YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}

YOUTUBE_SHORT_LINK_HOSTS = {
    "youtu.be",
    "www.youtu.be",
}


class InvalidYouTubeUrlError(ValueError):
    """輸入內容不是系統支援的 YouTube 影片網址。"""

"""從YouTube 網址中取得 11 碼影片 ID。"""
def get_video_id_from_youtube_url(input_video_url: str) -> str:
    
    parsed_url = urlparse(input_video_url.strip())
    url_scheme = parsed_url.scheme.lower()
    url_hostname = (parsed_url.hostname or "").lower().rstrip(".")
    url_path_parts = [
        path_part
        for path_part in parsed_url.path.split("/")
        if path_part
    ]

    if url_scheme not in {"http", "https"}:
        raise InvalidYouTubeUrlError("網址必須使用 HTTP 或 HTTPS。")

    video_id = None

    if url_hostname in YOUTUBE_SHORT_LINK_HOSTS:
        if len(url_path_parts) == 1:
            video_id = url_path_parts[0]

    elif url_hostname in YOUTUBE_HOSTS:
        if url_path_parts == ["watch"]:
            video_id_candidates = parse_qs(parsed_url.query).get("v", [])

            if video_id_candidates:
                video_id = video_id_candidates[0]

        elif (len(url_path_parts) == 2 and url_path_parts[0] in {"shorts", "live"}):
            video_id = url_path_parts[1]

    if (video_id is None or YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id) is None):
        raise InvalidYouTubeUrlError("無法從網址取得有效的 YouTube 影片 ID。")

    return video_id