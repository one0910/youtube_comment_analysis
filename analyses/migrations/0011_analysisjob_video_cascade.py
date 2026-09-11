import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analyses", "0010_fetchrun_options_and_nullable_usage")]

    operations = [
        migrations.AlterField(
            model_name="analysisjob",
            name="video",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="analysis_jobs",
                to="analyses.video",
                verbose_name="影片",
            ),
        ),
    ]
