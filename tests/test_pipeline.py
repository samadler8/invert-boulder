"""Only synthetic/weather-API-shaped fixtures; NO real forecast skill claims."""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from inversion.config import HOURLY_FIELDS, PRESSURE_LEVELS
from inversion.features import row_at, rows_from_data, proxy_label, uv
from inversion.train import train, split_chronological
from inversion.predict import Predictor
from inversion.server import app


def fixture_response(n=600):
    initial = datetime(2025, 1, 1, tzinfo=timezone.utc)
    h = {'time': [(initial + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(n)]}
    for key in HOURLY_FIELDS:
        h[key] = []
    for i in range(n):
        positive = i % 37 < 9
        hour = i % 24
        surf = -1 + 4 * math.sin(i / 24)
        values = {
            'temperature_2m': surf,
            'dew_point_2m': surf - (0.4 if positive else 5),
            'relative_humidity_2m': 97 if positive else 62,
            'cloud_cover_low': 85 if positive else 15,
            'cloud_cover_mid': 8 if positive else 65,
            'cloud_cover_high': 10 if positive else 55,
            'wind_speed_10m': 7 if positive else 18,
            'wind_direction_10m': 80 if positive else 260,
            'visibility': 750 if positive else 12000,
        }
        z = [1950, 2460, 3010, 3600, 4260]
        for p, z_p in zip(PRESSURE_LEVELS, z):
            values.update({f'temperature_{p}hPa': surf + (2 if positive else -3) - (z_p - 1950) * .004,
                           f'relative_humidity_{p}hPa': 90 if positive else 55,
                           f'wind_speed_{p}hPa': 10,
                           f'wind_direction_{p}hPa': 90,
                           f'geopotential_height_{p}hPa': z_p})
        for key in HOURLY_FIELDS:
            h[key].append(values[key])
    return {'latitude':40.015,'longitude':-105.27,'elevation':1640,'hourly':h}


def test_feature_schema_and_proxy():
    response = fixture_response(70)
    rows = rows_from_data(response)
    assert len(rows) == 70
    assert rows[0]['features'].shape == (18,)
    assert rows[0]['profile'].shape == (4, 25)
    assert (proxy_label(rows[0]),proxy_label(rows[15])) == (1, 0)
    assert abs(uv(36, 90)[0] + 10) < 1e-6
    response['hourly']['temperature_750hPa'][0] = None
    assert row_at(response, 0) is None
    assert len(rows_from_data(response)) == 69


def test_chronological_training_reload_and_inference(tmp_path):
    data = fixture_response()
    results = train([data], allow_proxy=True, model_dir=tmp_path,
                    cnn_epochs=3, xgb_estimators=25)
    assert results['verified_observations'] is False
    assert results['target'] == 'modeled_visibility_cloud_proxy'
    assert results['test_rows'] > 0
    pred = Predictor(tmp_path)
    rows = rows_from_data(data)
    answer = pred.predict(rows[:5])
    assert len(answer) == 5
    assert all(0 <= x['probability'] <= 1 for x in answer)
    assert answer[0]['cloud_top_ft'] is None
    assert {'cnn.pt','xgb.json','manifest.json'} <= {p.name for p in tmp_path.iterdir()}


def test_app_serves_ui_but_no_untrained_guesses(monkeypatch, tmp_path):
    from inversion import server
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path)
    client = TestClient(app)
    assert client.get('/').status_code == 200
    assert client.get('/dashboard.js').status_code == 200
    assert client.get('/api/health').json()['trained_models_available'] is False
    response = client.get('/api/forecast')
    assert response.status_code == 503
    assert 'Models not trained' in response.json()['detail']


def test_api_with_trained_artifacts_without_network(tmp_path, monkeypatch):
    from inversion import server
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    train([fixture_response()], allow_proxy=True, model_dir=tmp_path,
          cnn_epochs=2, xgb_estimators=15)
    # Build forecast timestamps covering current Boulder 7-day window.
    fake = fixture_response(n=240)
    today = datetime.now(ZoneInfo('America/Denver')).date()
    first_utc = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    fake['hourly']['time'] = [(first_utc + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M')
                              for i in range(240)]
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path)
    monkeypatch.setattr(server, 'Predictor', lambda: Predictor(tmp_path))
    monkeypatch.setattr(server, 'fetch_live', lambda: fake)
    server._cache.update(data=None, at=0, stamp=None)
    client = TestClient(app)
    result = client.get('/api/forecast')
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['model']['verified_observations'] is False
    assert 160 <= len(payload['hours']) <= 170  # 7 local days; DST changes day length
    assert all(h['cloud_top_ft'] is None for h in payload['hours'])
    assert client.get('/api/forecast').json() == payload  # TTL cache
