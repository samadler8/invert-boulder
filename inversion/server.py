"""Local HRRR forecast website. Live samples are collected separately with `hrrr live`."""
from datetime import datetime, timezone
from pathlib import Path
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import ROOT, DATA_DIR, MODEL_DIR, MAX_LEAD_HOURS
from .hrrr import load_jsonl
from .predict import Predictor

app = FastAPI(title='Boulder HRRR Low-Cloud Predictor', version='3.0.0')

@app.get('/')
def index():
    return FileResponse(ROOT/'index.html')

@app.get('/{name}')
def site_file(name: str):
    if name not in ('guide.html','science.html','dashboard.js'):
        raise HTTPException(404,'Not found')
    return FileResponse(ROOT/name)

@app.get('/api/health')
def health():
    return {'status':'ok', 'trained_models_available':(MODEL_DIR/'manifest.json').exists(),
            'forecast_horizon_hours_exclusive':MAX_LEAD_HOURS,
            'live_samples_available':(DATA_DIR/'hrrr_live.jsonl').exists()}

@app.get('/api/forecast')
def forecast(refresh: bool=False):
    path=MODEL_DIR/'manifest.json'
    if not path.exists():
        raise HTTPException(503,'Train HRRR models first: python -m inversion.train --observations ...')
    try:
        predictor=Predictor(MODEL_DIR)
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(503,f'Could not load HRRR model: {exc}') from exc
    rows=load_jsonl(DATA_DIR/'hrrr_live.jsonl')
    now=datetime.now(timezone.utc)
    allowed=set(predictor.manifest['trained_lead_hours'])
    rows=[r for r in rows if int(r['lead_hours']) in allowed
          and datetime.fromisoformat(r['timestamp'].replace('Z','+00:00'))>now]
    if not rows:
        raise HTTPException(503,'No current HRRR samples at trained lead times. Run: python -m inversion.hrrr live --lead-hours 24,30,36')
    issue_times={r['run_utc'] for r in rows}
    if len(issue_times)!=1:
        raise HTTPException(503,'Mixed HRRR issue times in live sample cache; re-run hrrr live')
    for r in rows:
        import numpy as np
        r['features']=np.asarray(r['features'],dtype=np.float32)
        r['profile']=np.asarray(r['profile'],dtype=np.float32)
    result={
        'source':'NOAA HRRR indexed GRIB2 point forecast near KBDU',
        'forecast_run_utc':next(iter(issue_times)),
        'fetched_at_utc':now.isoformat(),
        'model':{
            'target':predictor.manifest['target'],
            'verified_observations':True,
            'warning':predictor.manifest['disclaimer'],
            'test_metrics':predictor.manifest['test_metrics'],
            'cloud_base_available':predictor.manifest['cloud_base']['available'],
            'scenic_available':False,
            'max_lead_hours_exclusive':MAX_LEAD_HOURS,
        },
        'hours':predictor.predict(sorted(rows,key=lambda r:r['timestamp'])),
    }
    return result
