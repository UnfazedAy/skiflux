from typing import Optional, List
from skiflux.models.gamification import Badge, UserBadge
from skiflux.models.user import User


class GamificationRepository:
    def get_badge_by_id(self, badge_id: str) -> Optional[Badge]:
        try:
            return Badge.objects.get(id=badge_id)
        except Badge.DoesNotExist:
            return None

    def get_badge_by_name(self, name: str) -> Optional[Badge]:
        try:
            return Badge.objects.get(name__iexact=name)
        except Badge.DoesNotExist:
            return None

    def update_badge(self, badge: Badge, **kwargs) -> Badge:
        for key, value in kwargs.items():
            setattr(badge, key, value)
        badge.save()
        return badge

    def get_all_badges(self) -> List[Badge]:
        return list(Badge.objects.filter(is_active=True))

    def award_badge(self, user: User, badge: Badge) -> UserBadge:
        user_badge, created = UserBadge.objects.get_or_create(user=user, badge=badge)
        return user_badge

    def get_user_badges(self, user: User) -> List[UserBadge]:
        return list(UserBadge.objects.filter(user=user).select_related("badge"))
