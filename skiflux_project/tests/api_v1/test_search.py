import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from skiflux.models import Episode, Season

from .conftest import make_creator, make_verified_user


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def test_user(db):
    return make_verified_user(email="race@example.com")


@pytest.fixture
def test_creator(db):
    return make_creator()


@pytest.mark.django_db
class TestSearchEndpoint:
    def test_search_requires_authentication(self, api_client):
        url = reverse("global-search")
        response = api_client.get(url, {"q": "test"})
        assert response.status_code == 403

    def test_search_validates_short_query(self, test_user, api_client):
        api_client.force_authenticate(user=test_user)
        url = reverse("global-search")
        response = api_client.get(url, {"q": "a"})
        assert response.status_code == 400
        assert "q" in response.data["error"]

    def test_search_returns_paginated_matches(
        self, test_user, api_client, test_creator
    ):
        season = Season.objects.create(
            title="Python Masterclass",
            creator=test_creator,
            skillworld="code",
            is_published=True,
        )
        Episode.objects.create(
            title="Python Basics",
            description="Learn the basics of python.",
            season=season,
            creator=test_creator,
            status=Episode.Status.PUBLISHED,
            order=1,
        )

        api_client.force_authenticate(user=test_user)
        url = reverse("global-search")

        response = api_client.get(url, {"q": "python", "limit": 5, "offset": 0})

        assert response.status_code == 200
        data = response.data

        assert "episodes" in data
        assert data["episodes"]["count"] == 1
        assert len(data["episodes"]["results"]) == 1
        assert data["episodes"]["results"][0]["title"] == "Python Basics"

        assert data["episodes"]["results"][0]["video_url"] is None

        assert "seasons" in data
        assert data["seasons"]["count"] == 1
        assert data["seasons"]["results"][0]["title"] == "Python Masterclass"

        assert data["creators"]["count"] == 0
        assert data["users"]["count"] == 0
