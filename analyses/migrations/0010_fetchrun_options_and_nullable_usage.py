from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analyses", "0009_analysisresult"),
    ]

    operations = [
        migrations.AddField(
            model_name="fetchrun",
            name="sort_order",
            field=models.CharField(
                choices=[("newest", "最新"), ("top", "熱門")],
                default="newest",
                max_length=10,
                verbose_name="留言排序方式",
            ),
        ),
        migrations.AddField(
            model_name="fetchrun",
            name="include_replies",
            field=models.BooleanField(default=True, verbose_name="是否包含回覆"),
        ),
        migrations.AddField(
            model_name="fetchrun",
            name="maximum_comment_count",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="留言數量上限"),
        ),
        migrations.AddConstraint(
            model_name="fetchrun",
            constraint=models.CheckConstraint(
                condition=models.Q(("maximum_comment_count__isnull", True), ("maximum_comment_count__gte", 1), _connector="OR"),
                name="fetch_run_maximum_comment_count_gte_1",
            ),
        ),
        migrations.AlterField(
            model_name="analysisresult",
            name="prompt_tokens",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="輸入 Token 數"),
        ),
        migrations.AlterField(
            model_name="analysisresult",
            name="completion_tokens",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="輸出 Token 數"),
        ),
        migrations.AlterField(
            model_name="analysisresult",
            name="total_tokens",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="總 Token 數"),
        ),
    ]
