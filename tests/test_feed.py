"""
tests/test_feed.py — Mixtape

Regression tests for the "Friends Listening Now" feed logic (Issue #2).

Before the fix, get_friends_listening_now used a rolling 24-hour window, so a
friend whose most recent listen was yesterday evening still showed up the next
morning. These tests lock in the corrected behavior: only listens from the
current calendar day (since midnight UTC) count as "listening now".
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _befriend(user_a, user_b):
    """Make user_b a friend of user_a (bidirectional)."""
    db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=user_b.id))
    db.session.execute(friendships.insert().values(user_id=user_b.id, friend_id=user_a.id))


@pytest.fixture
def seed_feed(app):
    """
    One viewer with two friends:
      - today_friend listened a moment ago (today)  -> should appear
      - yesterday_friend last listened yesterday evening -> should NOT appear
    """
    with app.app_context():
        viewer = User(username="viewer", email="viewer@example.com")
        today_friend = User(username="today_friend", email="today@example.com")
        yesterday_friend = User(username="yesterday_friend", email="yesterday@example.com")
        db.session.add_all([viewer, today_friend, yesterday_friend])
        db.session.flush()

        _befriend(viewer, today_friend)
        _befriend(viewer, yesterday_friend)

        song = Song(title="Neon City", artist="Static Era", shared_by=viewer.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # today_friend: listened just now (always on the current calendar day)
        db.session.add(ListeningEvent(
            user_id=today_friend.id, song_id=song.id, listened_at=now,
        ))
        # yesterday_friend: listened one second before midnight -> yesterday.
        # Kept deliberately close to midnight so it is still inside the old
        # (buggy) rolling 24-hour window, which is what makes this a true
        # regression test: it fails on the pre-fix code and passes after.
        db.session.add(ListeningEvent(
            user_id=yesterday_friend.id, song_id=song.id,
            listened_at=midnight_today - timedelta(seconds=1),
        ))

        db.session.commit()
        yield {"viewer": viewer, "today_friend": today_friend,
               "yesterday_friend": yesterday_friend}


def test_listening_now_includes_friend_who_listened_today(app, seed_feed):
    with app.app_context():
        feed = get_friends_listening_now(seed_feed["viewer"].id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "today_friend" in usernames


def test_listening_now_excludes_friend_from_yesterday(app, seed_feed):
    """
    A friend whose only listen was yesterday evening must not appear, even
    though it was less than 24 hours ago. This is the regression for Issue #2.
    """
    with app.app_context():
        feed = get_friends_listening_now(seed_feed["viewer"].id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "yesterday_friend" not in usernames
