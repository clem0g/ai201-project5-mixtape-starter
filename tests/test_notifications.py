"""
tests/test_notifications.py — Mixtape

Regression tests for rating notifications (Issue #4).

Before the fix, rate_song() saved the rating but never created a notification,
so the song's original sharer was never told their song had been rated — even
though adding a shared song to a playlist did notify them. These tests lock in
the corrected behavior.
"""

import pytest
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_rating(app):
    """A sharer who shared a song, and a separate rater."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_creates_notification_for_sharer(app, seed_rating):
    """
    Rating another user's shared song creates a 'song_rated' notification for
    the sharer. This is the regression for Issue #4.
    """
    with app.app_context():
        rate_song(seed_rating["rater"].id, seed_rating["song"].id, 5)

        notifs = get_notifications(seed_rating["sharer"].id)
        rating_notifs = [n for n in notifs if n["type"] == "song_rated"]
        assert len(rating_notifs) == 1
        assert "rater" in rating_notifs[0]["body"]


def test_rating_own_song_does_not_notify(app, seed_rating):
    """A user rating their own shared song should not notify themselves."""
    with app.app_context():
        rate_song(seed_rating["sharer"].id, seed_rating["song"].id, 4)

        notifs = get_notifications(seed_rating["sharer"].id)
        rating_notifs = [n for n in notifs if n["type"] == "song_rated"]
        assert rating_notifs == []
