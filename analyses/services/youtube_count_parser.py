import re
from decimal import Decimal

YOUTUBE_COUNT_TEXT_PATTERN = re.compile(
    r"(?P<count_number>\d+(?:\.\d+)?)"
    r"\s*"
    r"(?P<count_unit>[千萬万億亿KkMmBb]?)"
)

COUNT_UNIT_MULTIPLIERS = {
    "": 1,
    "千": 1_000,
    "K": 1_000,
    "k": 1_000,
    "萬": 10_000,
    "万": 10_000,
    "M": 1_000_000,
    "m": 1_000_000,
    "億": 100_000_000,
    "亿": 100_000_000,
    "B": 1_000_000_000,
    "b": 1_000_000_000,
}


class InvalidYouTubeCountTextError(ValueError):
    """YouTube 數量文字無法轉換成整數。"""

def convert_youtube_count_text_to_integer( youtube_count_text: str) -> int:
    """將 YouTube 顯示的觀看數或留言數轉成整數。"""

    # 移除中文及英文格式的千分位逗號。
    normalized_count_text = youtube_count_text.replace(",", "").replace("，", "").strip()
    
    count_text_match = YOUTUBE_COUNT_TEXT_PATTERN.search(normalized_count_text)

    if count_text_match is None:
        raise InvalidYouTubeCountTextError(f"無法解析 YouTube 數量文字：{youtube_count_text!r}")

    count_number = Decimal(count_text_match.group("count_number"))
    count_unit = count_text_match.group("count_unit")
    count_multiplier = COUNT_UNIT_MULTIPLIERS[count_unit]

    return int(count_number * count_multiplier)