"""Exact points / raw readings / NOAA provenance checks without network."""
from datetime import datetime, timezone

from inversion.heuristic import WEIGHTS, evaluate
from inversion.config import FEATURE_NAMES
from inversion.hrrr import build_row
from inversion.history import save_prediction, history_view
from tests.test_pipeline import hrrr_scalars


def fake_row():
    surface, pressure = hrrr_scalars(True)
    return build_row(datetime(2026, 10, 29, 0, tzinfo=timezone.utc), 36,
                     surface, pressure)


def test_explanation_reproduces_original_score_and_links_to_correct_vintage():
    row = fake_row()
    score = evaluate(row)
    breakdown = score['heuristic_breakdown']
    assert [b['key'] for b in breakdown] == list(WEIGHTS)
    assert round(sum(b['weighted_points'] for b in breakdown)) == score['heuristic_score']
    assert abs(sum(b['weighted_points'] for b in breakdown) - score['heuristic_unrounded_score']) < .04
    assert all(b['weight_pct'] > 0 and b['readings'] for b in breakdown)
    assert all(b['weighted_points'] <= b['max_points'] for b in breakdown)
    assert score['forecast_source']['run_utc'] == row['run_utc']
    assert score['forecast_source']['valid_utc'] == row['timestamp']
    assert score['forecast_source']['surface_inventory_url'] == (
        'https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20261029/conus/hrrr.t00z.wrfsfcf36.grib2.idx')
    assert score['forecast_source']['pressure_inventory_url'].endswith('hrrr.t00z.wrfprsf36.grib2.idx')


def test_missing_input_is_disclosed_not_mislabeled_zero():
    row = fake_row()
    row['features'][FEATURE_NAMES.index('forecast_pbl_height_m')] = float('nan')
    result = evaluate(row)
    pbl = next(b for b in result['heuristic_breakdown'] if b['key'] == 'shallow_mixed_layer')
    assert pbl['has_missing_readings'] is True
    assert pbl['factor_score'] == 50.0
    assert pbl['weighted_points'] == 5.0
    assert pbl['readings'][0]['value'] is None


def test_history_saves_point_explanation_and_no_retroactive_recompute(tmp_path):
    row = fake_row()
    db = tmp_path / 'history.sqlite3'
    assert save_prediction(row, db_path=db, origin='reconstructed')
    from inversion.history import connect
    import json
    with connect(db) as con:
        saved = json.loads(con.execute('SELECT prediction_json FROM predictions').fetchone()[0])
    assert saved['heuristic_breakdown']
    assert saved['forecast_source']['run_utc'] == row['run_utc']
    assert saved['heuristic_unrounded_score'] == evaluate(row)['heuristic_unrounded_score']
