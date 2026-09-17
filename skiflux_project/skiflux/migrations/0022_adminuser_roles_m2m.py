from django.db import migrations, models


def forwards_copy_roles(apps, _schema_editor):
    AdminUser = apps.get_model("skiflux", "AdminUser")
    Role = apps.get_model("skiflux", "Role")

    creator_role, _ = Role.objects.get_or_create(
        name="Creator",
        defaults={
            "description": "Built-in studio access for uploading and managing content.",
            "permissions": [],
            "is_custom": False,
            "grants_studio_access": True,
        },
    )
    if not creator_role.grants_studio_access:
        creator_role.grants_studio_access = True
        creator_role.save(update_fields=["grants_studio_access"])

    for admin in AdminUser.objects.all().iterator():
        role_ids = set()
        legacy_role_id = getattr(admin, "role_id", None)
        if legacy_role_id:
            role_ids.add(legacy_role_id)
        if getattr(admin, "is_creator", False) or admin.role_type == "creator":
            role_ids.add(creator_role.id)
        if role_ids:
            admin.roles.set(role_ids)


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0021_adminuser_is_creator_and_financial_config_bonus"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="grants_studio_access",
            field=models.BooleanField(
                default=False,
                help_text="When True, holders of this role may use the creator studio.",
            ),
        ),
        migrations.AddField(
            model_name="adminuser",
            name="roles",
            field=models.ManyToManyField(
                blank=True,
                help_text="Custom and built-in roles assigned to this account.",
                related_name="admin_users",
                to="skiflux.role",
            ),
        ),
        migrations.RunPython(forwards_copy_roles, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="adminuser",
            name="role",
        ),
        migrations.RemoveField(
            model_name="adminuser",
            name="is_creator",
        ),
    ]
