"""Safe post-processing inference: separate airport fog, cloud base and scenic events."""
import json
from math import exp
from pathlib import Path

import numpy as np
import torch
from xgboost import XGBClassifier, XGBRegressor
from .config import (MODEL_DIR, FEATURE_NAMES, SCENIC_FEATURE_NAMES,
                     PROFILE_CHANNELS, PROFILE_LEVELS, PROFILE_TOP_AGL_M, OBS_STATION_ELEV_FT,
                     MODEL_VERSION, MODEL_SOURCE, MAX_LEAD_HOURS, LANDMARKS_FT)
from .models import ProfileCNN, raw_cnn, platt_apply


class Predictor:
    def __init__(self, model_dir=MODEL_DIR):
        directory = Path(model_dir)
        self.manifest = json.loads((directory / 'manifest.json').read_text())
        m = self.manifest
        valid = (m['version'] == MODEL_VERSION and m['data_model'] == MODEL_SOURCE
                 and m['features'] == list(FEATURE_NAMES)
                 and m['channels'] == list(PROFILE_CHANNELS)
                 and m['profile_levels'] == PROFILE_LEVELS
                 and m['profile_top_agl_m'] == PROFILE_TOP_AGL_M
                 and m['max_lead_hours_exclusive'] == MAX_LEAD_HOURS
                 and m['verified_observations'] is True)
        if not valid:
            raise RuntimeError('Saved model contract differs from observation-trained v2 code. Retrain.')
        self.xgb = XGBClassifier()
        self.xgb.load_model(str(directory / 'xgb.json'))
        saved = torch.load(str(directory / 'cnn.pt'), map_location='cpu', weights_only=True)
        self.cnn = ProfileCNN()
        self.cnn.load_state_dict(saved['state_dict'])
        self.cnn.eval()
        self.mean = saved['mean'].numpy()
        self.scale = saved['scale'].numpy()
        self.base = None
        self.scenic = None
        if m['cloud_base']['available']:
            self.base = XGBRegressor()
            self.base.load_model(str(directory / 'cloud_base.json'))
        if m['scenic']['available']:
            if m['scenic']['features'] != list(SCENIC_FEATURE_NAMES):
                raise RuntimeError('Saved scenic feature schema incompatible')
            self.scenic = XGBClassifier()
            self.scenic.load_model(str(directory / 'scenic.json'))

    def predict(self, rows):
        if not rows:
            return []
        if any(not 0 <= r['lead_hours'] < MAX_LEAD_HOURS for r in rows):
            raise ValueError('Only issue-time leads strictly below 72 hours are permitted')
        x = np.stack([r['features'] for r in rows])
        p = np.stack([r['profile'] for r in rows])
        x_p = platt_apply(self.xgb.predict_proba(x)[:, 1],
                          self.manifest['calibration']['xgb'])
        c_p = platt_apply(raw_cnn(self.cnn, p, self.mean, self.scale),
                          self.manifest['calibration']['cnn'])
        bases = self.base.predict(x) if self.base is not None else [None] * len(rows)
        landmark_probs = {}
        if self.scenic is not None:
            for name, ft in LANDMARKS_FT.items():
                if ft not in self.manifest['scenic']['trained_elevations_ft']:
                    continue  # No out-of-sample altitude extrapolation without validation.
                xr = np.column_stack([x, np.full(len(x), ft, dtype=np.float32)])
                landmark_probs[name] = platt_apply(self.scenic.predict_proba(xr)[:, 1],
                                                    self.manifest['scenic']['calibration'])
        result = []
        for i, row in enumerate(rows):
            # Forecast thermal signal is an NWP diagnostic, not a trained event probability.
            temp_profile = row['profile'][0]
            upward_warming = bool(np.any(np.diff(temp_profile[:8]) > .25))
            base = None if bases[i] is None else max(float(OBS_STATION_ELEV_FT), float(bases[i]))
            spread = float(self.manifest['cloud_base']['validation_80pct_abs_residual_ft']) if base is not None else None
            points = [
                {'name': name, 'elevation_ft': ft,
                 'scenic_probability': round(float(landmark_probs[name][i]), 4)
                 if name in landmark_probs else None}
                for name, ft in LANDMARKS_FT.items()
            ]
            result.append({
                'timestamp': row['timestamp'], 'run_utc': row['run_utc'],
                'lead_hours': row['lead_hours'], 'local_time': row['local_time'],
                **row['observables'],
                'xgb_probability': round(float(x_p[i]), 4),
                'cnn_probability': round(float(c_p[i]), 4),
                'probability': round(float((x_p[i] + c_p[i]) / 2), 4),
                'event': self.manifest['target'],
                'forecast_inversion_warming_signal': upward_warming,
                'estimated_low_cloud_base_ft_msl': round(base) if base is not None else None,
                'cloud_base_80pct_residual_interval_ft_msl': [
                    round(base - spread), round(base + spread)] if base is not None else None,
                'cloud_top_ft': None,  # METAR has no cloud-top observation.
                'landmarks': points,
            })
        return result
