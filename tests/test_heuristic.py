"""Offline tests for honest standalone heuristic and optional ML API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from inversion.config import FEATURE_NAMES
from inversion.heuristic import evaluate, WEIGHTS
from inversion.hrrr import build_row, write_jsonl
from inversion import server
from tests.test_pipeline import hrrr_scalars


def make_row(fog=False):
    i = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    s, p = hrrr_scalars(fog=fog)
    return build_row(i, 24, s, p)


def test_ranking_moist_cloud_calm_higher_than_clear_dry():
    foggy = evaluate(make_row(True))
    clear = evaluate(make_row(False))
    assert 0 <= clear['heuristic_score'] < foggy['heuristic_score'] <= 100
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-10
    assert foggy['heuristic_version']
    assert len(foggy['heuristic_components']) == len(WEIGHTS)
    assert all(site['scenic_probability'] is None for site in foggy['landmarks'])


def test_missing_optional_fields_do_not_create_fake_cloud_top():
    row = make_row(True)
    row['features'][FEATURE_NAMES.index('forecast_pbl_height_m')] = float('nan')
    row['observables']['forecast_cloud_top_ft_msl'] = None
    prediction = evaluate(row)
    assert 0 <= prediction['heuristic_score'] <= 100
    assert prediction['forecast_cloud_top_ft_msl'] is None
    assert all(site['relative_to_modeled_cloud_top'] == 'unknown' for site in prediction['landmarks'])


def test_live_heuristic_without_any_ml_weights(tmp_path, monkeypatch):
    row = make_row(True)
    write_jsonl(tmp_path / 'hrrr_live.jsonl', [row], mode='w')
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no_models')
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    client = TestClient(server.app)
    response = client.get('/api/forecast')
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['heuristic']['available'] is True
    assert payload['model']['ml_available'] is False
    result = payload['hours'][0]
    assert isinstance(result['heuristic_score'], int)
    assert result['ml_probability'] is None
    assert result['xgb_probability'] is None
    assert result['forecast_cloud_top_ft_msl'] is not None


def test_missing_live_cache_returns_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no_models')
    response = TestClient(server.app).get('/api/forecast')
    assert response.status_code == 503
    assert 'python -m inversion.hrrr live' in response.json()['detail']
