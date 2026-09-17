from django.db import IntegrityError

from skiflux.models.content import Episode, EpisodePurchase
from skiflux.models.user import User


class PurchaseRepository:
    def create(
        self, user: User, episode: Episode, amount_paid: float
    ) -> tuple[EpisodePurchase, bool]:
        try:
            existing = EpisodePurchase.objects.get(user=user, episode=episode)
            if existing.status == EpisodePurchase.Status.ACTIVE:
                return existing, False
            if existing.status in (
                EpisodePurchase.Status.REFUNDED,
                EpisodePurchase.Status.CANCELLED,
            ):
                existing.status = EpisodePurchase.Status.ACTIVE
                existing.amount_paid = amount_paid
                existing.refunded_at = None
                existing.save(update_fields=["status", "amount_paid", "refunded_at"])
                return existing, True
            return existing, False
        except EpisodePurchase.DoesNotExist:
            pass

        try:
            purchase, created = EpisodePurchase.objects.get_or_create(
                user=user,
                episode=episode,
                defaults={
                    "amount_paid": amount_paid,
                    "status": EpisodePurchase.Status.ACTIVE,
                },
            )
            return purchase, created
        except IntegrityError:
            purchase = EpisodePurchase.objects.get(user=user, episode=episode)
            return purchase, False

    def has_purchased(self, user: User, episode: Episode) -> bool:
        return EpisodePurchase.objects.filter(
            user=user,
            episode=episode,
            status=EpisodePurchase.Status.ACTIVE,
        ).exists()

    def list_by_user(self, user: User):
        return EpisodePurchase.objects.filter(
            user=user,
            status=EpisodePurchase.Status.ACTIVE,
        ).select_related(
            "episode",
            "episode__season",
        )

    def get_purchase_by_id(self, purchase_id: str):
        try:
            return EpisodePurchase.objects.select_related("user", "episode").get(
                id=purchase_id
            )
        except EpisodePurchase.DoesNotExist:
            return None
