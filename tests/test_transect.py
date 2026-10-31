"""Offline geographic transect tests: no NOAA access required."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import json
import sys

import pandas as pd
from fastapi.testclient import TestClient

from inversion.hrrr import download_product, build_row, load_jsonl, write_jsonl
from inversion.transect import TRANSECT_POINTS, assemble, relative_humidity_at
from inversion import server
from tests.test_pipeline import hrrr_scalars


def sample_fieldmaps():
    s, p = {}, {}
    for n, (key, _, lat, lon, _) in enumerate(TRANSECT_POINTS):
        ground = 1600 + n*70
        s[key] = {
            ('HGT', 'surface'): ground,
            ('RH', '2 m above ground'): 97-n*4,
            ('LCDC', 'low cloud layer'): 98-n*13,
            ('MCDC', 'middle cloud layer'): 15+n,
            ('HCDC', 'high cloud layer'): 4+n,
            '_grid': {'latitude': lat+0.002, 'longitude': lon-0.001, 'distance_km':.2},
        }
        p[key] = {}
        for level, height in ((800,2100),(750,2650),(700,3120),(650,3600),(600,4200)):
            p[key][('HGT',f'{level} mb')] = height
            p[key][('RH',f'{level} mb')] = 50-n*3
    return {'_transect_fields':s}, {'_transect_fields':p}


def test_location_count_and_precise_coordinates():
    assert len(TRANSECT_POINTS) == 10
    assert next(p for p in TRANSECT_POINTS if p[0]=='flatiron')[4] == 7258
    assert next(p for p in TRANSECT_POINTS if p[0]=='green')[4] == 8133


def test_vertical_rh_height_interpolation_and_missing_range():
    assert relative_humidity_at([(6500,95),(8500,35)], 7500) == 65
    assert relative_humidity_at([(6500,95),(8500,35)], 5500) is None
    assert relative_humidity_at([], 7500) is None
    assert relative_humidity_at([(7500,95),(7500,35)], 7500) is None


def test_assemble_tracks_grid_terrain_and_summit_without_claiming_cloud_top():
    s, p = sample_fieldmaps()
    result=assemble(s,p)
    assert result['version'] == __import__('inversion.transect', fromlist=['TRANSECT_VERSION']).TRANSECT_VERSION
    assert len(result['points'])==len(TRANSECT_POINTS)
    assert result['unique_model_cells']==len(TRANSECT_POINTS)
    g=next(point for point in result['points'] if point['id']=='green')
    assert g['summit_elevation_ft_msl']==8133
    assert g['grid_terrain_ft_msl'] > 5000
    assert g['rh_at_summit_pct'] is not None
    assert all('cloud_top' not in point for point in result['points'])
    assert all(point['grid_distance_km']==.2 for point in result['points'])
    # Missing pressure samples do not become invented height-resolved RH.
    p['_transect_fields']['green']={}
    g=next(point for point in assemble(s,p)['points'] if point['id']=='green')
    assert g['rh_at_summit_pct'] is None


def test_duplicate_cells_declared_not_six_independent_predictions():
    s,p=sample_fieldmaps()
    for item in s['_transect_fields'].values():
        item['_grid']={'latitude':40.0,'longitude':-105.25,'distance_km':1.2}
    result=assemble(s,p)
    assert result['unique_model_cells']==1


def test_hrrr_downloader_reads_grid_values_without_array_materialization(tmp_path,monkeypatch):
    # Two GRIB messages with manually authored metadata, no xarray or full-grid arrays.
    fake_eccodes=ModuleType('eccodes')
    released=[]
    fake_eccodes.codes_grib_new_from_file=lambda stream: ((b:=stream.read(1)) and b[0]) or None
    fake_eccodes.codes_release=lambda gid: released.append(gid)
    fake_eccodes.codes_grib_find_nearest=lambda gid,lat,lon,npoints=1: [SimpleNamespace(
        value=float(gid)+lat-39,lat=lat+.001,lon=lon-.002,distance=.19)]
    monkeypatch.setitem(sys.modules,'eccodes',fake_eccodes)
    fake_herbie=ModuleType('herbie')
    class Herbie:
        def __init__(self,*args,**kwargs):pass
        def inventory(self,search):return pd.DataFrame([
            {'variable':'HGT','level':'surface'},
            {'variable':'RH','level':'2 m above ground'},
        ])
        def download(self,*args,save_dir,**kwargs):
            p=Path(save_dir)/'dummy.grib';p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(bytes([10,20]));return str(p)
    fake_herbie.Herbie=Herbie
    monkeypatch.setitem(sys.modules,'herbie',fake_herbie)
    data=download_product(datetime(2026,10,30,tzinfo=timezone.utc),8,'sfc','anything',tmp_path,transect=True)
    assert len(data['_transect_fields'])==len(TRANSECT_POINTS)
    first=data['_transect_fields']['kbdu']
    assert first[('HGT','surface')] > 10
    assert first['_grid']['latitude'] > 40
    assert ('HGT','surface') in data
    assert released==[10,20]
    assert not (tmp_path/'dummy.grib').exists()


def test_build_row_saves_transect_without_modifying_ml_arrays():
    surface, pressure=hrrr_scalars(True)
    s,p=sample_fieldmaps()
    surface.update(s);pressure.update(p)
    row=build_row(datetime(2026,10,30,tzinfo=timezone.utc),24,surface,pressure)
    assert len(row['features'])==23
    assert len(row['profile'])==4
    assert row['observables']['foothills_transect']['points'][4]['summit_elevation_ft_msl']==7258
    json.dumps(row,allow_nan=True)


def test_transect_refresh_endpoint_enriches_one_existing_hour(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA_DIR',tmp_path)
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    init=now-timedelta(hours=1)
    row=build_row(init,5,*hrrr_scalars(True))
    write_jsonl(tmp_path/'hrrr_live.jsonl',[row],mode='w')
    write_jsonl(tmp_path/'quicklook_forecast_cache.jsonl',[row],mode='w')
    from inversion import hrrr
    s,p=sample_fieldmaps()
    calls=[]
    def fake_download(init,lead,product,pattern,scratch,**kwargs):
        calls.append((product,lead,kwargs))
        return s if product=='sfc' else p
    monkeypatch.setattr(hrrr,'download_product',fake_download)
    client=TestClient(server.app)
    response=client.post('/api/transect/refresh',json={'timestamp':row['timestamp']})
    assert response.status_code==202, response.text
    status=client.get('/api/transect/refresh/status',params={'job_id':response.json()['id']})
    assert status.json()['state']=='complete'
    assert calls[0][0]=='sfc' and calls[1][0]=='prs'
    assert all(kwargs['transect'] for _,_,kwargs in calls)
    live=load_jsonl(tmp_path/'hrrr_live.jsonl')[0]
    cache=load_jsonl(tmp_path/'quicklook_forecast_cache.jsonl')[0]
    assert len(live['observables']['foothills_transect']['points'])==len(TRANSECT_POINTS)
    assert cache['observables']['foothills_transect']==live['observables']['foothills_transect']
    assert len(live['features'])==23
    assert client.post('/api/transect/refresh',json={'timestamp':'not-a-date'}).status_code==400
    # Repeat uses existing sampled values, without downloading again.
    assert client.post('/api/transect/refresh',json={'timestamp':row['timestamp']}).status_code==202
    assert len(calls)==2


def test_dashboard_transect_is_connected_to_time_slider():
    from inversion.config import ROOT
    html=(ROOT/'index.html').read_text()
    js=(ROOT/'dashboard.js').read_text()
    for marker in ('transectMap','transectHeatmap','transectMetric','transectSelectedDetails','transectFetchButton'):
        assert f'id="{marker}"' in html
    assert 'renderFoothillsTransect(currentHourData)' in js
    assert 'fetchSelectedTransect' in js
    assert 'humidity_by_height' in js
    assert 'not a satellite image' in html.lower()
