from django.db import models


class CurrencyConfig(models.Model):
    """Per-currency conversion rates and gateway mappings."""

    currency_code = models.CharField(
        max_length=3,
        unique=True,
        help_text="ISO 4217 code: NGN, USD, GBP, EUR, GHS, ZAR, KES",
    )
    currency_name = models.CharField(max_length=50)
    currency_symbol = models.CharField(max_length=5)
    skillcoin_rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="How many units of this currency = 1 SkillCoin",
    )
    subunit_multiplier = models.PositiveIntegerField(
        default=100,
        help_text=(
            "Smallest-unit multiplier for this currency. "
            "Use 100 for 2-decimal currencies (USD, NGN, GBP, EUR, GHS, ZAR, KES). "
            "Use 1000 for 3-decimal currencies (KWD, BHD). "
            "Use 1 for 0-decimal currencies (JPY, KRW)."
        ),
    )
    is_active = models.BooleanField(default=True)
    supported_gateways = models.JSONField(
        default=list, help_text="List of gateway names that support this currency"
    )
    country_code = models.CharField(
        max_length=2, blank=True, help_text="ISO 3166-1 alpha-2 country code"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_currency_config"
        verbose_name = "Currency Config"
        verbose_name_plural = "Currency Configs"

    def __str__(self):
        return f"{self.currency_code} - {self.currency_name}"
