"""Offline HRRR feature/model tests. These are synthetic fixtures, not real weather."""
from datetime import datetime,timedelta,timezone,date
import numpy as np
from pathlib import Path
import json
import pytest
from inversion.hrrr import build_row,historical_pairs,load_jsonl,write_jsonl
from inversion.config import FEATURE_NAMES, PROFILE_CHANNELS,MAX_LEAD_HOURS
from inversion.observations import classify_low_ceiling, parse_iem_csv, save_csv, read_csv
from inversion.hrrr_train import run_training, rows_and_labels, positive_days
from inversion.predict import Predictor


def hrrr_scalars(fog=False):
    s = {('HGT','surface'): 1650.0,('TMP','2 m above ground'):280.0,
         ('DPT','2 m above ground'): 279.5 if fog else 272.0,
         ('RH','2 m above ground'): 98.0 if fog else 50.0,
         ('UGRD','10 m above ground'): 2.0, ('VGRD','10 m above ground'):-3.0,
         ('VIS','surface'): 200.0 if fog else 16000.0,
         ('LCDC','low cloud layer'):95.0 if fog else 12.0,
         ('MCDC','middle cloud layer'):20.0,('HCDC','high cloud layer'):18.0,
         ('HPBL','surface'): 100.0 if fog else 1000.0,
         ('HGT','cloud base'): 1900.0 if fog else 2900.0,
         ('HGT','cloud top'): 2300.0 if fog else 3600.0}
    p = {}
    for pressure,z in zip([800,750,700,650,600],[1950,2420,3000,3550,4250]):
        k=f'{pressure} mb'
        p.update({('HGT',k):z,('TMP',k):282.0-(z-1950)*.004 if fog else 275-(z-1950)*.004,
                  ('RH',k):90.0 if fog else 50.0,
                  ('UGRD',k):3.0,('VGRD',k):-2.0,
                  ('CLWMR',k):0.0003 if fog else 0.000001})
    return s,p


def test_features_and_older_forecast_horizon(tmp_path):
    i=datetime(2025,1,1,tzinfo=timezone.utc)
    s,p=hrrr_scalars(True)
    r=build_row(i,36,s,p)
    assert r['features'] and len(r['features'])==len(FEATURE_NAMES)
    assert np.asarray(r['profile']).shape==(len(PROFILE_CHANNELS),25)
    assert r['lead_hours']==36 and r['observables']['lowClouds']==95
    assert 5000 < r['observables']['forecast_cloud_base_ft_msl'] < 7000
    write_jsonl(tmp_path/'rows.jsonl',[r])
    assert load_jsonl(tmp_path/'rows.jsonl')[0]['timestamp']==r['timestamp']
    a=list(historical_pairs(date(2019,1,1),date(2019,1,2),0,[24,36,39]))
    assert len(a)==4 and max(f for _,f in a)==36
    b=list(historical_pairs(date(2025,1,1),date(2025,1,1),0,[24,36,39]))
    assert len(b)==3


def test_low_ceiling_independent_of_visibility():
    assert classify_low_ceiling({'skyc1':'OVC','skyl1':'400','vsby':'10'})==1
    assert classify_low_ceiling({'skyc1':'CLR','vsby':'1'})==0
    assert classify_low_ceiling({'vsby':'10'}) is None
    raw='station,valid,vsby,skyc1,skyl1,wxcodes\nBDU,2026-06-01 12:06,10.0,OVC,400,\n'
    r=parse_iem_csv(raw)[0]
    assert r['observed_low_ceiling']==1 and r['observed_fog']==0


def generate_fixture(days=160):
    begin=datetime(2025,1,1,tzinfo=timezone.utc)
    rows=[]; labels={}
    for d in range(days):
        init=begin+timedelta(days=d)
        positive=(d%4==0)
        s,p=hrrr_scalars(positive)
        for lead in [24,30,36]:
            row=build_row(init,lead,s,p)
            rows.append(row)
            labels[row['timestamp']]={'fog':int(positive),'low_ceiling':int(positive),
                                      'cloud_base_ft':5900.0 + d*2}
    return rows,labels


def test_train_save_and_predict(tmp_path):
    rows,obs=generate_fixture()
    m=run_training(rows,obs,tmp_path,epochs=1,estimators=20)
    assert m['target']=='observed_airport_low_ceiling'
    assert m['dataset']['positive_days']>3
    assert m['cloud_base']['available']
    results=Predictor(tmp_path).predict([
        {**r,'features':np.asarray(r['features'],dtype=np.float32),
         'profile':np.asarray(r['profile'],dtype=np.float32)} for r in rows[-3:]])
    assert len(results)==3
    assert all(r['cloud_top_ft'] is None for r in results)
    assert all(0<=r['probability']<=1 for r in results)


def test_positive_episode_guard(tmp_path):
    rows,obs=generate_fixture(160)
    for r in rows:
        if r['timestamp'][:4]=='2025' and r['timestamp'][5:7] in ('05','06'):
            obs[r['timestamp']]['low_ceiling']=0
    with pytest.raises(ValueError,match='positive calendar days'):
        run_training(rows,obs,tmp_path,epochs=1,estimators=20)


def test_local_api_using_offline_live_cache(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from inversion import server
    rows, obs = generate_fixture()
    run_training(rows, obs, tmp_path, epochs=1, estimators=20)
    now = datetime.now(timezone.utc)
    issue = now.replace(hour=(now.hour//6)*6, minute=0, second=0, microsecond=0)-timedelta(hours=6)
    s,p = hrrr_scalars(True)
    live = [build_row(issue, lead, s, p) for lead in (24, 30, 36)]
    write_jsonl(tmp_path/'hrrr_live.jsonl', live, mode='w')
    monkeypatch.setattr(server,'DATA_DIR',tmp_path)
    monkeypatch.setattr(server,'MODEL_DIR',tmp_path)
    client=TestClient(server.app)
    assert client.get('/api/health').json()['trained_models_available'] is True
    res=client.get('/api/forecast')
    assert res.status_code == 200, res.text
    body=res.json()
    assert body['model']['target']=='observed_airport_low_ceiling'
    assert all(r['cloud_top_ft'] is None for r in body['hours'])
    assert all(0 <= r['probability'] <=1 for r in body['hours'])
