from datetime import time

from django.core.cache import cache
from django.db import models


class SystemContentConfig(models.Model):
    max_video_size_mb = models.PositiveIntegerField(default=100)
    max_submission_size_mb = models.PositiveIntegerField(default=50)
    max_thumbnail_size_mb = models.PositiveIntegerField(default=2)
    max_episodes_per_season = models.PositiveIntegerField(default=30)
    max_seasons_per_creator = models.PositiveIntegerField(default=12)
    max_assessment_questions = models.PositiveIntegerField(default=50)
    sla_review_hours = models.PositiveIntegerField(default=24)
    allowed_video_formats = models.JSONField(
        default=list,
        help_text="List of allowed video formats e.g. ['mp4', 'mov']",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_configs",
    )

    class Meta:
        db_table = "skiflux_system_content_config"
        verbose_name = "System Content Config"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_content_config")

    @classmethod
    def get_config(cls) -> "SystemContentConfig":
        config = cache.get("system_content_config")
        if config is None:
            config, _ = cls.objects.get_or_create(
                pk=1,
                defaults={
                    "max_video_size_mb": 100,
                    "max_submission_size_mb": 50,
                    "max_thumbnail_size_mb": 2,
                    "max_episodes_per_season": 30,
                    "max_seasons_per_creator": 12,
                    "max_assessment_questions": 50,
                    "sla_review_hours": 24,
                    "allowed_video_formats": [
                        "mp4",
                        "webm",
                        "mov",
                        "mkv",
                        "avi",
                        "wmv",
                    ],
                },
            )
            cache.set("system_content_config", config, timeout=300)
        return config


class SystemNotificationConfig(models.Model):
    episode_approved = models.BooleanField(default=True)
    episode_rejected = models.BooleanField(default=True)
    task_submission_received = models.BooleanField(default=True)
    withdrawal_processed = models.BooleanField(default=True)
    weekly_performance_digest = models.BooleanField(default=True)
    task_approved_with_coins = models.BooleanField(default=True)
    task_rejected_with_feedback = models.BooleanField(default=True)
    new_episode_in_enrolled_world = models.BooleanField(default=True)
    deposit_confirmed = models.BooleanField(default=True)
    streak_reminder = models.BooleanField(default=False)
    daily_reminder_time = models.TimeField(
        default=time(9, 0),
        help_text="Time of day in WAT (Africa/Lagos TZ) when daily "
        "task/we-miss-you reminders are sent. Superadmin can set "
        "(e.g. 09:00). Default 9:00 AM WAT.",
    )
    new_comment_on_episode = models.BooleanField(default=True)
    assessment_perfect_score = models.BooleanField(default=True)
    milestone_badge_earned = models.BooleanField(default=True)
    referral_bonus_credited = models.BooleanField(default=True)
    streak_broken = models.BooleanField(default=True)
    streak_maintained = models.BooleanField(default=True)
    task_deadline_approaching = models.BooleanField(default=True)
    new_learning_path = models.BooleanField(default=True)
    community_challenge = models.BooleanField(default=True)
    new_follower = models.BooleanField(default=True)
    episode_reached_x_views = models.BooleanField(default=True)
    revenue_milestone = models.BooleanField(default=True)
    new_season_from_followed_creator = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_configs",
    )

    class Meta:
        db_table = "skiflux_system_notification_config"
        verbose_name = "System Notification Config"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_notification_config")

    @classmethod
    def get_config(cls) -> "SystemNotificationConfig":
        config = cache.get("system_notification_config")
        if config is None:
            config, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    "episode_approved": True,
                    "episode_rejected": True,
                    "task_submission_received": True,
                    "withdrawal_processed": True,
                    "weekly_performance_digest": True,
                    "task_approved_with_coins": True,
                    "task_rejected_with_feedback": True,
                    "new_episode_in_enrolled_world": True,
                    "deposit_confirmed": True,
                    "streak_reminder": False,
                    "daily_reminder_time": time(9, 0),
                    "new_comment_on_episode": True,
                    "assessment_perfect_score": True,
                    "milestone_badge_earned": True,
                    "referral_bonus_credited": True,
                    "streak_broken": True,
                    "streak_maintained": True,
                    "task_deadline_approaching": True,
                    "new_learning_path": True,
                    "community_challenge": True,
                    "new_follower": True,
                    "episode_reached_x_views": True,
                    "revenue_milestone": True,
                    "new_season_from_followed_creator": True,
                },
            )
            cache.set("system_notification_config", config, timeout=300)
        return config


class SystemSecurityConfig(models.Model):
    session_timeout_minutes = models.PositiveIntegerField(default=60)
    max_failed_login_attempts = models.PositiveIntegerField(default=5)
    account_lockout_duration_minutes = models.PositiveIntegerField(default=30)
    require_2fa_for_admins = models.BooleanField(default=True)
    ip_allowlist_for_super_admin = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_configs",
    )

    class Meta:
        db_table = "skiflux_system_security_config"
        verbose_name = "System Security Config"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_security_config")

    @classmethod
    def get_config(cls) -> "SystemSecurityConfig":
        config = cache.get("system_security_config")
        if config is None:
            config, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    "session_timeout_minutes": 60,
                    "max_failed_login_attempts": 5,
                    "account_lockout_duration_minutes": 30,
                    "require_2fa_for_admins": True,
                    "ip_allowlist_for_super_admin": False,
                },
            )
            cache.set("system_security_config", config, timeout=300)
        return config


class SystemFeatureFlagConfig(models.Model):
    leaderboard = models.BooleanField(default=True)
    portfolio_share_links = models.BooleanField(default=True)
    skillcoin_withdrawals = models.BooleanField(default=True)
    new_user_registrations = models.BooleanField(default=True)
    comments_system = models.BooleanField(default=True)
    referral_program = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    ai_task_grading = models.BooleanField(default=False)
    creator_analytics_dashboard = models.BooleanField(default=True)
    multi_language_support = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_flag_configs",
    )

    class Meta:
        db_table = "skiflux_system_feature_flag_config"
        verbose_name = "System Feature Flag Config"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_feature_flag_config")

    @classmethod
    def get_config(cls) -> "SystemFeatureFlagConfig":
        config = cache.get("system_feature_flag_config")
        if config is None:
            config, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    "leaderboard": True,
                    "portfolio_share_links": True,
                    "skillcoin_withdrawals": True,
                    "new_user_registrations": True,
                    "comments_system": True,
                    "referral_program": True,
                    "maintenance_mode": False,
                    "ai_task_grading": False,
                    "creator_analytics_dashboard": True,
                    "multi_language_support": False,
                },
            )
            cache.set("system_feature_flag_config", config, timeout=300)
        return config


class SystemGamificationConfig(models.Model):
    xp_for_amateur = models.PositiveIntegerField(default=1000)
    xp_for_senior = models.PositiveIntegerField(default=5000)
    xp_for_expert = models.PositiveIntegerField(default=15000)
    xp_for_professional = models.PositiveIntegerField(default=50000)
    xp_per_7_day_streak = models.PositiveIntegerField(default=50)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gamification_configs",
    )

    class Meta:
        db_table = "skiflux_system_gamification_config"
        verbose_name = "System Gamification Config"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_gamification_config")

    @classmethod
    def get_config(cls) -> "SystemGamificationConfig":
        config = cache.get("system_gamification_config")
        if config is None:
            config, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    "xp_for_amateur": 1000,
                    "xp_for_senior": 5000,
                    "xp_for_expert": 15000,
                    "xp_for_professional": 50000,
                    "xp_per_7_day_streak": 50,
                },
            )
            cache.set("system_gamification_config", config, timeout=300)
        return config
