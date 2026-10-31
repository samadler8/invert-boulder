"""Offline forecast-history checks: timestamps, provenance and no hindsight leakage."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from inversion import server
from inversion.history import (as_utc, backfill_event, choose_hrrr_run,
                               history_view, save_prediction)
from inversion.hrrr import build_row, write_jsonl
from tests.test_pipeline import hrrr_scalars


def row_for(init, lead):
    surface, pressure = hrrr_scalars(True)
    return build_row(init, lead, surface, pressure)


def hour_now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def test_actual_capture_not_backdated_to_forecast_issue(tmp_path):
    target = hour_now() - timedelta(hours=3)
    init = target - timedelta(hours=24)
    row = row_for(init, 24)
    db = tmp_path / 'history.sqlite3'
    # Saved 5h before the target, so available at T-4h but not T-6h.
    was_saved = target - timedelta(hours=5)
    assert save_prediction(row, db_path=db, captured_at=was_saved)
    assert not save_prediction(row, db_path=db, captured_at=was_saved)
    response = history_view(db, now=target + timedelta(hours=3), target=target,
                            offsets=(4, 6, 12))
    assert response['selected_event_utc'] == row['timestamp']
    assert response['comparisons'][0]['forecast']['origin'] == 'captured'
    assert response['comparisons'][1]['forecast'] is None
    assert response['comparisons'][2]['forecast'] is None
    assert response['comparisons'][0]['forecast']['heuristic_score'] >= 0


def test_reconstruction_vintage_and_explicit_provenance(tmp_path):
    target = hour_now() - timedelta(hours=6)
    db = tmp_path / 'history.sqlite3'
    calls = []

    def fake_fetch(init, lead, scratch):
        calls.append((init, lead))
        return row_for(init, lead)

    result = backfill_event(target, db_path=db, fetcher=fake_fetch)
    assert len(calls) == 5
    assert all(0 <= lead < 40 for _, lead in calls)
    assert all((target - init) == timedelta(hours=lead) for init, lead in calls)
    assert all(x['status'] == 'saved' for x in result)
    view = history_view(db, now=target + timedelta(hours=6), target=target)
    assert len(view['comparisons']) == 5
    assert all(x['forecast'] is not None for x in view['comparisons'])
    assert all(x['forecast']['origin'] == 'reconstructed' for x in view['comparisons'])
    assert all(x['forecast']['captured_at_utc'] is None for x in view['comparisons'])
    assert 'NOT proof' in view['note']
    # Re-running never requests already reconstructed run/lead pairs.
    backfill_event(target, db_path=db, fetcher=fake_fetch)
    assert len(calls) == 5


def test_reconstructed_never_claimed_available_too_early(tmp_path):
    target = hour_now() - timedelta(hours=2)
    init = target - timedelta(hours=7)
    db = tmp_path / 'history.sqlite3'
    save_prediction(row_for(init, 7), origin='reconstructed', db_path=db)
    view = history_view(db, now=target + timedelta(hours=2), target=target,
                        offsets=(6,))
    # Init only 1h prior to cutoff; publication delay assumed 2h.
    assert view['comparisons'][0]['forecast'] is None


def test_history_api_survives_missing_future_forecast(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no_models')
    target = hour_now() - timedelta(hours=1)
    db = tmp_path / 'forecast_history.sqlite3'
    save_prediction(row_for(target - timedelta(hours=12), 12),
                    db_path=db, captured_at=target - timedelta(hours=7))
    client = TestClient(server.app)
    response = client.get('/api/history')
    assert response.status_code == 200, response.text
    assert response.json()['event_times_utc'] == [target.isoformat().replace('+00:00', 'Z')]
    assert client.get('/api/history?event_utc=2020-01-01T00:00:00Z').status_code == 400
    assert client.get('/api/forecast').status_code == 503


def test_forecast_api_saves_actual_history_without_trained_ml(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no_models')
    init = hour_now() - timedelta(hours=6)
    row = row_for(init, 24)
    write_jsonl(tmp_path / 'hrrr_live.jsonl', [row], mode='w')
    response = TestClient(server.app).get('/api/forecast')
    assert response.status_code == 200, response.text
    # Event hasn't happened yet, but the ledger has recorded the prediction.
    from inversion.history import connect
    with connect(tmp_path / 'forecast_history.sqlite3') as db:
        record = db.execute('SELECT * FROM predictions').fetchone()
    assert record['origin'] == 'captured'
    assert record['valid_utc'] == row['timestamp']
    snapshot = json.loads(record['prediction_json'])
    assert snapshot['heuristic_score'] == response.json()['hours'][0]['heuristic_score']
    assert snapshot['ml_probability'] is None


def test_capture_published_live_preserves_optional_ml_prediction(tmp_path):
    from inversion.history import capture_published_live, connect
    from inversion.hrrr_train import run_training
    from tests.test_pipeline import generate_fixture

    rows, labels = generate_fixture(160)
    run_training(rows, labels, tmp_path, epochs=1, estimators=20)
    live = rows[-1:]
    db = tmp_path / 'history.sqlite3'
    result = capture_published_live(live, db_path=db, model_dir=tmp_path)
    assert result == {'heuristic_saved': 1, 'ml_saved': 1}
    with connect(db) as con:
        snapshots = con.execute('SELECT * FROM predictions ORDER BY ml_model_version').fetchall()
    assert len(snapshots) == 2
    assert not snapshots[0]['ml_model_version']
    assert snapshots[1]['ml_model_version']
    assert json.loads(snapshots[1]['prediction_json'])['ml_probability'] is not None
    assert json.loads(snapshots[0]['prediction_json'])['ml_probability'] is None



def test_selected_hour_backfill_button_api_fills_all_five_cutoffs(tmp_path, monkeypatch):
    """The optional POST fetches only one past hour, not the entire 48h window."""
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    target = hour_now() - timedelta(hours=7)
    db = tmp_path / 'forecast_history.sqlite3'
    # Simulate quicklook's default saved T-6h reconstruction.
    def fake_fetch(init, lead, scratch):
        return row_for(init, lead)
    backfill_event(target, offsets=(6,), db_path=db, fetcher=fake_fetch)
    calls = []

    def intercepted_backfill(event, *, offsets, db_path):
        calls.extend(offsets)
        return backfill_event(event, offsets=offsets, db_path=db_path, fetcher=fake_fetch)

    monkeypatch.setattr(server, 'backfill_event', intercepted_backfill)
    with TestClient(server.app) as client:
        resp = client.post('/api/history/reconstruct', json={'event_utc': target.isoformat()})
        assert resp.status_code == 202, resp.text
        status = client.get('/api/history/reconstruct/status', params={'job_id':resp.json()['id']})
        assert status.status_code == 200
        assert status.json()['state'] == 'complete'
        assert len(status.json()['progress']) == 5
        assert sorted(calls) == [0, 12, 18, 24]
        view = client.get('/api/history', params={'event_utc': target.isoformat()})
        assert view.status_code == 200
        comparisons = view.json()['comparisons']
        assert len(comparisons) == 5
        assert all(v['forecast'] is not None for v in comparisons)
        assert all(v['forecast']['scenic_indicators'] for v in comparisons)
        assert all(v['forecast']['forecast_source'] for v in comparisons)
        # Running again is free; it does not fetch anything already saved.
        again = client.post('/api/history/reconstruct', json={'event_utc': target.isoformat()})
        assert again.status_code == 202
        assert calls == [24, 18, 12, 0]


def test_selected_history_reconstruction_rejects_invalid_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    with TestClient(server.app) as client:
        for event in ['2000-01-01T00:00:00Z',
                      (hour_now() + timedelta(hours=4)).isoformat(),
                      '2026-10-30T08:30:00Z', 'not-a-date']:
            result = client.post('/api/history/reconstruct', json={'event_utc': event})
            assert result.status_code == 400, (event, result.text)
        assert client.get('/api/history/reconstruct/status', params={'job_id':'bogus'}).status_code == 404


def test_legacy_reconstructed_vintages_are_refreshable_without_erasing_original(tmp_path, monkeypatch):
    """Previously archived v1-only reconstructions can be upgraded to scenic v2."""
    from inversion.history import connect, needs_reconstruction_upgrade

    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    target = hour_now() - timedelta(hours=7)
    db = tmp_path / 'forecast_history.sqlite3'

    def fake_fetch(init, lead, scratch):
        return row_for(init, lead)

    backfill_event(target, db_path=db, fetcher=fake_fetch)
    # Simulate the database written before the scenic predictor was installed.
    with connect(db) as con:
        rows = con.execute('SELECT id, prediction_json FROM predictions').fetchall()
        for record in rows:
            snapshot = json.loads(record['prediction_json'])
            for name in list(snapshot):
                if name.startswith('scenic_'):
                    del snapshot[name]
            snapshot['heuristic_version'] = 'hrrr-setup-index-v1'
            con.execute('UPDATE predictions SET heuristic_version=?, prediction_json=? WHERE id=?',
                        ('hrrr-setup-index-v1', json.dumps(snapshot), record['id']))

    view = history_view(db, now=target + timedelta(hours=7), target=target)
    assert all(c['needs_refresh'] for c in view['comparisons'])
    assert all(c['forecast']['heuristic_score'] is not None for c in view['comparisons'])

    calls = []

    def fake_backfill(event, *, offsets, db_path):
        calls.extend(offsets)
        return backfill_event(event, offsets=offsets, db_path=db_path, fetcher=fake_fetch)

    monkeypatch.setattr(server, 'backfill_event', fake_backfill)
    with TestClient(server.app) as client:
        response = client.post('/api/history/reconstruct', json={'event_utc': target.isoformat()})
        assert response.status_code == 202
        status = client.get('/api/history/reconstruct/status',
                            params={'job_id': response.json()['id']}).json()
        assert status['state'] == 'complete'
        assert sorted(calls) == [0, 6, 12, 18, 24]
        newer = client.get('/api/history', params={'event_utc': target.isoformat()}).json()
        assert all(not c['needs_refresh'] for c in newer['comparisons'])
        assert all('scenic_indicators' in c['forecast'] for c in newer['comparisons'])
        assert all(c['forecast']['heuristic_version'] == 'hrrr-setup-index-v3-smooth-sky'
                   for c in newer['comparisons'])
    with connect(db) as con:
        originals = con.execute("SELECT * FROM predictions WHERE heuristic_version='hrrr-setup-index-v1'").fetchall()
        refreshed = con.execute("SELECT * FROM predictions WHERE heuristic_version='hrrr-setup-index-v3-smooth-sky'").fetchall()
    assert len(originals) == 5
    assert len(refreshed) == 5


def test_current_snapshot_with_unresolved_scenic_is_not_retried(tmp_path):
    """Missing meteorological measurements must not cause infinite redownloads."""
    from inversion.history import needs_reconstruction_upgrade
    target = hour_now() - timedelta(hours=6)
    db = tmp_path / 'forecast_history.sqlite3'
    backfill_event(target, offsets=(6,), db_path=db,
                   fetcher=lambda init, lead, scratch: row_for(init, lead))
    old = history_view(db, now=target + timedelta(hours=6), target=target,
                       offsets=(6,))['comparisons'][0]['forecast']
    assert not needs_reconstruction_upgrade(old)
    old['scenic_heuristic_score'] = None
    assert not needs_reconstruction_upgrade(old)
    old['scenic_version'] = 'old-version'
    assert needs_reconstruction_upgrade(old)
