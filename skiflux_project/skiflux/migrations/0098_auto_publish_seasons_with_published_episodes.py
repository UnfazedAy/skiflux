from django.db import migrations


def publish_seasons_with_published_episodes(apps, schema_editor):
    Season = apps.get_model("skiflux", "Season")
    Episode = apps.get_model("skiflux", "Episode")
    published = "published"

    season_ids = (
        Episode.objects.filter(status=published)
        .values_list("season_id", flat=True)
        .distinct()
    )
    Season.objects.filter(id__in=season_ids, is_published=False).update(
        is_published=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0097_systemfinancialconfig_episode_purchase_price_skillcoins"),
    ]

    operations = [
        migrations.RunPython(
            publish_seasons_with_published_episodes,
            migrations.RunPython.noop,
        ),
    ]
