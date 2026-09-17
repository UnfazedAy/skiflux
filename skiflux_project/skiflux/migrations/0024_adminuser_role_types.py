from django.db import migrations, models


def forwards_populate_role_types(apps, _schema_editor):
    AdminUser = apps.get_model("skiflux", "AdminUser")
    Role = apps.get_model("skiflux", "Role")

    creator_role = Role.objects.filter(name="Creator", is_custom=False).first()

    for admin in AdminUser.objects.all().iterator():
        types = [admin.role_type]
        if (
            creator_role
            and admin.roles.filter(id=creator_role.id).exists()
            and "creator" not in types
        ):
            types.append("creator")

        admin.role_types = types
        admin.save(update_fields=["role_types"])


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0023_ledger_transaction_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminuser",
            name="role_types",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Built-in role types held by this account. Platform admins may "
                    "include 'creator' here without changing role_type from 'admin'."
                ),
            ),
        ),
        migrations.RunPython(forwards_populate_role_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="season",
            name="creator",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="seasons",
                to="skiflux.adminuser",
            ),
        ),
        migrations.AlterField(
            model_name="episode",
            name="creator",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="episodes",
                to="skiflux.adminuser",
            ),
        ),
        migrations.AlterField(
            model_name="follow",
            name="creator",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="followers",
                to="skiflux.adminuser",
            ),
        ),
    ]
