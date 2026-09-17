from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0022_adminuser_roles_m2m"),
        ("skiflux", "0020_merge_20260520_1646"),
    ]

    operations = [
        migrations.AddField(
            model_name="episodepurchase",
            name="refunded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="episodepurchase",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("refunded", "Refunded"),
                    ("cancelled", "Cancelled"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="skillcointransaction",
            name="status",
            field=models.CharField(
                choices=[
                    ("posted", "Posted"),
                    ("cancelled", "Cancelled"),
                    ("refunded", "Refunded"),
                    ("failed", "Failed"),
                ],
                default="posted",
                help_text=(
                    "Lifecycle state for audit; posted rows count "
                    "toward wallet balance."
                ),
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="skillcointransaction",
            name="transaction_type",
            field=models.CharField(
                choices=[
                    ("deposit", "Deposit (Credit)"),
                    ("debit_purchase", "Purchase Episode (Debit)"),
                    ("creator_revenue", "Creator Revenue Split (Credit)"),
                    (
                        "creator_revenue_reversal",
                        "Creator Revenue Reversal (Debit)",
                    ),
                    ("cashback_reward", "Cashback Reward (Credit)"),
                    ("refund", "Refund (Credit)"),
                    ("admin_adjustment", "Manual Admin Adjustment (Adjustment)"),
                ],
                max_length=30,
            ),
        ),
    ]
