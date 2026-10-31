"""The combined button refreshes five independent sources in order."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from inversion import server


def test_refresh_all_sequence(monkeypatch):
    calls = []
    import scripts.quicklook as quicklook
    import scripts.refresh_observations as observations
    import inversion.nearby as nearby
    import inversion.nws as nws
    monkeypatch.setattr(nearby, 'refresh_nearby', lambda **kw: calls.append('nearby') or {'stations': 2})
    monkeypatch.setattr(nws, 'refresh_nws', lambda **kw: calls.append('nws') or {'hours': 24})
    monkeypatch.setattr(quicklook, 'update_future', lambda **kw: calls.append('future') or {'fetched': 1})
    monkeypatch.setattr(server, 'history_view', lambda *a, **kw: {
        'comparisons': [{'hours_before_event': h, 'forecast': None}
                        for h in (24, 18, 12, 6, 0)]})
    monkeypatch.setattr(server, 'needs_reconstruction_upgrade', lambda f: True) if hasattr(server,'needs_reconstruction_upgrade') else None
    monkeypatch.setattr(server, 'backfill_event', lambda *a, **kw: calls.append('history') or [{'status':'saved'}])
    monkeypatch.setattr(observations, 'refresh_observations',
                        lambda *a, **kw: calls.append('observations') or {'new_reports': 1})
    client = TestClient(server.app)
    target = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(minute=0,second=0,microsecond=0)
    response = client.post('/api/refresh/all', json={'event_utc': target.isoformat()})
    assert response.status_code == 202
    status = client.get('/api/refresh/all/status', params={'job_id': response.json()['id']})
    assert status.status_code == 200
    assert status.json()['state'] == 'complete'
    assert calls == ['future'] + ['history'] * 5 + ['observations', 'nearby', 'nws']


def test_refresh_all_continues_if_future_fails(monkeypatch):
    calls = []
    import scripts.quicklook as quicklook
    import scripts.refresh_observations as observations
    import inversion.nearby as nearby
    import inversion.nws as nws
    monkeypatch.setattr(nearby, 'refresh_nearby', lambda **kw: calls.append('nearby') or {'stations': 2})
    monkeypatch.setattr(nws, 'refresh_nws', lambda **kw: calls.append('nws') or {'hours': 24})
    def failed_future(**kw):
        calls.append('future')
        raise RuntimeError('simulated NOAA outage')
    monkeypatch.setattr(quicklook, 'update_future', failed_future)
    monkeypatch.setattr(server, 'history_view', lambda *a, **kw: {'comparisons': [
        {'hours_before_event': h, 'forecast': None} for h in (24,18,12,6,0)]})
    monkeypatch.setattr(server, 'backfill_event', lambda *a, **kw: calls.append('history') or [])
    monkeypatch.setattr(observations, 'refresh_observations',
                        lambda *a, **kw: calls.append('observations') or {})
    client = TestClient(server.app)
    target = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(minute=0,second=0,microsecond=0)
    response = client.post('/api/refresh/all', json={'event_utc': target.isoformat()})
    assert response.status_code == 202
    job = client.get('/api/refresh/all/status', params={'job_id': response.json()['id']}).json()
    assert job['state'] == 'complete'
    assert [x['status'] for x in job['results']] == ['error', 'ok', 'ok', 'ok', 'ok']
    assert calls == ['future'] + ['history'] * 5 + ['observations', 'nearby', 'nws']
