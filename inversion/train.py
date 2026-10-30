"""Historical Open-Meteo acquisition, chronological training and model export."""
import argparse
import csv
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import torch

from .config import (DATA_DIR, MODEL_DIR, FEATURE_NAMES, PROFILE_CHANNELS,
                     PROFILE_LEVELS, PROFILE_TOP_AGL_M, MODEL_VERSION, MODEL_SOURCE)
from .features import rows_from_data, proxy_label
from .weather import fetch_history
from .models import (train_xgb, train_cnn, raw_cnn, platt_fit,
                     platt_apply, metrics)


def observations(path):
    """CSV contains UTC ISO-8601 timestamp (with Z/offset) and observed_event 0/1."""
    result = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Observation timestamp needs UTC offset / Z')
            value = int(r['observed_event'])
            if value not in (0, 1):
                raise ValueError('observed_event must be 0 or 1')
            key = timestamp.astimezone(timezone.utc).replace(minute=0, second=0,
                                                             microsecond=0).isoformat().replace('+00:00', 'Z')
            if key in result:
                raise ValueError(f'Duplicate hour in labels: {key}')
            result[key] = value
    return result


def labeled_rows(responses, labels=None, *, proxy=False):
    all_rows = []
    for response in responses:
        all_rows.extend(rows_from_data(response))
    unique = {r['timestamp']: r for r in all_rows}
    sorted_rows = [unique[k] for k in sorted(unique)]
    good = []
    for r in sorted_rows:
        label = labels.get(r['timestamp']) if labels is not None else proxy_label(r) if proxy else None
        if label is not None:
            good.append((r, int(label)))
    return good


def split_chronological(labeled, *, gap_hours=24):
    n = len(labeled)
    if n < 200:
        raise ValueError(f'Need >=200 labeled hours (got {n}). Gather more historical data.')
    i = int(.7 * n)
    j = int(.85 * n)
    # Purge by actual elapsed time, not index: independent observations can be sparse.
    t1 = datetime.fromisoformat(labeled[i][0]['timestamp'].replace('Z', '+00:00'))
    t2 = datetime.fromisoformat(labeled[j][0]['timestamp'].replace('Z', '+00:00'))
    parse = lambda pair: datetime.fromisoformat(pair[0]['timestamp'].replace('Z', '+00:00'))
    train = [pair for pair in labeled[:i] if parse(pair) < t1 - timedelta(hours=gap_hours)]
    val = [pair for pair in labeled[i:j] if parse(pair) < t2 - timedelta(hours=gap_hours)]
    test = labeled[j:]
    for name, part in [('train', train), ('validation', val), ('test', test)]:
        if len({y for _, y in part}) != 2:
            raise ValueError(f'{name} has only one class; widen date range / improve labels.')
    return train, val, test


def arrays(part):
    return (
        np.stack([r['features'] for r, _ in part]),
        np.stack([r['profile'] for r, _ in part]),
        np.asarray([y for _, y in part], dtype=np.int64),
    )


def train(responses, *, labels=None, allow_proxy=False, model_dir=MODEL_DIR,
          cnn_epochs=25, xgb_estimators=300):
    if labels is None and not allow_proxy:
        raise ValueError('Provide real observation labels or explicitly allow proxy targets.')
    rows = labeled_rows(responses, labels, proxy=allow_proxy)
    trainset, valset, testset = split_chronological(rows)
    x_tr, p_tr, y_tr = arrays(trainset)
    x_va, p_va, y_va = arrays(valset)
    x_te, p_te, y_te = arrays(testset)

    xgb = train_xgb(x_tr, y_tr, x_va, y_va, estimators=xgb_estimators)
    cnn, mean, scale, train_info = train_cnn(p_tr, y_tr, p_va, y_va,
                                            epochs=cnn_epochs)
    xgb_cal = platt_fit(xgb.predict_proba(x_va)[:, 1], y_va)
    cnn_cal = platt_fit(raw_cnn(cnn, p_va, mean, scale), y_va)
    xgb_probs = platt_apply(xgb.predict_proba(x_te)[:, 1], xgb_cal)
    cnn_probs = platt_apply(raw_cnn(cnn, p_te, mean, scale), cnn_cal)
    ensemble_probs = (xgb_probs + cnn_probs) / 2
    report = {
        'xgb': metrics(y_te, xgb_probs), 'cnn': metrics(y_te, cnn_probs),
        'ensemble': metrics(y_te, ensemble_probs),
    }
    manifest = {
        'version': MODEL_VERSION, 'data_model': MODEL_SOURCE,
        'target': 'observed_scenic_fog' if labels is not None else 'modeled_visibility_cloud_proxy',
        'verified_observations': labels is not None,
        'disclaimer': ('Validation uses user-supplied observations.' if labels is not None else
                       'Proxy labels were generated from weather-model output, NOT observed fog/visibility. ' 
                       'Predictions are probability-like proxy scores, not verified real-world odds.'),
        'features': list(FEATURE_NAMES),
        'channels': list(PROFILE_CHANNELS), 'profile_levels': PROFILE_LEVELS,
        'profile_top_agl_m': PROFILE_TOP_AGL_M,
        'training_rows': len(trainset), 'validation_rows': len(valset),
        'test_rows': len(testset),
        'train_time_span_utc': [trainset[0][0]['timestamp'],trainset[-1][0]['timestamp']],
        'test_time_span_utc': [testset[0][0]['timestamp'],testset[-1][0]['timestamp']],
        'calibration': {'xgb': xgb_cal, 'cnn': cnn_cal},
        'test_metrics': report, 'cnn_training': train_info,
    }
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    xgb.save_model(str(model_dir / 'xgb.json'))
    torch.save({'state_dict': cnn.state_dict(),
                'mean': torch.tensor(mean), 'scale': torch.tensor(scale)},
               str(model_dir / 'cnn.pt'))
    (model_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2022, 1, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument('--observations', type=Path,
                        help='UTC timestamp, observed_event CSV, independently observed')
    parser.add_argument('--allow-proxy-labels', action='store_true',
                        help='EXPERIMENTAL: train on weather-model-generated labels instead of observations')
    parser.add_argument('--history-json', type=Path,
                        help='Offline fixture: JSON array of raw Open-Meteo responses')
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--model-dir', type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    if not args.observations and not args.allow_proxy_labels:
        parser.error('Provide --observations labels.csv or --allow-proxy-labels explicitly.')
    if args.history_json:
        responses = json.loads(args.history_json.read_text())
        if isinstance(responses, dict): responses = [responses]
    else:
        responses = fetch_history(args.start, args.end,
                                  cache_dir=DATA_DIR / 'raw')
    labels = observations(args.observations) if args.observations else None
    result = train(responses, labels=labels, allow_proxy=args.allow_proxy_labels,
                   cnn_epochs=args.epochs, model_dir=args.model_dir)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
