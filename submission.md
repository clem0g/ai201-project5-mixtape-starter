# Project 5 — Mixtape Bug Hunt · Submission

Repository branch: `bugfix/mixtape`

All five open issues were reproduced, traced to root cause, fixed, and documented. Each fix is
its own commit. Two new regression tests were added for the two bugs that had no existing test
coverage (Issues #2 and #4).

---

## AI Usage

I used an AI assistant (Claude) throughout, mostly for *navigation and comprehension* of an
unfamiliar codebase rather than for guessing fixes. Specifically:

- **Orientation.** I pasted the `routes/` and `services/` files and asked the assistant to
  summarize what each module was responsible for and to trace the call chain for a couple of
  features (rating a song; viewing a playlist). This is what let me write the codebase map below
  quickly and confidently instead of reading every file cold.
- **Tracing call chains.** For each issue I asked it to confirm the route → service path (e.g.
  `POST /songs/<id>/rate` → `routes/songs.py:rate()` → `notification_service.rate_song()`) so I
  knew which service function to open first.
- **Explaining a specific language detail.** For Issue #1 I asked "what does Python's
  `datetime.weekday()` return for Sunday vs `isoweekday()`?" once I'd already narrowed the bug to
  the `today.weekday() != 6` comparison. The answer (`weekday()` → 6 for Sunday, `isoweekday()`
  → 7) confirmed my reading. I then verified it myself in a Python shell rather than taking it on
  faith.
- **Comparing two code paths.** For Issue #4 I asked it to diff the structure of `add_to_playlist`
  (which notifies) against `rate_song` (which doesn't). That made the missing `create_notification`
  call obvious.

**Where I had to verify or override it.** The AI is only as good as the context it has, and two
pieces of *project documentation* actively point you the wrong way if you trust them over the code:

- The project brief's *example* codebase map claims "there's no separate rating model — the rating
  is stored directly on the Song." That is **false for this repo** — `models.py` clearly defines a
  standalone `Rating` model with a unique `(user_id, song_id)` constraint. It's an illustrative
  example, not a description of this codebase, and an AI that "helpfully" agreed with it would have
  been wrong.
- `README.md`'s "How to Read the Code" lists `notification_service.rate_song()` as the rating
  entry point, which sounds odd (rating logic living in the *notification* service). It turned out
  to be accurate, but it's the kind of thing worth confirming in the code rather than assuming.

For every fix I confirmed the diagnosis by reading the actual function and then by running the
test suite (Issues #1/#3/#5 each have a pre-existing test that fails on the buggy code and passes
after the fix; for #2 and #4 I wrote the tests myself). The AI helped me *read* faster; the
verification was done against the running code and tests.

---

## Codebase Map

*(Written before opening any issue, from reading `models.py`, `app.py`, the routes, the services,
and `seed_data.py`.)*

### Main files and their roles

- **`app.py`** — Flask application factory `create_app()`. Configures a SQLite database
  (`mixtape.db` by default, overridable via `DATABASE_URL`), initializes the shared `SQLAlchemy`
  object `db`, and registers four blueprints with URL prefixes: `songs_bp` → `/songs`,
  `playlists_bp` → `/playlists`, `users_bp` → `/users`, `feed_bp` → `/feed`. Calls
  `db.create_all()` inside an app context.

- **`models.py`** — All SQLAlchemy models plus three association tables:
  - **Models:** `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`.
  - **`friendships`** — self-referential many-to-many on `User` (`user_id`, `friend_id`); seeded
    bidirectionally.
  - **`song_tags`** — many-to-many between `Song` and `Tag`.
  - **`playlist_entries`** — many-to-many between `Playlist` and `Song`, **with an explicit
    `position` integer column** (plus `added_by`, `added_at`). Song order in a playlist is an
    explicit 1-indexed position, not just insertion order — this matters for Issue #5.
  - Ratings are their own model (`Rating`, unique per `user_id`+`song_id`), *not* a field on `Song`.

- **`routes/`** — Thin controllers. Each function parses the request, delegates to a service, and
  formats the JSON response, translating a service `ValueError` into a 404/400.
  - `songs.py` — `/search`, `/<id>`, `POST /<id>/rate`, `POST /<id>/listen`.
  - `playlists.py` — `POST /`, `/<id>`, `GET /<id>/songs`, `POST /<id>/songs`.
  - `users.py` — `/<id>`, `/<id>/streak`, `/<id>/notifications`, `POST /notifications/<id>/read`.
  - `feed.py` — `/<id>/listening-now`, `/<id>/activity`.

- **`services/`** — All business logic lives here, and **all five bugs are here**:
  - `streak_service.py` — `record_listening_event`, `update_listening_streak`, `get_streak`.
  - `feed_service.py` — `get_friends_listening_now`, `get_activity_feed`.
  - `search_service.py` — `search_songs`, `get_song`.
  - `notification_service.py` — `create_notification`, `add_to_playlist`, `rate_song`,
    `get_notifications`, `mark_as_read`.
  - `playlist_service.py` — `create_playlist`, `get_playlist_songs`, `get_playlist`,
    `get_user_playlists`.

- **`seed_data.py`** — Drops and recreates the DB, then inserts 5 users (with starting streaks and
  bidirectional friendships), 10 tags, 13 songs deliberately spanning **0, 1, and 3 tags** (the
  3-tag ones are what expose Issue #3), listening events (3 within the last ~30 min plus 8 older
  ones), `last_listened_at` values for a few users, 3 playlists with positions 1..7, and one
  working `song_added_to_playlist` notification (the reference pattern for Issue #4).

- **`tests/`** — pytest suites using an in-memory SQLite DB. `test_streaks.py`, `test_search.py`,
  and `test_playlists.py` each already contain a test that fails on the buggy code
  (Issues #1, #3, #5 respectively).

### Data flow — rating a song (ties to Issue #4)

`POST /songs/<song_id>/rate` → `routes/songs.py:rate()` parses `user_id` + `score` →
`notification_service.rate_song(user_id, song_id, score)`. `rate_song` validates the score, loads
the `Song` and rater `User`, upserts the `Rating`, and commits. In the *same module*,
`add_to_playlist()` performs the analogous "someone touched your shared song" action and, after
committing, calls `create_notification()` for `song.shared_by`. `rate_song` omits that call — that
asymmetry is the whole of Issue #4.

### Data flow — viewing a playlist (ties to Issue #5)

`GET /playlists/<id>/songs` → `routes/playlists.py:get_songs()` →
`playlist_service.get_playlist_songs()`, which joins `playlist_entries`, orders by
`position` ascending, and returns song dicts. The join/ordering is correct; the returned slice is
where the bug lives.

### Patterns I noticed

- **Thin routes, fat services.** Routes never touch the DB directly (except `users.py`'s simple
  `get_user`); they delegate to a service and map exceptions to HTTP codes.
- **Services own all writes and use `ValueError` as their "not found / invalid input" signal**,
  which routes catch and turn into 404/400.
- **Everything is UTC.** Timestamps are created with `datetime.now(timezone.utc)`, so date/time
  comparisons are all in UTC — relevant to Issues #1 and #2.

---

## Reproduction environment

Setup was the standard flow from the README:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed_data.py
FLASK_APP=app:create_app flask run      # serves at http://127.0.0.1:5000
pytest tests/                           # runs the suite
```

For the endpoint-based reproductions I grabbed seeded IDs from a `flask shell`
(`FLASK_APP=app:create_app flask shell`), e.g.:

```python
from models import User, Song, Playlist
[(u.username, u.id) for u in User.query.all()]
Playlist.query.filter_by(name="Friday Energy").first().id
```

---

## Root Cause Analyses

### Issue #1 — My listening streak keeps resetting
*(`services/streak_service.py`)*

- **How I reproduced it.** `test_streaks.py::test_streak_increments_on_sunday` fails on the
  original code: it records a listen on Saturday (`2024-06-15`, `weekday()==5`) then Sunday
  (`2024-06-16`, `weekday()==6`) and asserts the streak became 2, but the code left it at 1. I also
  confirmed the day-boundary logic in a Python shell: for a Saturday→Sunday pair,
  `days_since_last == 1` is true but the extra guard flips the result to a reset. This matches
  kenji's report exactly ("both times it was a Sunday").

- **How I found the root cause.** I opened `streak_service.py` and read `update_listening_streak`
  top-down. The `days_since_last == 0 / == 1 / else` structure is the standard streak pattern, so
  the only thing that could make a *consecutive* day behave like a *skipped* day was the extra
  condition on the `elif`: `and today.weekday() != 6`. The moment I checked what `weekday()`
  returns — 6 is **Sunday** — it was clear this branch was silently excluding Sundays from the
  "consecutive day" case.

- **The root cause.** Python's `datetime.weekday()` returns `6` for Sunday. The increment branch
  was written as `elif days_since_last == 1 and today.weekday() != 6:`. On any Sunday, `weekday()`
  *is* 6, so the guard is false, the `elif` is skipped, and execution falls through to the `else`
  that resets the streak to 1 — even though the user listened on consecutive days. There is no
  legitimate reason to treat Sunday differently; the guard was spurious.

- **My fix and side-effect check.** I removed the `and today.weekday() != 6` clause, so the branch
  is simply `elif days_since_last == 1:`. I re-ran the whole streak suite: the four previously
  passing tests (new-user start, consecutive weekday increment, same-day no-double-count, skipped-day
  reset) still pass, and `test_streak_increments_on_sunday` now passes. Skip detection is untouched
  (`days_since_last >= 2` still hits the `else`), so genuine gaps still reset correctly.

### Issue #2 — Friends Listening Now shows people from yesterday
*(`services/feed_service.py`)*

- **How I reproduced it.** In a `flask shell` I added a listening event for one of nova's friends
  timestamped one second before today's midnight (i.e. yesterday, 23:59:59 UTC), then called
  `get_friends_listening_now(nova_id)`. That friend appeared in the feed even though their listen
  was yesterday — exactly nova's complaint that darius's 11pm listen still showed at 9am. My new
  `tests/test_feed.py::test_listening_now_excludes_friend_from_yesterday` encodes this.

- **How I found the root cause.** `routes/feed.py:listening_now` delegates straight to
  `get_friends_listening_now`. Reading that function, the recency filter is
  `ListeningEvent.listened_at >= cutoff`, and `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`
  with `RECENT_THRESHOLD = timedelta(hours=24)`. A rolling 24-hour window is precisely the behavior
  nova described ("hangs around until the same time the next day").

- **The root cause.** "Listening now" was implemented as a **rolling 24-hour window** rather than
  "listened today." A listen at 11pm is only ~10 hours old at 9am the next morning, so it stays
  inside a 24-hour window and keeps showing up until 11pm the following day. The feature wants the
  *current calendar day*, not "sometime in the last 24 hours."

- **My fix and side-effect check.** I changed the cutoff from "now minus 24 hours" to the start of
  the current UTC day: `cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)`. I removed
  the now-unused `RECENT_THRESHOLD` constant and the unused `timedelta` import. I verified both
  sides of the boundary with `test_feed.py`: a friend who listened earlier *today* still appears,
  and a friend whose last listen was just before midnight no longer does. `get_activity_feed`
  (which is intentionally *not* recency-filtered) is untouched, so the general activity feed still
  returns the most recent N events.

### Issue #3 — The same song keeps showing up twice in search
*(`services/search_service.py`)*

- **How I reproduced it.** `test_search.py::test_search_no_duplicates_multi_tag_song` fails on the
  original code: searching "Crown Heights" returns the 3-tag song `Crown Heights Anthem` three
  times instead of once. Against the running app, `GET /songs/search?q=Anthem` returns that song
  three times while single-tag and no-tag songs appear once — matching simone's report and the fact
  that the seed data marks the 3-tag songs as "the ones that expose Issue #3."

- **How I found the root cause.** `routes/songs.py:search()` calls `search_songs(query)`. In that
  function the query does `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` before filtering
  on title/artist. The number of duplicates equaling the number of tags (3 tags → 3 rows, 1 tag →
  1 row, 0 tags → 1 row) is the signature of a join fan-out with no de-duplication.

- **The root cause.** The query joins the `song_tags` association table, which has one row per
  (song, tag) pair. A song with N tags therefore produces N result rows, and nothing collapses
  them, so the song is returned N times. The join isn't even needed: the search filters only on
  `title`/`artist`, and tags are loaded separately via the `Song.tags` relationship inside
  `to_dict()`.

- **My fix and side-effect check.** I removed the unnecessary `.outerjoin(song_tags, ...)` (and its
  now-unused imports), so the query selects each matching `Song` exactly once. I re-ran the search
  suite: the multi-tag no-duplicate test now passes, and the single-tag, no-tag, matching, and
  empty-result tests still pass. `to_dict()` still includes the full tag list, so search results
  keep their tags — only the duplication is gone. (An alternative fix is adding `.distinct()`, but
  removing the join addresses the actual cause rather than masking the symptom.)

### Issue #4 — Notified on playlist-add but not on rating
*(`services/notification_service.py`)*

- **How I reproduced it.** With the app running, I had a non-sharer rate a shared song
  (`POST /songs/<song_id>/rate` with `{"user_id": <rater>, "score": 5}`), then checked the sharer's
  notifications (`GET /users/<sharer_id>/notifications`). The rating was saved (visible on the song)
  but no notification existed — matching aaliya's report. Adding the same song to a playlist *did*
  produce a notification, confirming the asymmetry. My new
  `tests/test_notifications.py::test_rating_creates_notification_for_sharer` encodes this.

- **How I found the root cause.** Both actions live in `notification_service.py`, so I read them
  side by side. `add_to_playlist()` ends with a `create_notification(...)` call to `song.shared_by`
  guarded by `if song.shared_by != added_by_user_id`. `rate_song()` validates, upserts the
  `Rating`, commits, and returns — with **no `create_notification` call anywhere**. The pattern for
  a correct notification was right there; the rating path simply never implemented it.

- **The root cause.** This is an architectural omission, not a typo: `rate_song()` persists the
  rating but never creates a `Notification`, so the sharer is never told. The rating endpoint
  therefore "works" (the score is saved) while silently doing nothing about notifications.

- **My fix and side-effect check.** After the rating is committed, I added the same notification
  pattern used by `add_to_playlist`: if the rater isn't the original sharer, call
  `create_notification(user_id=song.shared_by, notification_type="song_rated", body=...)`. I
  verified with `test_notifications.py` that rating another user's song now creates exactly one
  `song_rated` notification for the sharer, and that a user rating their *own* shared song does not
  notify themselves (the `shared_by != user_id` guard, mirroring the playlist path). The rating
  upsert logic and return value are unchanged, so existing rating behavior is preserved.

### Issue #5 — The last song in a playlist never shows up
*(`services/playlist_service.py`)*

- **How I reproduced it.** `test_playlists.py::test_playlist_returns_all_songs` fails on the
  original code: a 5-song playlist returns 4 songs. Against the running app,
  `GET /playlists/<Friday Energy id>/songs` returns 6 of the 7 seeded songs, and the missing one is
  always the highest `position` (most recently added) — matching darius's report that adding a new
  song "frees" the previously missing one and hides the new one instead.

- **How I found the root cause.** `routes/playlists.py:get_songs()` calls `get_playlist_songs()`.
  The query there is correct — it joins `playlist_entries`, filters by `playlist_id`, and orders by
  `position` ascending. The bug is the very last line: `return [song.to_dict() for song in
  songs[:-1]]`. The `[:-1]` slice drops the final element of an ascending-by-position list, which
  is always the last-added song.

- **The root cause.** An off-by-one in the return statement: `songs[:-1]` intentionally excludes the
  last item of the ordered list. Because the list is ordered by ascending `position`, the last item
  is always the most recently added song, so exactly one song — the newest — is always hidden. The
  function's own docstring says it "returns all songs," which the slice contradicts.

- **My fix and side-effect check.** I changed `songs[:-1]` to `songs` so every entry is returned. I
  re-ran the playlist suite: `test_playlist_returns_all_songs` (now 5) and
  `test_playlist_returns_songs_in_order` (all five titles in order) pass, and
  `test_empty_playlist_returns_empty_list` still returns `[]` without error (previously `[][:-1]`
  was also `[]`, so the empty case was never affected). Ordering is unchanged since the `order_by`
  was already correct.

---

## Stretch: Regression tests

Issues #1, #3, and #5 already had a test in the repo that fails on the buggy code and passes after
the fix (`test_streak_increments_on_sunday`, `test_search_no_duplicates_multi_tag_song`,
`test_playlist_returns_all_songs`). The two bugs with **no** existing coverage now have tests:

- **`tests/test_feed.py`** (Issue #2) — asserts a friend who listened earlier today appears in
  "listening now," and a friend whose last listen was just before midnight does **not**. The
  yesterday event is placed one second before midnight so it still falls inside the old rolling
  24-hour window, which is what makes the test fail on the pre-fix code.
- **`tests/test_notifications.py`** (Issue #4) — asserts that rating another user's shared song
  creates exactly one `song_rated` notification for the sharer, and that rating your own song does
  not notify you.

Run everything with `pytest tests/`.

---

## Commit history

Each fix is a separate commit on `bugfix/mixtape`, conventional format:

```
docs: add submission with codebase map and root cause analyses
test: add regression tests for feed recency and rating notifications
fix: return all playlist songs including the most recently added
fix: create notification when a shared song is rated
fix: remove tag join causing duplicate search results
fix: scope listening-now feed to the current calendar day
fix: increment streak on Sunday instead of resetting at week boundary
```

*(Screenshot of `git log --oneline` on the `bugfix/mixtape` branch is attached with the
submission.)*
