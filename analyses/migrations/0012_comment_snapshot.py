import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analyses", "0011_analysisjob_video_cascade")]

    operations = [
        migrations.RenameModel("CommentObservation", "CommentSnapshot"),
        migrations.RemoveConstraint(
            model_name="commentsnapshot",
            name="unique_comment_observation_per_fetch_run",
        ),
        *[
            migrations.RenameField("commentsnapshot", "observed_" + suffix, "snapshot_" + suffix)
            for suffix in (
                "author_display_name", "comment_text", "like_count",
                "published_time_text", "youtube_updated_at", "is_pinned", "at",
            )
        ],
        migrations.AlterModelOptions(
            name="commentsnapshot",
            options={"ordering": ["snapshot_at", "id"],
                     "verbose_name": "留言快照", "verbose_name_plural": "留言快照"},
        ),
        migrations.AlterField(
            model_name="commentsnapshot", name="snapshot_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="快照時間"),
        ),
        migrations.AlterField(
            model_name="commentsnapshot", name="fetch_run",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name="comment_snapshots", to="analyses.fetchrun", verbose_name="留言抓取紀錄"),
        ),
        migrations.AlterField(
            model_name="commentsnapshot", name="comment",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name="snapshots", to="analyses.comment", verbose_name="留言"),
        ),
        migrations.AddConstraint(
            model_name="commentsnapshot",
            constraint=models.UniqueConstraint(fields=("fetch_run", "comment"),
                name="unique_comment_snapshot_per_fetch_run"),
        ),
    ]
