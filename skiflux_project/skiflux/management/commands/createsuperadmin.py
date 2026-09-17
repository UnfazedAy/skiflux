import getpass

from django.core.management.base import BaseCommand, CommandError

from skiflux.models import AdminUser


class Command(BaseCommand):
    help = "Creates a new Super Admin account for the SkiFlux Admin Portal."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Create SkiFlux Super Admin ---"))

        email = input("Email address: ").strip().lower()
        if not email:
            raise CommandError("Email cannot be blank.")

        if AdminUser.objects.filter(email=email).exists():
            raise CommandError(
                f"Error: An admin user with email '{email}' already exists."
            )

        first_name = input("First name: ").strip()
        if not first_name:
            raise CommandError("First name cannot be blank.")

        last_name = input("Last name (optional): ").strip()

        while True:
            password = getpass.getpass("Password: ")
            if len(password) < 8:
                self.stdout.write(
                    self.style.ERROR("Password must be at least 8 characters long.")
                )
                continue

            password_confirm = getpass.getpass("Password (again): ")
            if password != password_confirm:
                self.stdout.write(
                    self.style.ERROR("Error: Your passwords didn't match.")
                )
            else:
                break

        try:
            AdminUser.objects.create_super_admin(
                email=email,
                first_name=first_name,
                password=password,
                last_name=last_name,
            )
            self.stdout.write(
                self.style.SUCCESS(f"\nSuccessfully created Super Admin: {email}")
            )
        except Exception as e:
            raise CommandError(f"Failed to create Super Admin: {str(e)}")
