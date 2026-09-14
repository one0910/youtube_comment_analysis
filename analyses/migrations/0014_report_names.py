from django.db import migrations


def rename_schema(apps, schema_editor, old, new):
    results = apps.get_model("analyses", "AnalysisResult").objects.using(schema_editor.connection.alias)
    for result in results.filter(schema_version=old).iterator():
        payload = result.result_data
        if isinstance(payload, dict) and payload.get("schema_version") == old:
            payload["schema_version"] = new
        results.filter(pk=result.pk).update(schema_version=new, result_data=payload)


def forwards(apps, schema_editor):
    rename_schema(apps, schema_editor, "comment-analysis-result-v2", "comment-analysis-result")


def backwards(apps, schema_editor):
    rename_schema(apps, schema_editor, "comment-analysis-result", "comment-analysis-result-v2")


class Migration(migrations.Migration):
    dependencies = [("analyses", "0013_main_comment")]
    operations = [migrations.RunPython(forwards, backwards)]
