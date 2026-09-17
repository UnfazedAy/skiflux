from django.db import models


class UserAppPreferences(models.Model):
    class DownloadQuality(models.TextChoices):
        HIGH = "high", "High"
        STANDARD = "standard", "Standard"
        DATA_SAVER = "data_saver", "Data saver"

    user = models.OneToOneField(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="app_preferences",
    )
    auto_play_next = models.BooleanField(default=True)
    download_quality = models.CharField(
        max_length=20,
        choices=DownloadQuality.choices,
        default=DownloadQuality.STANDARD,
    )
    download_on_wifi_only = models.BooleanField(default=True)
    app_language = models.CharField(max_length=10, default="en")
    save_watch_history = models.BooleanField(default=True)
    personalised_recommendations = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_user_app_preferences"
        verbose_name = "User App Preferences"

    def __str__(self):
        return f"{self.user.email} app preferences"

    @classmethod
    def get_or_create_for_user(cls, user):
        prefs, _ = cls.objects.get_or_create(user=user)
        return prefs
