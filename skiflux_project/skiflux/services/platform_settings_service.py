from skiflux.models.platform_settings import (
    SystemContentConfig,
    SystemFeatureFlagConfig,
    SystemGamificationConfig,
    SystemNotificationConfig,
    SystemSecurityConfig,
)

from skiflux.models import AdminUser
from rest_framework.exceptions import PermissionDenied, ValidationError


class PlatformSettingsService:
    @staticmethod
    def get_content_config() -> SystemContentConfig:
        return SystemContentConfig.get_config()

    @staticmethod
    def get_feature_flag_config() -> SystemFeatureFlagConfig:
        return SystemFeatureFlagConfig.get_config()

    @staticmethod
    def get_notification_config() -> SystemNotificationConfig:
        return SystemNotificationConfig.get_config()

    @staticmethod
    def get_security_config() -> SystemSecurityConfig:
        return SystemSecurityConfig.get_config()

    def update_content_config(
        self,
        admin: AdminUser,
        max_video_size_mb: int = None,
        max_submission_size_mb: int = None,
        max_thumbnail_size_mb: int = None,
        max_episodes_per_season: int = None,
        max_seasons_per_creator: int = None,
        max_assessment_questions: int = None,
        sla_review_hours: int = None,
        allowed_video_formats: list = None,
    ) -> SystemContentConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update platform content settings."
            )

        config = SystemContentConfig.get_config()

        if max_video_size_mb is not None:
            if max_video_size_mb <= 0:
                raise ValidationError("max_video_size_mb must be greater than zero.")
            config.max_video_size_mb = max_video_size_mb

        if max_submission_size_mb is not None:
            if max_submission_size_mb <= 0:
                raise ValidationError(
                    "max_submission_size_mb must be greater than zero."
                )
            config.max_submission_size_mb = max_submission_size_mb

        if max_thumbnail_size_mb is not None:
            if max_thumbnail_size_mb <= 0:
                raise ValidationError(
                    "max_thumbnail_size_mb must be greater than zero."
                )
            config.max_thumbnail_size_mb = max_thumbnail_size_mb

        if max_episodes_per_season is not None:
            if max_episodes_per_season <= 0:
                raise ValidationError(
                    "max_episodes_per_season must be greater than zero."
                )
            config.max_episodes_per_season = max_episodes_per_season

        if max_seasons_per_creator is not None:
            if max_seasons_per_creator <= 0:
                raise ValidationError(
                    "max_seasons_per_creator must be greater than zero."
                )
            config.max_seasons_per_creator = max_seasons_per_creator

        if max_assessment_questions is not None:
            if max_assessment_questions <= 0:
                raise ValidationError(
                    "max_assessment_questions must be greater than zero."
                )
            config.max_assessment_questions = max_assessment_questions

        if sla_review_hours is not None:
            if sla_review_hours <= 0:
                raise ValidationError("sla_review_hours must be greater than zero.")
            config.sla_review_hours = sla_review_hours

        if allowed_video_formats is not None:
            if not isinstance(allowed_video_formats, list):
                raise ValidationError("allowed_video_formats must be a list.")
            if any(
                not isinstance(item, str) or not item.strip()
                for item in allowed_video_formats
            ):
                raise ValidationError(
                    "allowed_video_formats must be a list of non-empty strings."
                )
            config.allowed_video_formats = allowed_video_formats

        config.updated_by = admin
        config.save()
        return config

    def update_notification_config(
        self,
        admin: AdminUser,
        episode_approved: bool = None,
        episode_rejected: bool = None,
        task_submission_received: bool = None,
        withdrawal_processed: bool = None,
        weekly_performance_digest: bool = None,
        task_approved_with_coins: bool = None,
        task_rejected_with_feedback: bool = None,
        new_episode_in_enrolled_world: bool = None,
        deposit_confirmed: bool = None,
        streak_reminder: bool = None,
        daily_reminder_time: str = None,  # e.g. "09:00" (WAT) or time object
        new_comment_on_episode: bool = None,
        assessment_perfect_score: bool = None,
        milestone_badge_earned: bool = None,
        referral_bonus_credited: bool = None,
        streak_broken: bool = None,
        streak_maintained: bool = None,
        task_deadline_approaching: bool = None,
        new_learning_path: bool = None,
        community_challenge: bool = None,
        new_follower: bool = None,
        episode_reached_x_views: bool = None,
        revenue_milestone: bool = None,
        new_season_from_followed_creator: bool = None,
    ) -> SystemNotificationConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update platform notification settings."
            )

        config = SystemNotificationConfig.get_config()

        if episode_approved is not None:
            config.episode_approved = episode_approved
        if episode_rejected is not None:
            config.episode_rejected = episode_rejected
        if task_submission_received is not None:
            config.task_submission_received = task_submission_received
        if withdrawal_processed is not None:
            config.withdrawal_processed = withdrawal_processed
        if weekly_performance_digest is not None:
            config.weekly_performance_digest = weekly_performance_digest
        if task_approved_with_coins is not None:
            config.task_approved_with_coins = task_approved_with_coins
        if task_rejected_with_feedback is not None:
            config.task_rejected_with_feedback = task_rejected_with_feedback
        if new_episode_in_enrolled_world is not None:
            config.new_episode_in_enrolled_world = new_episode_in_enrolled_world
        if deposit_confirmed is not None:
            config.deposit_confirmed = deposit_confirmed
        if streak_reminder is not None:
            config.streak_reminder = streak_reminder
        if daily_reminder_time is not None:
            from datetime import datetime

            if isinstance(daily_reminder_time, str):
                config.daily_reminder_time = datetime.strptime(
                    daily_reminder_time, "%H:%M"
                ).time()
            else:
                config.daily_reminder_time = daily_reminder_time
        if new_comment_on_episode is not None:
            config.new_comment_on_episode = new_comment_on_episode
        if assessment_perfect_score is not None:
            config.assessment_perfect_score = assessment_perfect_score
        if milestone_badge_earned is not None:
            config.milestone_badge_earned = milestone_badge_earned
        if referral_bonus_credited is not None:
            config.referral_bonus_credited = referral_bonus_credited
        if streak_broken is not None:
            config.streak_broken = streak_broken
        if streak_maintained is not None:
            config.streak_maintained = streak_maintained
        if task_deadline_approaching is not None:
            config.task_deadline_approaching = task_deadline_approaching
        if new_learning_path is not None:
            config.new_learning_path = new_learning_path
        if community_challenge is not None:
            config.community_challenge = community_challenge
        if new_follower is not None:
            config.new_follower = new_follower
        if episode_reached_x_views is not None:
            config.episode_reached_x_views = episode_reached_x_views
        if revenue_milestone is not None:
            config.revenue_milestone = revenue_milestone
        if new_season_from_followed_creator is not None:
            config.new_season_from_followed_creator = new_season_from_followed_creator

        config.updated_by = admin
        config.save()
        return config

    def update_security_config(
        self,
        admin: AdminUser,
        session_timeout_minutes: int = None,
        max_failed_login_attempts: int = None,
        account_lockout_duration_minutes: int = None,
        require_2fa_for_admins: bool = None,
        ip_allowlist_for_super_admin: bool = None,
    ) -> SystemSecurityConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update platform security settings."
            )

        config = SystemSecurityConfig.get_config()

        if session_timeout_minutes is not None:
            if session_timeout_minutes <= 0:
                raise ValidationError(
                    "session_timeout_minutes must be greater than zero."
                )
            config.session_timeout_minutes = session_timeout_minutes
        if max_failed_login_attempts is not None:
            if max_failed_login_attempts <= 0:
                raise ValidationError(
                    "max_failed_login_attempts must be greater than zero."
                )
            config.max_failed_login_attempts = max_failed_login_attempts
        if account_lockout_duration_minutes is not None:
            if account_lockout_duration_minutes <= 0:
                raise ValidationError(
                    "account_lockout_duration_minutes must be greater than zero."
                )
            config.account_lockout_duration_minutes = account_lockout_duration_minutes
        if require_2fa_for_admins is not None:
            config.require_2fa_for_admins = require_2fa_for_admins
        if ip_allowlist_for_super_admin is not None:
            config.ip_allowlist_for_super_admin = ip_allowlist_for_super_admin

        config.updated_by = admin
        config.save()
        return config

    def update_feature_flag_config(
        self,
        admin: AdminUser,
        leaderboard: bool = None,
        portfolio_share_links: bool = None,
        skillcoin_withdrawals: bool = None,
        new_user_registrations: bool = None,
        comments_system: bool = None,
        referral_program: bool = None,
        maintenance_mode: bool = None,
        ai_task_grading: bool = None,
        creator_analytics_dashboard: bool = None,
        multi_language_support: bool = None,
    ) -> SystemFeatureFlagConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update platform feature flag settings."
            )

        config = SystemFeatureFlagConfig.get_config()

        if leaderboard is not None:
            config.leaderboard = leaderboard
        if portfolio_share_links is not None:
            config.portfolio_share_links = portfolio_share_links
        if skillcoin_withdrawals is not None:
            config.skillcoin_withdrawals = skillcoin_withdrawals
        if new_user_registrations is not None:
            config.new_user_registrations = new_user_registrations
        if comments_system is not None:
            config.comments_system = comments_system
        if referral_program is not None:
            config.referral_program = referral_program
        if maintenance_mode is not None:
            config.maintenance_mode = maintenance_mode
        if ai_task_grading is not None:
            config.ai_task_grading = ai_task_grading
        if creator_analytics_dashboard is not None:
            config.creator_analytics_dashboard = creator_analytics_dashboard
        if multi_language_support is not None:
            config.multi_language_support = multi_language_support

        config.updated_by = admin
        config.save()
        return config

    @staticmethod
    def get_gamification_config() -> SystemGamificationConfig:
        return SystemGamificationConfig.get_config()

    def update_gamification_config(
        self,
        admin: AdminUser,
        xp_for_amateur: int = None,
        xp_for_senior: int = None,
        xp_for_expert: int = None,
        xp_for_professional: int = None,
        xp_per_7_day_streak: int = None,
    ) -> SystemGamificationConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update platform gamification settings."
            )

        config = SystemGamificationConfig.get_config()

        if xp_for_amateur is not None:
            if xp_for_amateur < 0:
                raise ValidationError("XP cannot be negative.")
            config.xp_for_amateur = xp_for_amateur

        if xp_for_senior is not None:
            if xp_for_senior < 0:
                raise ValidationError("XP cannot be negative.")
            config.xp_for_senior = xp_for_senior

        if xp_for_expert is not None:
            if xp_for_expert < 0:
                raise ValidationError("XP cannot be negative.")
            config.xp_for_expert = xp_for_expert

        if xp_for_professional is not None:
            if xp_for_professional < 0:
                raise ValidationError("XP cannot be negative.")
            config.xp_for_professional = xp_for_professional

        if xp_per_7_day_streak is not None:
            if xp_per_7_day_streak < 0:
                raise ValidationError("XP cannot be negative.")
            config.xp_per_7_day_streak = xp_per_7_day_streak

        config.updated_by = admin
        config.save()
        return config
