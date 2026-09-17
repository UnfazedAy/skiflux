from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0093_saved_cards_stripe_connect"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalaccount",
            name="gateway_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Gateway used to register or pay out to this destination "
                "(e.g. paystack, stripe).",
                max_length=30,
            ),
        ),
    ]
