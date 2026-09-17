from decimal import Decimal

from django.db import migrations, models


def set_is_creator_true(apps, _schema_editor):
    AdminUser = apps.get_model("skiflux", "AdminUser")
    AdminUser.objects.filter(role_type="creator").update(is_creator=True)


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0020_systemfinancialconfig_userwallet_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminuser",
            name="is_creator",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When True, this account may use the creator studio while keeping "
                    "its admin role_type and assigned portal role."
                ),
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="registration_bonus_granted",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True after the one-time registration Skillcoin bonus is credited."
                ),
            ),
        ),
        migrations.AddField(
            model_name="systemfinancialconfig",
            name="registration_bonus_skillcoins",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "One-time Skillcoins credited when a user verifies their account."
                ),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="systemfinancialconfig",
            name="max_manual_adjustment_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10000.00"),
                help_text=(
                    "Maximum absolute amount for a single manual wallet adjustment."
                ),
                max_digits=12,
            ),
        ),
        migrations.RunPython(
            code=set_is_creator_true,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
