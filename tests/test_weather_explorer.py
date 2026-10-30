"""Offline astronomy, precision elevations, history migration, and dashboard contract."""
from datetime import date, datetime, timezone, timedelta
import json
import sqlite3

from fastapi.testclient import TestClient

from inversion.config import LANDMARKS_FT
from inversion.solar import solar_day
from inversion.server import app
from inversion.history import connect, save_prediction, history_view
from inversion.scenic import VERSION as SCENIC_VERSION
from tests.test_pipeline import hrrr_scalars
from inversion.hrrr import build_row


def test_boulder_sunrise_and_sunset_and_dst():
    oct31 = solar_day(date(2026, 10, 31))
    nov1 = solar_day(date(2026, 11, 1))
    assert oct31['sunrise'].startswith('2026-10-31T07:')
    assert oct31['sunset'].startswith('2026-10-31T18:') or oct31['sunset'].startswith('2026-10-31T17:59')
    assert oct31['sunrise'].endswith('-06:00')
    assert nov1['sunrise'].startswith('2026-11-01T06:')
    assert nov1['sunrise'].endswith('-07:00')
    assert nov1['sunset'].endswith('-07:00')
    for day in (oct31, nov1):
        assert 600 <= day['daylight_minutes'] <= 660
        assert day['civil_dawn'] < day['sunrise'] < day['morning_golden_end']
        assert day['evening_golden_start'] < day['sunset'] < day['civil_dusk']


def test_solar_api_is_offline_and_validates_dates():
    client = TestClient(app)
    response = client.get('/api/solar', params={'date_local':'2026-10-31'})
    assert response.status_code == 200
    assert response.json()['timezone'] == 'America/Denver'
    assert response.json()['coordinates']['latitude'] == 40.015
    assert client.get('/api/solar?date_local=not-a-date').status_code == 400
    assert client.get('/api/solar?date_local=2026-02-29').status_code == 400


def test_precise_elevations_drive_scenic_sites():
    assert LANDMARKS_FT['First Flatiron'] == 7258
    assert LANDMARKS_FT['Green Mountain'] == 8133
    init = datetime(2026, 10, 30, 0, tzinfo=timezone.utc)
    surface, pressure = hrrr_scalars(True)
    from inversion.heuristic import evaluate
    prediction = evaluate(build_row(init, 24, surface, pressure))
    assert next(x['elevation_ft'] for x in prediction['scenic_site_details'] if x['name']=='First Flatiron') == 7258
    assert next(x['elevation_ft'] for x in prediction['scenic_site_details'] if x['name']=='Green Mountain') == 8133
    assert prediction['scenic_version'] == SCENIC_VERSION


def test_old_history_schema_migrates_and_preserves_old_scenic_snapshot(tmp_path):
    db_path = tmp_path / 'history.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valid_utc TEXT NOT NULL, run_utc TEXT NOT NULL,
            lead_hours INTEGER NOT NULL, origin TEXT NOT NULL,
            captured_at_utc TEXT NOT NULL,
            heuristic_version TEXT NOT NULL,
            ml_model_version TEXT NOT NULL DEFAULT '',
            prediction_json TEXT NOT NULL,
            UNIQUE(valid_utc, run_utc, origin, heuristic_version, ml_model_version)
        )''')
        old = {'heuristic_version':'hrrr-setup-index-v3-smooth-sky',
               'scenic_version':'hrrr-scenic-suitability-v2-smooth-sky',
               'scenic_heuristic_score':90, 'scenic_flatiron_score':90}
        db.execute('''INSERT INTO predictions
            (valid_utc,run_utc,lead_hours,origin,captured_at_utc,heuristic_version,ml_model_version,prediction_json)
            VALUES (?,?,?,?,?,?,?,?)''',
            ('2026-10-31T12:00:00Z','2026-10-30T12:00:00Z',24,'reconstructed',
             '2026-10-31T16:00:00Z',old['heuristic_version'],'',json.dumps(old)))
    with connect(db_path) as db:
        old_saved = db.execute('SELECT * FROM predictions').fetchone()
        assert old_saved['scenic_version'] == old['scenic_version']
        assert json.loads(old_saved['prediction_json']) == old
    surface, pressure = hrrr_scalars(True)
    row = build_row(datetime(2026,10,30,12,tzinfo=timezone.utc),24,surface,pressure)
    assert save_prediction(row, origin='reconstructed', db_path=db_path)
    with connect(db_path) as db:
        records = db.execute('SELECT scenic_version,prediction_json FROM predictions ORDER BY id').fetchall()
        assert len(records) == 2
        assert records[0]['scenic_version'] == old['scenic_version']
        assert records[1]['scenic_version'] == SCENIC_VERSION
        assert json.loads(records[0]['prediction_json']) == old


def test_new_explorer_has_range_source_and_uncertainty_notices():
    from inversion.config import ROOT
    html = (ROOT / 'index.html').read_text()
    js = (ROOT / 'dashboard.js').read_text()
    assert 'id="explorerSlider"' in html
    assert 'id="weatherLandscape"' in html
    assert 'id="solarCards"' in html
    assert 'id="forecastMetricsExtended"' in html
    assert '7,258 ft' in html
    assert '8,133 ft' in html
    assert 'oninput="selectAtmosphereFrame(Number(this.value))"' in html
    assert 'NOT cloud top' in js
    assert 'actual sampled forecast hours' in js
