from rest_framework import serializers

from skiflux.models.platform_settings import (
    SystemContentConfig,
    SystemFeatureFlagConfig,
    SystemNotificationConfig,
    SystemSecurityConfig,
    SystemGamificationConfig,
)


class SystemContentConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemContentConfig
        fields = [
            "max_video_size_mb",
            "max_submission_size_mb",
            "max_thumbnail_size_mb",
            "max_episodes_per_season",
            "max_seasons_per_creator",
            "max_assessment_questions",
            "sla_review_hours",
            "allowed_video_formats",
        ]
        extra_kwargs = {
            "allowed_video_formats": {"required": False},
        }


class SystemNotificationConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemNotificationConfig
        fields = [
            "episode_approved",
            "episode_rejected",
            "task_submission_received",
            "withdrawal_processed",
            "weekly_performance_digest",
            "task_approved_with_coins",
            "task_rejected_with_feedback",
            "new_episode_in_enrolled_world",
            "deposit_confirmed",
            "streak_reminder",
            "daily_reminder_time",
            "new_comment_on_episode",
            "assessment_perfect_score",
            "milestone_badge_earned",
            "referral_bonus_credited",
            "streak_broken",
            "streak_maintained",
            "task_deadline_approaching",
            "new_learning_path",
            "community_challenge",
            "new_follower",
            "episode_reached_x_views",
            "revenue_milestone",
            "new_season_from_followed_creator",
        ]


class SystemSecurityConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSecurityConfig
        fields = [
            "session_timeout_minutes",
            "max_failed_login_attempts",
            "account_lockout_duration_minutes",
            "require_2fa_for_admins",
            "ip_allowlist_for_super_admin",
        ]


class SystemFeatureFlagConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemFeatureFlagConfig
        fields = [
            "leaderboard",
            "portfolio_share_links",
            "skillcoin_withdrawals",
            "new_user_registrations",
            "comments_system",
            "referral_program",
            "maintenance_mode",
            "ai_task_grading",
            "creator_analytics_dashboard",
            "multi_language_support",
        ]


class SystemGamificationConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemGamificationConfig
        fields = [
            "xp_for_amateur",
            "xp_for_senior",
            "xp_for_expert",
            "xp_for_professional",
            "xp_per_7_day_streak",
        ]
