"""Offline 48-hour quicklook tests; NOAA fetching replaced with fixed fixtures."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from inversion import server
from inversion.config import MAX_LEAD_HOURS, DISPLAY_MAX_LEAD_HOURS
from inversion.history import timeline_view, save_prediction, utc_str
from inversion.hrrr import build_row, load_jsonl, write_jsonl
from scripts.quicklook import (hourly_targets, issue_cycle, update_future,
                               update_past)
from tests.test_pipeline import hrrr_scalars


def fixture_row(init, lead):
    return build_row(init, lead, *hrrr_scalars(True))


def test_hrrr_forecast_display_48_without_changing_ml_contract():
    assert MAX_LEAD_HOURS == 40  # previously trained ML remains unchanged
    assert DISPLAY_MAX_LEAD_HOURS == 49
    init = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    row = fixture_row(init, 48)
    assert row['lead_hours'] == 48
    assert row['timestamp'] == '2026-11-01T12:00:00Z'


def test_sampling_spans_past_and_future_including_local_mornings():
    now = datetime(2026, 10, 30, 18, 18, tzinfo=timezone.utc)
    assert issue_cycle(now) == datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    past = hourly_targets(now, 48, 6, future=False)
    future = hourly_targets(now, 48, 6, future=True)
    assert past and future
    assert all(now - timedelta(hours=48) <= t <= now for t in past)
    assert all(now < t <= now + timedelta(hours=48) for t in future)
    assert any(t.astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).hour == 7
               for t in future)


def test_timeline_rejects_post_event_capture(tmp_path):
    now = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    target = now - timedelta(hours=27)
    row = fixture_row(target - timedelta(hours=20), 20)
    db = tmp_path / 'history.sqlite3'
    save_prediction(row, db_path=db, origin='captured',
                    captured_at=target - timedelta(hours=3))  # too late for T-6
    assert timeline_view(db, now=now) == []
    assert save_prediction(row, db_path=db, origin='reconstructed')
    view = timeline_view(db, now=now)
    assert len(view) == 1
    assert view[0]['origin'] == 'reconstructed'
    assert view[0]['timestamp'] == utc_str(target)


def test_future_sampler_resume_from_partial_cache(tmp_path):
    now = datetime(2026, 10, 30, 18, 18, tzinfo=timezone.utc)
    calls = []

    def fake_fetch(init, lead, scratch):
        calls.append((init, lead))
        return fixture_row(init, lead)

    cache = tmp_path / 'sample_cache.jsonl'
    live = tmp_path / 'live.jsonl'
    first = update_future(now=now, step=6, cache=cache, live=live,
                          fetcher=fake_fetch, stop_after=3)
    assert first['fetched'] == 3
    assert len(load_jsonl(live)) == 3
    second = update_future(now=now, step=6, cache=cache, live=live,
                           fetcher=fake_fetch, stop_after=3)
    assert second['fetched'] == 3
    assert len(load_jsonl(live)) == 6
    assert len(set(calls)) == 6
    third = update_future(now=now, step=6, cache=cache, live=live,
                          fetcher=fake_fetch)
    assert third['failed'] == 0
    assert third['available'] > 6
    assert max(r['lead_hours'] for r in load_jsonl(live)) <= 48


def test_past_sampler_reconstructs_without_refetch(tmp_path):
    now = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    db = tmp_path / 'history.sqlite3'
    calls = []

    def fake_fetch(init, lead, scratch):
        calls.append((init, lead))
        return fixture_row(init, lead)

    result = update_past(now=now, step=12, db_path=db, fetcher=fake_fetch)
    assert result['saved'] > 3
    assert len(timeline_view(db, now=now)) == result['saved']
    again = update_past(now=now, step=12, db_path=db, fetcher=fake_fetch)
    assert again['saved'] == 0
    assert len(calls) == result['saved']


def test_api_window_does_not_require_training_or_live(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no-model')
    client = TestClient(server.app)
    empty = client.get('/api/window')
    assert empty.status_code == 200
    assert empty.json()['past'] == [] and empty.json()['future'] == []
    assert empty.json()['future_error']
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    init = now - timedelta(hours=6)
    row = fixture_row(init, 48)  # beyond original 40h ML contract
    write_jsonl(tmp_path / 'hrrr_live.jsonl', [row], mode='w')
    live = client.get('/api/window')
    assert live.status_code == 200, live.text
    assert len(live.json()['future']) == 1
    assert live.json()['future'][0]['lead_hours'] == 48
    assert live.json()['future'][0]['scenic_heuristic_score'] is not None
