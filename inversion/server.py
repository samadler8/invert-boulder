"""Serve the original local web UI and the trained model's forecasts.

Run: python -m uvicorn inversion.server:app --reload
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from .config import ROOT, MODEL_DIR, TIMEZONE
from .features import rows_from_data
from .weather import fetch_live
from .predict import Predictor

app = FastAPI(title='Boulder Inversion Predictor', version='1.0.0')
_lock = threading.RLock()
_cache = {'at': 0.0, 'data': None, 'stamp': None}


def load_predictor():
    if not (MODEL_DIR / 'manifest.json').exists():
        raise HTTPException(503,
            'Models not trained. Run python -m inversion.train --allow-proxy-labels '
            '(experimental), or train with independently observed labels. See README.')
    try:
        return Predictor()
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(503, f'Cannot load model files: {exc}') from exc


@app.get('/')
def index():
    return FileResponse(ROOT / 'index.html')


@app.get('/{name}')
def site_file(name: str):
    if name not in ('guide.html', 'science.html', 'dashboard.js'):
        raise HTTPException(404, 'Not found')
    return FileResponse(ROOT / name)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'trained_models_available': (MODEL_DIR / 'manifest.json').exists()}


@app.get('/api/forecast')
def forecast(refresh: bool = False):
    # No synthetic forecast substitution and no invented probabilities on failure.
    predictor = load_predictor()
    with _lock:
        if (not refresh and _cache['data'] is not None
                and time.monotonic() - _cache['at'] < 1800
                and _cache['stamp'] == (MODEL_DIR / 'manifest.json').stat().st_mtime_ns):
            return _cache['data']
    try:
        data = fetch_live()
        start = datetime.now(ZoneInfo(TIMEZONE)).date()
        end = start + timedelta(days=7)
        rows = [r for r in rows_from_data(data)
                if start <= datetime.fromisoformat(r['local_time']).date() < end]
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(502, f'Weather provider failed: {exc}') from exc
    if len(rows) < 24:
        raise HTTPException(502, 'Insufficient complete pressure-level profiles from weather provider.')
    results = predictor.predict(rows)
    response = {
        'source': 'Open-Meteo GFS global forecast (single model)',
        'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
        'model': {'target': predictor.manifest['target'],
                  'verified_observations': predictor.manifest['verified_observations'],
                  'warning': predictor.manifest['disclaimer'],
                  'test_metrics': predictor.manifest['test_metrics']},
        'hours': results,
    }
    with _lock:
        _cache.update(at=time.monotonic(), data=response,
                      stamp=(MODEL_DIR / 'manifest.json').stat().st_mtime_ns)
    return response
