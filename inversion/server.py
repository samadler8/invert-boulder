"""Serve independent HRRR scenic forecasts and observation history.

Run `python -m inversion.hrrr live` separately to refresh the on-disk forecast.
The API never silently substitutes synthetic weather for a failed live fetch.
"""
from datetime import datetime, timezone, timedelta, date
import threading
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import FileResponse

from .config import ROOT, DATA_DIR, MODEL_DIR, DISPLAY_MAX_LEAD_HOURS
from .heuristic import evaluate, VERSION, WEIGHTS
from .scenic import VERSION as SCENIC_VERSION, MAX_DESIRED_DECK_TOP_FT_MSL
from .hrrr import load_jsonl
from .history import DEFAULT_DB, history_view, timeline_view, save_prediction, backfill_event, as_utc, utc_str

app = FastAPI(title='Boulder HRRR Inversion Setup', version='5.0.0')


@app.get('/')
def index():
    return FileResponse(ROOT / 'index.html')


@app.get('/{name}')
def site_file(name: str):
    if name not in ('guide.html', 'science.html', 'dashboard.js'):
        raise HTTPException(404, 'Not found')
    return FileResponse(ROOT / name)


@app.get('/api/solar')
def solar(date_local: str | None = None):
    """Offline Boulder sunrise, sunset, twilight and golden-hour times."""
    from .solar import solar_day
    from zoneinfo import ZoneInfo
    from .config import TIMEZONE
    try:
        day = date.fromisoformat(date_local) if date_local else datetime.now(ZoneInfo(TIMEZONE)).date()
    except ValueError as exc:
        raise HTTPException(400, 'Expected ISO calendar date YYYY-MM-DD') from exc
    return solar_day(day)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'trained_models_available': False,  # Legacy response key; ML archived.
            'forecast_horizon_hours_exclusive': DISPLAY_MAX_LEAD_HOURS,
            'live_samples_available': (DATA_DIR / 'hrrr_live.jsonl').exists(),
            'heuristic_available': True, 'heuristic_version': VERSION,
            'scenic_heuristic_available': True, 'scenic_version': SCENIC_VERSION,
            'history_available': DEFAULT_DB.exists()}


@app.get('/api/forecast')
def forecast(refresh: bool = False):
    # `refresh` maintains compatibility with the existing frontend; the CLI is
    # responsible for downloading new HRRR data (no implicit network call here).
    rows = load_jsonl(DATA_DIR / 'hrrr_live.jsonl')
    now = datetime.now(timezone.utc)
    rows = [r for r in rows if 0 <= int(r['lead_hours']) < DISPLAY_MAX_LEAD_HOURS
            and datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')) > now]
    if not rows:
        raise HTTPException(503, 'No future HRRR samples. Run: python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39')
    runs = {r['run_utc'] for r in rows}
    if len(runs) != 1:
        raise HTTPException(503, 'Mixed HRRR run times. Regenerate the live cache.')
    rows.sort(key=lambda r: r['timestamp'])

    out = []
    for r in rows:
        out.append({
            'timestamp': r['timestamp'], 'run_utc': r['run_utc'],
            'lead_hours': r['lead_hours'], 'local_time': r['local_time'],
            **r['observables'], **evaluate(r),
            'ml_probability': None, 'xgb_probability': None,
            'cnn_probability': None, 'event': None,
            'estimated_low_cloud_base_ft_msl': None,
            'cloud_base_80pct_residual_interval_ft_msl': None,
        })

    # ML pipeline is archived. Forecast scores come solely from public HRRR fields.
    for r, predicted in zip(rows, out):
        save_prediction(r, db_path=DATA_DIR / 'forecast_history.sqlite3',
                        captured_at=now, predicted=predicted,
                        ml_model_version='')

    return {
        'source': 'NOAA HRRR issued GRIB2 point forecast near KBDU',
        'forecast_run_utc': next(iter(runs)),
        'fetched_at_utc': now.isoformat(),
        'heuristic': {
            'available': True, 'version': VERSION, 'weights': WEIGHTS,
            'quantity': '0-100 low-cloud/inversion-setup favorability index, NOT a probability',
            'warning': ('Two separate hand-designed indices: airport low-cloud setup and mountain scenic suitability. '
                        'Neither is a probability. Scenic suitability explicitly penalizes mid/high cloud '
                        'and uses coarse HRRR humidity profiles as an unvalidated proxy for low-deck depth.'),
        },
        'scenic': {
            'available': True, 'version': SCENIC_VERSION,
            'main_landmark': 'Green Mountain',
            'max_desired_deck_top_ft_msl': MAX_DESIRED_DECK_TOP_FT_MSL,
            'quantity': '0-100 mountain above-clouds suitability index (not a probability)',
        },
        # Compatibility metadata for older dashboard clients; never loads model files.
        'model': {
            'ml_available': False, 'target': None, 'verified_observations': False,
            'warning': 'ML archived. Forecasts are public-data heuristic indices, not calibrated probabilities.',
            'test_metrics': None, 'cloud_base_available': False,
            'scenic_available': False, 'max_lead_hours_exclusive': DISPLAY_MAX_LEAD_HOURS,
            'heuristic_display_max_lead_hours_exclusive': DISPLAY_MAX_LEAD_HOURS,
        },
        'hours': out,
    }


@app.get('/api/history')
def history(event_utc: str | None = None):
    """Show five as-of forecasts (T-24,18,12,6,0) and independent METAR when cached."""
    try:
        return history_view(DATA_DIR / 'forecast_history.sqlite3',
                            target=event_utc, window_hours=48)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc



from .history import needs_reconstruction_upgrade

class HistoryRebuildRequest(BaseModel):
    event_utc: str


# A single, bounded, opt-in historical retrieval task per local server process.
# GET requests never contact NOAA. Restarting the server clears task progress,
# but forecast snapshots already saved in SQLite remain intact.
_history_job_lock = threading.Lock()
_history_job = None


def _execute_history_rebuild(target, job_id, db_path):
    global _history_job
    statuses = []
    for offset in (24, 18, 12, 6, 0):
        try:
            existing = history_view(db_path, now=datetime.now(timezone.utc),
                                    window_hours=48, target=target,
                                    offsets=(offset,))['comparisons'][0]['forecast']
            if not needs_reconstruction_upgrade(existing):
                result = {'offset_hours': offset, 'status': 'already_current'}
            else:
                result = backfill_event(target, offsets=(offset,), db_path=db_path)[0]
        except Exception as exc:
            result = {'offset_hours': offset, 'status': 'error',
                      'message': f'{type(exc).__name__}: {exc}'}
        statuses.append(result)
        with _history_job_lock:
            if _history_job is not None and _history_job['id'] == job_id:
                _history_job['progress'] = list(statuses)
    with _history_job_lock:
        if _history_job is not None and _history_job['id'] == job_id:
            _history_job['state'] = 'complete'


@app.post('/api/history/reconstruct', status_code=202)
def reconstruct_history(request: HistoryRebuildRequest, background: BackgroundTasks):
    global _history_job
    try:
        target = as_utc(request.event_utc)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, 'A timezone-aware event_utc is required') from exc
    now = datetime.now(timezone.utc)
    if not (now - timedelta(hours=48) <= target <= now):
        raise HTTPException(400, 'Select an hour within the previous 48 hours')
    if target.minute or target.second or target.microsecond:
        raise HTTPException(400, 'Forecast target must fall on an exact UTC hour')
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job['state'] == 'running':
            raise HTTPException(409, 'Unified refresh is currently running')
    with _history_job_lock:
        if _history_job is not None and _history_job['state'] == 'running':
            raise HTTPException(409, 'A different historical reconstruction is already running')
        job_id = uuid4().hex
        _history_job = {'id': job_id, 'state': 'running', 'event_utc': utc_str(target),
                        'progress': [], 'total_offsets': 5}
    background.add_task(_execute_history_rebuild, target, job_id,
                        DATA_DIR / 'forecast_history.sqlite3')
    return dict(_history_job)


def _execute_observation_refresh(target, job_id, db_path):
    """Explicit opt-in external IEM lookup; never performed during page GET."""
    global _history_job
    try:
        from scripts.refresh_observations import refresh_observations
        # One UTC date provides the selected hour; no download of long archive.
        day = target.date()
        result = refresh_observations(day, day, output=DATA_DIR / 'observed_recent_bdu.csv')
        progress = [{'status': 'saved', **result}]
    except Exception as exc:
        progress = [{'status': 'error', 'message': f'{type(exc).__name__}: {exc}'}]
    with _history_job_lock:
        if _history_job is not None and _history_job['id'] == job_id:
            _history_job['progress'] = progress
            _history_job['state'] = 'complete'


@app.post('/api/history/observation/refresh', status_code=202)
def refresh_observation(request: HistoryRebuildRequest, background: BackgroundTasks):
    """Refresh nearest-hour airport observations only after explicit user action."""
    global _history_job
    try:
        target = as_utc(request.event_utc)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, 'A timezone-aware event_utc is required') from exc
    now = datetime.now(timezone.utc)
    if not (now - timedelta(hours=48) <= target <= now):
        raise HTTPException(400, 'Select an hour within the previous 48 hours')
    if target.minute or target.second or target.microsecond:
        raise HTTPException(400, 'Observation target must fall on an exact UTC hour')
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job['state'] == 'running':
            raise HTTPException(409, 'Unified refresh is currently running')
    with _history_job_lock:
        if _history_job is not None and _history_job['state'] == 'running':
            raise HTTPException(409, 'A historical data retrieval is already running')
        job_id = uuid4().hex
        _history_job = {'id': job_id, 'state': 'running', 'event_utc': utc_str(target),
                        'progress': [], 'total_offsets': 1, 'type': 'observation'}
    background.add_task(_execute_observation_refresh, target, job_id,
                        DATA_DIR / 'forecast_history.sqlite3')
    return dict(_history_job)


@app.get('/api/history/reconstruct/status')
def reconstruction_status(job_id: str):
    with _history_job_lock:
        if _history_job is None or job_id != _history_job['id']:
            raise HTTPException(404, 'No matching reconstruction job on this server')
        return dict(_history_job)

# Unified, on-demand website refresh: future first, then selective history,
# then IEM observations. All network work stays outside GET endpoints.
_refresh_lock = threading.Lock()
_refresh_job = None

class RefreshAllRequest(BaseModel):
    event_utc: str | None = None


def _refresh_set(job_id, **changes):
    global _refresh_job
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job['id'] == job_id:
            _refresh_job.update(changes)


def _run_refresh_all(job_id, target):
    from scripts.quicklook import update_future, update_past
    from scripts.refresh_observations import refresh_observations
    from .history import needs_reconstruction_upgrade
    results = []
    def progress(stage, message):
        _refresh_set(job_id, stage=stage, message=message, results=list(results))
    def attempt(stage, message, fn):
        progress(stage, message)
        try:
            value = fn()
            results.append({'stage': stage, 'status': 'ok', 'result': value})
        except Exception as exc:
            results.append({'stage': stage, 'status': 'error',
                            'message': f'{type(exc).__name__}: {exc}'})
        _refresh_set(job_id, results=list(results))
    try:
        now = datetime.now(timezone.utc)
        # Keep this fast(er) by reusing the durable per-run cache. Future forecasts
        # come first and successful downloads remain saved if a later step fails.
        attempt('future', '1/3 · Checking latest HRRR future forecasts (up to 6 new hours)…',
                lambda: update_future(now=now, step=3, stop_after=6))

        def historical():
            # Fill only the chosen target's five vintages. Other past hours keep
            # their saved T-6 summaries; no unbounded 48h x five-vintage backfill.
            chosen = target
            if chosen is None:
                # Most recent 7 AM Boulder target, for a useful morning comparison.
                from zoneinfo import ZoneInfo
                from .config import TIMEZONE
                local = now.astimezone(ZoneInfo(TIMEZONE))
                event_local = local.replace(hour=7, minute=0, second=0, microsecond=0)
                if event_local > local:
                    event_local -= timedelta(days=1)
                chosen = event_local.astimezone(timezone.utc)
            comps = history_view(DATA_DIR / 'forecast_history.sqlite3',
                                 now=now, target=chosen, offsets=(24,18,12,6,0))['comparisons']
            needed = tuple(c['hours_before_event'] for c in comps
                           if needs_reconstruction_upgrade(c['forecast']))
            result = []
            for number, offset in enumerate(needed, 1):
                progress('history', f'2/3 · Historical forecast {number}/{len(needed)}: T−{offset}h…')
                try:
                    result.extend(backfill_event(chosen, offsets=(offset,),
                                                 db_path=DATA_DIR / 'forecast_history.sqlite3'))
                except Exception as exc:
                    result.append({'offset_hours': offset, 'status': 'error',
                                   'message': f'{type(exc).__name__}: {exc}'})
            return {'target_utc': utc_str(chosen), 'checked': 5,
                    'updated': sum(r.get('status') == 'saved' for r in result), 'results': result}
        attempt('history', '2/3 · Updating historical T−24/18/12/6/0 for selected hour…', historical)

        def observations():
            # Small independent airport observation window, not long-term training.
            start = (now - timedelta(hours=55)).date()
            return refresh_observations(start, now.date(),
                   output=DATA_DIR / 'observed_recent_bdu.csv')
        attempt('observations', '3/3 · Updating actual KBDU airport observations…', observations)
        _refresh_set(job_id, state='complete', stage='complete',
                     message='Refresh completed. Updated local forecast and history views.',
                     results=list(results))
    except Exception as exc:
        _refresh_set(job_id, state='complete', stage='error',
                     message=f'Unexpected refresh error: {type(exc).__name__}: {exc}',
                     results=list(results))


@app.post('/api/refresh/all', status_code=202)
def refresh_everything(request: RefreshAllRequest, background: BackgroundTasks):
    global _refresh_job
    target = None
    if request.event_utc:
        try:
            target = as_utc(request.event_utc)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, 'Invalid event_utc') from exc
        now = datetime.now(timezone.utc)
        if not (now - timedelta(hours=48) <= target <= now) or any((target.minute, target.second, target.microsecond)):
            raise HTTPException(400, 'Choose an exact hour in the past 48 hours')
    with _history_job_lock:
        if _history_job is not None and _history_job['state'] == 'running':
            raise HTTPException(409, 'Another historical retrieval is running')
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job['state'] == 'running':
            raise HTTPException(409, 'Refresh already running')
        job_id = uuid4().hex
        _refresh_job = {'id': job_id, 'state': 'running', 'stage': 'queued',
                        'message': 'Queued', 'results': []}
    background.add_task(_run_refresh_all, job_id, target)
    return dict(_refresh_job)


@app.get('/api/refresh/all/status')
def refresh_everything_status(job_id: str):
    with _refresh_lock:
        if _refresh_job is None or _refresh_job['id'] != job_id:
            raise HTTPException(404, 'Unknown refresh job')
        return dict(_refresh_job)


@app.get('/api/window')
def window():
    """Unified past/future display; GET never downloads data from NOAA."""
    now = datetime.now(timezone.utc)
    past = timeline_view(DATA_DIR / 'forecast_history.sqlite3', now=now, window_hours=48)
    error = None
    try:
        forward = forecast()['hours']
    except HTTPException as exc:
        error = str(exc.detail)
        forward = []
    future_limit = now + timedelta(hours=48)
    forward = [r for r in forward
               if datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')) <= future_limit]
    return {
        'generated_at_utc': now.isoformat().replace('+00:00', 'Z'),
        'past_window_hours': 48, 'future_window_hours': 48,
        'past': past, 'future': forward, 'future_error': error,
        'historical_note': ('Captured = saved by this app before the T-6h cutoff. '
                            'Reconstructed = current heuristic applied later to issued HRRR data; '
                            'a 2-hour publication lag is assumed, not verified.'),
        'future_note': ('Available HRRR extended cycles contain leads 0-48 hours from initialization. '
                        'A recent issued run may end before now + 48h. '
                        'Uncovered hours are unavailable, not estimated.'),
    }


# On-demand enrichment for *existing* future forecasts downloaded before the
# spatial-transect feature. This never downloads all 48h or rewrites history.
class TransectRequest(BaseModel):
    timestamp: str

_transect_lock = threading.Lock()
_transect_job = None


def _run_transect_refresh(job_id, timestamp):
    global _transect_job
    try:
        from .hrrr import (download_product, load_jsonl, write_jsonl)
        from .transect import assemble
        rows = load_jsonl(DATA_DIR / 'hrrr_live.jsonl')
        selected = next((r for r in rows if r.get('timestamp') == timestamp), None)
        if selected is None:
            raise ValueError('Selected forecast is no longer in the live cache')
        if selected.get('observables', {}).get('foothills_transect'):
            note = 'Transect already available for selected forecast.'
        else:
            run = datetime.fromisoformat(selected['run_utc'].replace('Z', '+00:00'))
            lead = int(selected['lead_hours'])
            if lead < 0 or lead >= DISPLAY_MAX_LEAD_HOURS:
                raise ValueError('Forecast lead is outside HRRR display range')
            scratch = DATA_DIR / 'hrrr_tmp'
            surf_pattern = (r':(?:HGT:surface|RH:2 m above ground|'
                            r'LCDC:low cloud layer|MCDC:middle cloud layer|'
                            r'HCDC:high cloud layer):')
            prs_pattern = r':(?:HGT|RH):(?:600|650|700|750|800) mb:'
            sfc = download_product(run, lead, 'sfc', surf_pattern, scratch, transect=True)
            prs = download_product(run, lead, 'prs', prs_pattern, scratch, transect=True)
            transect = assemble(sfc, prs)
            if not transect or not transect.get('points'):
                raise RuntimeError('HRRR did not return usable foothills-grid samples')
            with _transect_lock:
                if _transect_job and _transect_job['id'] == job_id:
                    _transect_job['message'] = 'Saving decoded transect to local forecast cache...'
            # Maintain atomic writes to each local file; never discard other
            # forecast rows or alter historical snapshots in the SQLite archive.
            for filename in ('hrrr_live.jsonl', 'quicklook_forecast_cache.jsonl'):
                destination = DATA_DIR / filename
                if not destination.exists():
                    continue
                updated = load_jsonl(destination)
                changed = False
                for row in updated:
                    if row.get('timestamp') == timestamp and row.get('run_utc') == selected['run_utc']:
                        row.setdefault('observables', {})['foothills_transect'] = transect
                        changed = True
                if changed:
                    stage = destination.with_name(destination.name + '.transect-next')
                    write_jsonl(stage, updated, mode='w')
                    stage.replace(destination)
            note = 'Transect saved for selected forecast. Reloading local weather data will show the map.'
        with _transect_lock:
            if _transect_job and _transect_job['id'] == job_id:
                _transect_job.update(state='complete', message=note)
    except Exception as exc:
        with _transect_lock:
            if _transect_job and _transect_job['id'] == job_id:
                _transect_job.update(state='error', message=f'{type(exc).__name__}: {exc}')


@app.post('/api/transect/refresh', status_code=202)
def refresh_transect(request: TransectRequest, background: BackgroundTasks):
    global _transect_job
    try:
        target = as_utc(request.timestamp)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, 'Expected a valid UTC forecast timestamp') from exc
    if target < datetime.now(timezone.utc) - timedelta(hours=1) or target > datetime.now(timezone.utc) + timedelta(hours=49):
        raise HTTPException(400, 'Select an available near-term forecast hour')
    timestamp = utc_str(target)
    rows = load_jsonl(DATA_DIR / 'hrrr_live.jsonl')
    if not any(r.get('timestamp') == timestamp for r in rows):
        raise HTTPException(404, 'Forecast hour not downloaded. Refresh the future forecast first.')
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job['state'] == 'running':
            raise HTTPException(409, 'A general HRRR refresh is already running')
    with _transect_lock:
        if _transect_job is not None and _transect_job['state'] == 'running':
            raise HTTPException(409, 'A foothills transect download is already running')
        job_id = uuid4().hex
        _transect_job = {'id': job_id, 'state': 'running',
                         'message': 'Downloading only the selected HRRR surface/humidity fields...'}
    background.add_task(_run_transect_refresh, job_id, timestamp)
    return dict(_transect_job)


@app.get('/api/transect/refresh/status')
def transect_refresh_status(job_id: str):
    with _transect_lock:
        if _transect_job is None or _transect_job['id'] != job_id:
            raise HTTPException(404, 'Unknown transect refresh job')
        return dict(_transect_job)
