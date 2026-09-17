from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0094_withdrawalaccount_gateway_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalaccount",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="False when the owner removes this destination.",
            ),
        ),
    ]
