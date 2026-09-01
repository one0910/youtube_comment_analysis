from django.db import transaction
from django.utils import timezone

from analyses.models import Comment, CommentObservation, FetchRun, Video
from analyses.providers.youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeProvider,
)


class YouTubeCommentVideoMismatchError(ValueError):
    """留言資料與目前分析影片不一致。"""


def fetch_and_store_youtube_comments(
    fetch_run: FetchRun,
    youtube_provider: YouTubeProvider,
    fetch_options: YouTubeCommentFetchOptions | None = None,
) -> int:
    """從 Provider 逐筆取得留言並保存至資料庫。"""

    if fetch_options is None:
        fetch_options = YouTubeCommentFetchOptions()

    video_record = fetch_run.analysis_job.video
    observed_youtube_comment_ids: set[str] = set()

    try:
        comment_data_iterator = youtube_provider.iter_video_comments(
            youtube_video_id=video_record.youtube_video_id,
            fetch_options=fetch_options,
        )

        for single_comment_data in comment_data_iterator:
            _validate_comment_video(
                video_record=video_record,
                comment_data=single_comment_data,
            )

            # Selenium 捲動時可能重複讀到同一個 DOM 留言，
            # 同一次抓取只保存第一次出現的資料。
            if (single_comment_data.youtube_comment_id in observed_youtube_comment_ids):
                continue

            _save_comment_and_observation(
                video_record=video_record,
                fetch_run=fetch_run,
                comment_data=single_comment_data,
            )

            observed_youtube_comment_ids.add(single_comment_data.youtube_comment_id)


        _resolve_unresolved_parent_comments(video_record=video_record)

    finally:
        # 即使 Provider 中途失敗，也保留已成功保存的留言數量。
        fetch_run.fetched_comment_count = len(observed_youtube_comment_ids)

        fetch_run.save(
            update_fields=[
                "fetched_comment_count",
                "updated_at",
            ]
        )

    return len(observed_youtube_comment_ids)


"""確認 Provider 回傳的留言屬於目前分析的影片。"""
def _validate_comment_video(video_record: Video,comment_data: YouTubeCommentData) -> None:

    if comment_data.youtube_video_id != video_record.youtube_video_id:
        raise YouTubeCommentVideoMismatchError("Provider 回傳的留言不屬於目前分析影片。")


@transaction.atomic
def _save_comment_and_observation(
    video_record: Video,
    fetch_run: FetchRun,
    comment_data: YouTubeCommentData,
) -> Comment:
    """以單則 Transaction 保存留言及本次抓取快照。"""

    existing_comment_record = (
        Comment.objects
        .filter(youtube_comment_id=comment_data.youtube_comment_id)
        .only("id", "video_id")
        .first()
    )

    if (existing_comment_record is not None and existing_comment_record.video_id != video_record.id):
        raise YouTubeCommentVideoMismatchError("相同 YouTube 留言 ID 已經屬於另一支影片。")

    parent_youtube_comment_id = (comment_data.parent_youtube_comment_id or "" )
    parent_comment_record = None

    if parent_youtube_comment_id:
        parent_comment_record = (
            Comment.objects
            .filter(video=video_record,youtube_comment_id=parent_youtube_comment_id )
            .first()
        )

    comment_record, _ = Comment.objects.update_or_create(
        youtube_comment_id=comment_data.youtube_comment_id,
        defaults={
            "video": video_record,
            "parent_youtube_comment_id": parent_youtube_comment_id,
            "parent_comment": parent_comment_record,
            "author_display_name": comment_data.author_display_name or "",
            "author_channel_id": comment_data.author_channel_id or "",
            "author_channel_url": (comment_data.author_channel_url or ""),
            "comment_text": comment_data.comment_text,
            "like_count": comment_data.like_count,
            "published_at": comment_data.published_at,
            "published_time_text": (comment_data.published_time_text or ""),
            "youtube_updated_at": (comment_data.youtube_updated_at),
            "is_pinned": comment_data.is_pinned,
        },
    )

    CommentObservation.objects.update_or_create(
        fetch_run=fetch_run,
        comment=comment_record,
        defaults={
            "observed_author_display_name": (comment_data.author_display_name or ""),
            "observed_comment_text": comment_data.comment_text,
            "observed_like_count": comment_data.like_count,
            "observed_published_time_text": (comment_data.published_time_text or ""),
            "observed_youtube_updated_at": (comment_data.youtube_updated_at),
            "observed_is_pinned": comment_data.is_pinned,
        },
    )

    return comment_record


@transaction.atomic
def _resolve_unresolved_parent_comments(video_record: Video) -> None:
    """父留言稍後出現時，補上回覆留言的 ForeignKey。"""

    unresolved_reply_records = list(
        Comment.objects
        .filter(video=video_record,parent_comment__isnull=True)
        .exclude(parent_youtube_comment_id="")
    )

    if not unresolved_reply_records:
        return

    parent_youtube_comment_ids = {
        reply_record.parent_youtube_comment_id
        for reply_record in unresolved_reply_records
    }

    parent_comment_records = (
        Comment.objects
        .filter(video=video_record,youtube_comment_id__in=parent_youtube_comment_ids)
        .in_bulk(field_name="youtube_comment_id")
    )

    resolved_reply_records = []
    current_time = timezone.now()

    for reply_record in unresolved_reply_records:
        parent_comment_record = parent_comment_records.get(reply_record.parent_youtube_comment_id)

        if (parent_comment_record is None or parent_comment_record.id == reply_record.id):
            continue

        reply_record.parent_comment = parent_comment_record
        reply_record.updated_at = current_time
        resolved_reply_records.append(reply_record)

    if resolved_reply_records:
        Comment.objects.bulk_update(
            resolved_reply_records,
            fields=["parent_comment","updated_at",],
        )
