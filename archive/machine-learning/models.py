"""XGBoost + small 1D-CNN with common probability calibration."""
from copy import deepcopy
import numpy as np
import torch
from torch import nn
from xgboost import XGBClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score, log_loss)

from .config import PROFILE_CHANNELS, PROFILE_LEVELS


class ProfileCNN(nn.Module):
    def __init__(self, channels=len(PROFILE_CHANNELS)):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv1d(channels, 16, 3, padding=1), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(16, 32, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(6),
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(32 * 6, 32),
                                  nn.ReLU(), nn.Dropout(.2), nn.Linear(32, 1))

    def forward(self, profile):
        return self.head(self.body(profile)).squeeze(-1)


def train_xgb(x_train, y_train, x_val, y_val, *, estimators=300):
    pos = max(int(y_train.sum()), 1)
    neg = len(y_train) - pos
    model = XGBClassifier(
        n_estimators=estimators, max_depth=3, learning_rate=.05,
        subsample=.85, colsample_bytree=.9, min_child_weight=4,
        objective='binary:logistic', eval_metric='logloss',
        scale_pos_weight=min(15, max(1.0, neg / pos)),
        tree_method='hist', n_jobs=4, random_state=42,
        early_stopping_rounds=25 if estimators >= 50 else None,
    )
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    return model


def standardizer(profiles):
    means = profiles.mean(axis=(0, 2), keepdims=True).astype(np.float32)
    scales = np.maximum(profiles.std(axis=(0, 2), keepdims=True), 0.001).astype(np.float32)
    return means, scales


def normalize(profiles, mean, scale):
    return ((profiles - mean) / scale).astype(np.float32)


def train_cnn(p_train, y_train, p_val, y_val, *, epochs=25, batch_size=64, patience=6):
    """CPU-compatible; CUDA/MPS opt-in can be added when needed."""
    torch.manual_seed(42)
    mean, scale = standardizer(p_train)
    tr = torch.from_numpy(normalize(p_train, mean, scale))
    va = torch.from_numpy(normalize(p_val, mean, scale))
    tr_y = torch.from_numpy(np.asarray(y_train, dtype=np.float32))
    va_y = torch.from_numpy(np.asarray(y_val, dtype=np.float32))
    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(tr, tr_y),
        batch_size=batch_size, shuffle=True)
    model = ProfileCNN()
    weight = min(15, max(1.0, (len(y_train) - sum(y_train)) / max(sum(y_train), 1)))
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(weight, dtype=torch.float32))
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.001)
    best, best_loss, stalls = None, float('inf'), 0
    for epoch in range(epochs):
        model.train()
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            v_loss = criterion(model(va), va_y).item()
        if v_loss < best_loss - 1e-4:
            best, best_loss, stalls = deepcopy(model.state_dict()), v_loss, 0
        else:
            stalls += 1
            if stalls >= patience:
                break
    model.load_state_dict(best)
    model.eval()
    return model, mean, scale, {'epochs_ran': epoch + 1, 'val_loss': best_loss}


def raw_cnn(model, profiles, mean, scale):
    with torch.no_grad():
        normalized = torch.from_numpy(normalize(profiles, mean, scale))
        return torch.sigmoid(model(normalized)).cpu().numpy().astype(float)


def platt_fit(raw_probs, labels):
    """Calibrate only on untouched, chronologically later validation period."""
    p = np.asarray(raw_probs).clip(1e-5, 1 - 1e-5)
    x = np.log(p / (1-p)).reshape(-1, 1)
    calibrator = LogisticRegression(C=1.0, max_iter=200)
    calibrator.fit(x, labels)
    return [float(calibrator.coef_[0, 0]), float(calibrator.intercept_[0])]


def platt_apply(raw_probs, params):
    p = np.asarray(raw_probs).clip(1e-5, 1 - 1e-5)
    z = params[0] * np.log(p / (1-p)) + params[1]
    return 1 / (1 + np.exp(-np.clip(z, -45, 45)))


def metrics(y_true, probs):
    y_true = np.asarray(y_true)
    probs = np.asarray(probs).clip(1e-7, 1-1e-7)
    values = {
        'count': len(y_true), 'positive_rate': round(float(y_true.mean()), 4),
        'brier': round(float(brier_score_loss(y_true, probs)), 4),
        'log_loss': round(float(log_loss(y_true, probs, labels=[0, 1])), 4),
    }
    if len(set(y_true)) == 2:
        values['roc_auc'] = round(float(roc_auc_score(y_true, probs)), 4)
        values['average_precision'] = round(float(average_precision_score(y_true, probs)), 4)
    return values
