"""Single-index release, independent public sources, and safe retention tests."""
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from inversion import server
from inversion.hrrr import build_row, load_jsonl, write_jsonl
from inversion.heuristic import evaluate
from inversion.opportunity import evaluate_opportunity, VERSION as OPPORTUNITY_VERSION
from inversion.nearby import parse_reports, refresh_nearby
from inversion.nws import normalize, refresh_nws
from inversion.storage import cleanup, forecast_prune
from inversion.transect import TRANSECT_POINTS
from scripts.quicklook import update_future
from tests.test_pipeline import hrrr_scalars
from tests.test_transect import sample_fieldmaps


def weather_row():
    surface, pressure = hrrr_scalars(True)
    s, p = sample_fieldmaps()
    surface.update(s)
    pressure.update(p)
    row = build_row(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
                    24, surface, pressure)
    row['profile'][1] = [97] * 3 + [48] * 22
    return row


def test_single_score_is_versioned_and_not_a_probability():
    row = weather_row()
    evaluated = evaluate(row)
    index = evaluate_opportunity(row, evaluated)
    assert index['opportunity_version'] == OPPORTUNITY_VERSION
    assert 0 <= index['opportunity_score'] <= 100
    assert 'not a calibrated probability' in index['opportunity_note']
    assert index['opportunity_evidence']['unique_hrrr_cells'] == len(TRANSECT_POINTS)
    row['observables']['foothills_transect'] = None
    no_spatial = evaluate_opportunity(row, evaluate(row))
    assert no_spatial['opportunity_evidence']['spatial_modifier'] is None
    assert no_spatial['opportunity_score'] == evaluated['scenic_heuristic_score']
    row['profile'] = []
    assert evaluate_opportunity(row, evaluate(row))['opportunity_score'] is None


def test_new_forecast_api_and_storage_are_local_only(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    write_jsonl(tmp_path/'hrrr_live.jsonl', [weather_row()], mode='w')
    client = TestClient(server.app)
    response = client.get('/api/forecast')
    assert response.status_code == 200
    one = response.json()['hours'][0]
    assert isinstance(one['opportunity_score'], int)
    assert one['opportunity_version'] == OPPORTUNITY_VERSION
    assert client.get('/api/observations/nearby').json()['stations'] == []
    assert client.get('/api/nws').json()['hours'] == []
    assert client.get('/api/storage').json()['history_snapshots'] == 1
    assert client.get('/').status_code == 200


def test_storage_dry_run_and_bounded_deletion(tmp_path):
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    old = {'timestamp': '2026-10-01T00:00:00Z', 'run_utc': '2026-10-01T00:00:00Z', 'lead_hours': 0}
    recent = {'timestamp': '2026-10-29T00:00:00Z', 'run_utc': '2026-10-28T12:00:00Z', 'lead_hours': 12}
    cache = tmp_path/'quicklook_forecast_cache.jsonl'
    write_jsonl(cache, [old, recent, recent], mode='w')
    historical = tmp_path/'hrrr_samples.jsonl'
    historical.write_text('preserve this historic training data!')
    report = cleanup(tmp_path, now=now)
    assert report['files'][0]['removed'] == 2
    assert len(load_jsonl(cache)) == 3
    assert cleanup(tmp_path, now=now, apply=True)['files'][0]['removed'] == 2
    assert load_jsonl(cache) == [recent]
    assert historical.read_text() == 'preserve this historic training data!'

    obs = tmp_path/'observed_recent_bdu.csv'
    obs.write_text('timestamp,station\n2026-08-01T00:00:00Z,BDU\n2026-10-28T00:00:00Z,BDU\n')
    assert cleanup(tmp_path, now=now)['recent_observations']['removed'] == 1
    assert '2026-08-01' in obs.read_text()
    cleanup(tmp_path, now=now, apply=True)
    assert '2026-08-01' not in obs.read_text()

    history = tmp_path/'forecast_history.sqlite3'
    with sqlite3.connect(history) as db:
        db.execute('CREATE TABLE predictions (valid_utc TEXT)')
        db.execute('INSERT INTO predictions VALUES (?)', ('2026-01-01T00:00:00Z',))
    cleanup(tmp_path, now=now, apply=True)
    with sqlite3.connect(history) as db:
        assert db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0] == 1
    assert cleanup(tmp_path, now=now, apply=False, delete_old_history_days=90)['history_rows_to_delete'] == 1
    with sqlite3.connect(history) as db:
        assert db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0] == 1
    cleanup(tmp_path, now=now, apply=True, delete_old_history_days=90)
    with sqlite3.connect(history) as db:
        assert db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0] == 0


def test_truncated_jsonl_does_not_discard_completed_rows(tmp_path):
    path = tmp_path/'cache.jsonl'
    path.write_text('{"run_utc":"ok"}\n{"partially_saved":')
    with pytest.warns(UserWarning, match='incomplete trailing'):
        assert load_jsonl(path) == [{'run_utc': 'ok'}]
    path.write_text('{"broken":\n{"valid":true}\n')
    with pytest.raises(ValueError, match='non-terminal'):
        load_jsonl(path)


def test_nearby_metar_parser_preserves_provenance_and_missing_data():
    data = ('station,valid,vsby,tmpf,relh,skyc1,skyl1,wxcodes,metar\n'
            'BDU,2026-10-30 12:00,0.5,38,100,OVC,400,FG,KBDU 301200Z 1/2SM FG OVC004\n'
            'BJC,2026-10-30 12:00,10,44,70,CLR,,,KBJC 301200Z 10SM CLR\n'
            'BDU,2026-10-30 13:00,1,39,98,BKN,500,BR,KBDU 301300Z 1SM BR BKN005\n')
    rows = parse_reports(data)
    assert [r['station'] for r in rows] == ['BDU', 'BJC']
    assert rows[0]['visibility_miles'] == 1
    assert rows[0]['sky_layers'][0]['height_ft_agl'] == 500
    assert rows[1]['sky_layers'][0]['coverage'] == 'CLR'
    assert rows[1]['sky_layers'][0]['height_ft_agl'] is None
    assert all('Iowa Environmental Mesonet' in row['source'] for row in rows)


def test_nws_hourly_guidance_is_separate_and_validated(tmp_path):
    raw={'properties':{'periods':[{'startTime':'2026-10-31T07:00:00-06:00',
      'shortForecast':'Patchy fog then mostly sunny', 'temperature':40,'temperatureUnit':'F',
      'windSpeed':'4 mph','windDirection':'N','probabilityOfPrecipitation':{'value':10}}]}}
    result=normalize(raw)
    assert result['hours'][0]['timestamp_utc']=='2026-10-31T13:00:00Z'
    assert result['hours'][0]['summary']=='Patchy fog then mostly sunny'
    class Response:
        def __init__(self, payload):self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    class Client:
        def __init__(self):self.calls=[]
        def get(self,url,**kw):
            self.calls.append(url)
            if '/points/' in url:
                return Response({'properties':{'forecastHourly':'https://api.weather.gov/gridpoints/BOU/1,2/forecast/hourly'}})
            return Response(raw)
    c=Client()
    from inversion.nws import cached_nws
    path=tmp_path/'nws.json'
    assert refresh_nws(client=c, output=path)['hours']==1
    assert len(c.calls)==2
    assert cached_nws(path)['hours'][0]['summary'].startswith('Patchy')
    class BadClient(Client):
        def get(self,url,**kw):
            return Response({'properties':{'forecastHourly':'https://untrusted.example.com/forecast'}})
    with pytest.raises(ValueError, match='untrusted'):
        refresh_nws(client=BadClient(),output=path)
    assert len(cached_nws(path)['hours'])==1  # last good cache survives


def test_ui_is_pure_real_data_and_single_score():
    from inversion.config import ROOT
    html=(ROOT/'index.html').read_text()
    js=(ROOT/'dashboard.js').read_text()
    assert 'Boulder inversion opportunity' in html
    assert 'id="opportunityScore"' in html
    assert 'id="nwsSummary"' in html
    assert 'id="nearbyStations"' in html
    assert 'SYNTHETIC UI DEMOS' not in html
    assert 'loadPreset(' not in js
    assert 'Green Mountain scenic index' not in html
    assert '0–100' in html or '0–100' in js


def test_spatial_modifier_uses_distinct_model_grid_cells():
    row = weather_row()
    baseline = evaluate(row)
    original = row['observables']['foothills_transect']
    for p in original['points']:
        if p['id'] in ('kbdu', 'east_boulder', 'downtown'):
            p['grid_id'] = 'same-hrrr-cell'
    changed = evaluate_opportunity(row, baseline)
    assert changed['opportunity_evidence']['spatial_modifier'] is None
    assert any('Fewer than two distinct' in x for x in changed['opportunity_evidence']['data_issues'])

def test_finalize_checkout_archives_without_touching_data(tmp_path):
    from scripts.finalize_checkout import run
    (tmp_path/'inversion').mkdir()
    (tmp_path/'data').mkdir()
    (tmp_path/'models').mkdir()
    (tmp_path/'inversion'/'predict.py').write_text('older model')
    (tmp_path/'FOOTHILLS_TRANSECT.md').write_text('older docs')
    (tmp_path/'data'/'hrrr_samples.jsonl').write_text('keep me')
    (tmp_path/'models'/'manifest.json').write_text('keep me')
    assert len(run(tmp_path)) == 2
    assert (tmp_path/'archive/machine-learning/legacy-checkout/predict.py').read_text() == 'older model'
    assert (tmp_path/'archive/release-notes/FOOTHILLS_TRANSECT.md').read_text() == 'older docs'
    assert (tmp_path/'data/hrrr_samples.jsonl').read_text() == 'keep me'
    assert (tmp_path/'models/manifest.json').read_text() == 'keep me'
    assert not run(tmp_path)
