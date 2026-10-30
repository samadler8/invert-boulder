"""Safe loading and aligned prediction for both local models."""
import json
from pathlib import Path
import numpy as np
import torch
from xgboost import XGBClassifier
from .config import (MODEL_DIR, FEATURE_NAMES, PROFILE_CHANNELS,
                     PROFILE_LEVELS, PROFILE_TOP_AGL_M, MODEL_VERSION, MODEL_SOURCE)
from .models import ProfileCNN, raw_cnn, platt_apply


class Predictor:
    def __init__(self, model_dir=MODEL_DIR):
        directory = Path(model_dir)
        self.manifest = json.loads((directory / 'manifest.json').read_text())
        m = self.manifest
        expected = (m['version'] == MODEL_VERSION and m['data_model'] == MODEL_SOURCE
                    and m['features'] == list(FEATURE_NAMES)
                    and m['channels'] == list(PROFILE_CHANNELS)
                    and m['profile_levels'] == PROFILE_LEVELS
                    and m['profile_top_agl_m'] == PROFILE_TOP_AGL_M)
        if not expected:
            raise RuntimeError('Saved model contract differs from code. Retrain models.')
        self.xgb = XGBClassifier()
        self.xgb.load_model(str(directory / 'xgb.json'))
        saved = torch.load(str(directory / 'cnn.pt'), map_location='cpu', weights_only=True)
        self.cnn = ProfileCNN()
        self.cnn.load_state_dict(saved['state_dict'])
        self.cnn.eval()
        self.mean = saved['mean'].numpy()
        self.scale = saved['scale'].numpy()

    def predict(self, rows):
        if not rows:
            return []
        x = np.stack([r['features'] for r in rows])
        profiles = np.stack([r['profile'] for r in rows])
        x_probs = platt_apply(self.xgb.predict_proba(x)[:, 1],
                              self.manifest['calibration']['xgb'])
        c_probs = platt_apply(raw_cnn(self.cnn, profiles, self.mean, self.scale),
                              self.manifest['calibration']['cnn'])
        return [
            {'timestamp': r['timestamp'], 'local_time': r['local_time'],
             **r['observables'],
             'xgb_probability': round(float(px), 4),
             'cnn_probability': round(float(pc), 4),
             'probability': round(float((px + pc) / 2), 4),
             # No scientifically defensible cloud-top estimator exists yet.
             'cloud_top_ft': None}
            for r, px, pc in zip(rows, x_probs, c_probs)
        ]
