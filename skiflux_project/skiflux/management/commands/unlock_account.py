from django.core.management.base import BaseCommand

from skiflux.models import AdminUser, User
from skiflux.utils.lockout import manually_unlock_account


class Command(BaseCommand):
    help = "Manually unlock a user or admin account by email"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)

    def handle(self, *args, **options):
        email = options["email"]
        for Model in (User, AdminUser):
            obj = Model.objects.filter(email=email).first()
            if obj:
                manually_unlock_account(obj)
                self.stdout.write(self.style.SUCCESS(f"Successfully unlocked: {email}"))
                return
        self.stdout.write(self.style.ERROR(f"No user found with email: {email}"))
