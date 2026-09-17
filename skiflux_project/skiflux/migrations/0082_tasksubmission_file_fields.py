from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0081_usernotificationpreferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="tasksubmission",
            name="submission_file_content_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="tasksubmission",
            name="submission_file_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="tasksubmission",
            name="submission_file_public_id",
            field=models.CharField(
                blank=True,
                help_text="Cloudinary public_id for uploaded proof file.",
                max_length=500,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tasksubmission",
            name="submission_file_url",
            field=models.URLField(blank=True, max_length=2000, null=True),
        ),
        migrations.AlterField(
            model_name="episodetask",
            name="accepted_proof_types",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Creator defined e.g. ["link", "image", "video", "file"]. '
                "Learners may submit a link, text notes, and/or an uploaded proof file.",
            ),
        ),
    ]
