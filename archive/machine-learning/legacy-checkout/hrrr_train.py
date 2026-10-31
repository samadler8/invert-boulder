"""Train the HRRR postprocessor using independent KBDU METAR labels.

Training inputs MUST come from inversion.hrrr.collect and be matched by valid UTC
hour to the observation CSV. Duplicate valid hours from different runs stay in
same chronological partition. No class balancing by inventing observations.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor

from .config import (FEATURE_NAMES, PROFILE_CHANNELS, PROFILE_LEVELS,
                     PROFILE_TOP_AGL_M, MODEL_SOURCE, MODEL_VERSION,
                     MODEL_DIR, MAX_LEAD_HOURS, OBS_STATION_ELEV_FT)
from .hrrr import load_jsonl
from .observations import read_csv
from .models import (train_xgb, train_cnn, raw_cnn, platt_fit,
                     platt_apply, metrics)


def rows_and_labels(records, observations, target='low_ceiling'):
    if target not in ('low_ceiling', 'fog'):
        raise ValueError('Supported targets: low_ceiling or fog')
    result = []
    seen = set()
    for row in records:
        key = (row['timestamp'], row['run_utc'])
        if key in seen:
            raise ValueError(f'Duplicate forecast-run + valid-time pair: {key}')
        seen.add(key)
        if not 0 <= row['lead_hours'] < MAX_LEAD_HOURS:
            continue
        obs = observations.get(row['timestamp'])
        if obs is None or obs.get(target) is None:
            continue
        transformed = dict(row)
        transformed['features'] = np.asarray(row['features'], dtype=np.float32)
        transformed['profile'] = np.asarray(row['profile'], dtype=np.float32)
        if transformed['features'].shape != (len(FEATURE_NAMES),):
            raise ValueError('HRRR feature schema changed; rebuild cached rows')
        if transformed['profile'].shape != (len(PROFILE_CHANNELS), PROFILE_LEVELS):
            raise ValueError('HRRR CNN channel schema changed; rebuild cached rows')
        if not np.isfinite(transformed['profile']).all():
            raise ValueError('NaN in CNN profile')
        result.append((transformed, int(obs[target])))
    return sorted(result, key=lambda q: (q[0]['timestamp'], q[0]['run_utc']))


def chronological_split(pairs, gap_hours=MAX_LEAD_HOURS):
    valid_times = sorted({r['timestamp'] for r, _ in pairs})
    if len(valid_times) < 90:
        raise ValueError(f'Only {len(valid_times)} uniquely verified hours; need at least 90')
    p1 = datetime.fromisoformat(valid_times[int(len(valid_times)*0.70)].replace('Z','+00:00'))
    p2 = datetime.fromisoformat(valid_times[int(len(valid_times)*0.85)].replace('Z','+00:00'))
    dt = lambda r: datetime.fromisoformat(r['timestamp'].replace('Z','+00:00'))
    tr = [(r,y) for r,y in pairs if dt(r) < p1-timedelta(hours=gap_hours)]
    va = [(r,y) for r,y in pairs if p1 <= dt(r) < p2-timedelta(hours=gap_hours)]
    te = [(r,y) for r,y in pairs if dt(r) >= p2]
    return tr, va, te


def positive_days(part):
    return len({row['timestamp'][:10] for row,y in part if y == 1})


def to_arrays(part):
    return (np.stack([r['features'] for r,_ in part]),
            np.stack([r['profile'] for r,_ in part]),
            np.asarray([y for _,y in part], dtype=np.int64))


def cloud_base_model(records, observations, dest, min_unique_hours=90):
    unique = {}
    for row in records:
        obs = observations.get(row['timestamp'])
        if obs is not None and obs.get('cloud_base_ft') is not None:
            x = np.asarray(row['features'], dtype=np.float32)
            unique[(row['timestamp'],row['run_utc'])] = (row, float(obs['cloud_base_ft']))
    pairs = sorted(unique.values(),key=lambda p:p[0]['timestamp'])
    if len({r['timestamp'] for r,_ in pairs}) < min_unique_hours:
        return {'available':False,'reason':'Insufficient unique independently reported cloud-base hours'}
    tr, va, te = chronological_split(pairs)
    if min(map(len,(tr,va,te))) < 15:
        return {'available':False,'reason':'Insufficient independent cloud-base examples after temporal splits'}
    xtr=np.stack([r['features'] for r,_ in tr]); ytr=np.asarray([y for _,y in tr])
    xva=np.stack([r['features'] for r,_ in va]); yva=np.asarray([y for _,y in va])
    xte=np.stack([r['features'] for r,_ in te]); yte=np.asarray([y for _,y in te])
    reg=XGBRegressor(n_estimators=180,max_depth=3,learning_rate=.04,
                     tree_method='hist',n_jobs=4,random_state=42)
    reg.fit(xtr,ytr)
    residual=np.abs(reg.predict(xva)-yva)
    margin=float(np.quantile(residual,.8))
    dest.mkdir(parents=True,exist_ok=True)
    reg.save_model(str(dest/'cloud_base.json'))
    return {'available':True,'target':'reported KBDU cloud BASE, feet MSL; conditional on reported ceiling',
            'validation_80pct_abs_residual_ft':margin,
            'test_mae_ft':float(mean_absolute_error(yte,reg.predict(xte))),
            'distinct_valid_hours':len({r['timestamp'] for r,_ in pairs}),
            'warning':'Airport cloud base is not cloud top or scenic clearance.'}


def run_training(rows, observations, dest, target='low_ceiling', epochs=25, estimators=300,
                 base_only=False):
    dest=Path(dest)
    dest.mkdir(parents=True,exist_ok=True)
    base=cloud_base_model(rows, observations, dest)
    if base_only:
        (dest/'cloud_base_report.json').write_text(json.dumps(base,indent=2)+'\n')
        return {'cloud_base':base, 'note':'Other models not trained by --base-only'}
    pairs=rows_and_labels(rows,observations,target)
    if len(pairs) < 200:
        raise ValueError(f'Only {len(pairs)} labeled forecast examples. Fetch a longer historical period.')
    tr,va,te=chronological_split(pairs)
    for name,part in [('train',tr),('validation',va),('test',te)]:
        days=positive_days(part)
        if days < 3:
            raise ValueError(f'{name} has only {days} independent positive calendar days; '
                             'collect more winters before fitting probabilities')
    xtr,ptr,ytr=to_arrays(tr)
    xva,pva,yva=to_arrays(va)
    xte,pte,yte=to_arrays(te)
    xgb=train_xgb(xtr,ytr,xva,yva,estimators=estimators)
    cnn,mean,scale,details=train_cnn(ptr,ytr,pva,yva,epochs=epochs)
    xc=platt_fit(xgb.predict_proba(xva)[:,1],yva)
    cc=platt_fit(raw_cnn(cnn,pva,mean,scale),yva)
    xp=platt_apply(xgb.predict_proba(xte)[:,1],xc)
    cp=platt_apply(raw_cnn(cnn,pte,mean,scale),cc)
    ens=(xp+cp)/2
    report={'xgb':metrics(yte,xp),'cnn':metrics(yte,cp),'ensemble':metrics(yte,ens)}
    seen_leads=sorted({int(r['lead_hours']) for r,_ in pairs})
    manifest={
        'version':MODEL_VERSION, 'data_model':MODEL_SOURCE,
        'target':'observed_airport_'+target, 'verified_observations':True,
        'observation_station':'KBDU / Boulder Municipal Airport',
        'max_lead_hours_exclusive':MAX_LEAD_HOURS,
        'weather_archive':'NOAA HRRR issued GRIB2 cycles via Herbie indexed subsets',
        'features':list(FEATURE_NAMES), 'channels':list(PROFILE_CHANNELS),
        'profile_levels':PROFILE_LEVELS,'profile_top_agl_m':PROFILE_TOP_AGL_M,
        'calibration':{'xgb':xc,'cnn':cc},'cnn_training':details,
        'cloud_base':base,
        'scenic':{'available':False,'reason':'No independently verified summit image labels'},
        'trained_lead_hours':seen_leads,
        'test_metrics':report,
        'dataset':{'distinct_valid_hours':len({r['timestamp'] for r,_ in pairs}),
                   'rows':len(pairs),'positive_days':positive_days(pairs),
                   'train_positive_days':positive_days(tr),
                   'validation_positive_days':positive_days(va),
                   'test_positive_days':positive_days(te)},
        'disclaimer':('Experimental HRRR-based, observation-trained airport low ceiling/fog. '
                      'NOT a verified temperature inversion or mountain-above-cloud probability. '
                      'Calibration is preliminary and rare weather events may be underrepresented.'),
    }
    xgb.save_model(str(dest/'xgb.json'))
    torch.save({'state_dict':cnn.state_dict(),'mean':torch.tensor(mean),
                'scale':torch.tensor(scale)}, str(dest/'cnn.pt'))
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--features',type=Path,default=Path('data/hrrr_samples.jsonl'))
    ap.add_argument('--observations',type=Path,required=True)
    ap.add_argument('--target',choices=['low_ceiling','fog'],default='low_ceiling')
    ap.add_argument('--model-dir',type=Path,default=MODEL_DIR)
    ap.add_argument('--epochs',type=int,default=25)
    ap.add_argument('--base-only',action='store_true')
    a=ap.parse_args()
    result=run_training(load_jsonl(a.features),read_csv(a.observations),a.model_dir,
                        target=a.target,epochs=a.epochs,base_only=a.base_only)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
