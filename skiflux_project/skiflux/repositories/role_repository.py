from typing import Optional
from skiflux.models import Role
from django.db import IntegrityError


class RoleRepository:
    def create(self, **kwargs) -> tuple[Optional[Role], Optional[str]]:
        try:
            role = Role.objects.create(**kwargs)
            return role, None
        except IntegrityError:
            return None, "IntegrityError"

    def get_all(self):
        return list(Role.objects.all())

    def get_by_id(self, role_id: str) -> Optional[Role]:
        try:
            return Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return None

    def get_by_name(self, name: str) -> Optional[Role]:
        try:
            return Role.objects.get(name=name)
        except Role.DoesNotExist:
            return None

    def filter_by_ids(self, role_ids: list):
        return list(Role.objects.filter(id__in=role_ids))
