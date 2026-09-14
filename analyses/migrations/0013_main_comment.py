from django.db import migrations, models


def rename_sample_key(apps, schema_editor, old_key, new_key):
    results = apps.get_model("analyses", "AnalysisResult").objects.using(schema_editor.connection.alias)
    for result in results.all().iterator():
        payload = result.result_data
        if not isinstance(payload, dict):
            continue
        sample = payload.get("sample")
        if not isinstance(sample, dict) or old_key not in sample:
            continue
        if new_key in sample and sample[new_key] != sample[old_key]:
            raise ValueError(f"Conflicting report sample keys for AnalysisResult {result.pk}")
        sample[new_key] = sample.pop(old_key)
        results.filter(pk=result.pk).update(result_data=payload)


def forwards(apps, schema_editor):
    rename_sample_key(apps, schema_editor, "top_level_comment_count", "main_comment_count")


def backwards(apps, schema_editor):
    rename_sample_key(apps, schema_editor, "main_comment_count", "top_level_comment_count")


class Migration(migrations.Migration):
    dependencies = [("analyses", "0012_comment_snapshot")]

    operations = [
        migrations.RemoveConstraint(
            model_name="analysisresult", name="analysis_result_comment_counts_match",
        ),
        migrations.RenameField(
            model_name="analysisresult", old_name="top_level_comment_count",
            new_name="main_comment_count",
        ),
        migrations.AddConstraint(
            model_name="analysisresult",
            constraint=models.CheckConstraint(
                condition=models.Q(analyzed_comment_count=models.F("main_comment_count") + models.F("reply_comment_count")),
                name="analysis_result_comment_counts_match",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
