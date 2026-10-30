"""
================================================================================
APPROACH A: XGBOOST / TABULAR ML MODEL FOR BOULDER INVERSION PREDICTION
================================================================================

[INSTRUCTIONS FOR NEXT LLM]:
1. Replace `generate_synthetic_data()` with actual data loading functions.
   - Surface weather: Use NOAA CDO API or CDPHE station exports for Boulder (e.g., KBDU / Boulder Reservoir).
   - Foothills / Mountain weather: NCAR Foothills Lab or Gold Hill / SNOTEL station data to calculate elevation delta T.
2. Ensure strict temporal alignment: Do NOT use future observation timestamps to predict past inversions.
3. Use TimeSeriesSplit or temporal cross-validation (e.g., train on 2018-2022, test on 2023-2025) 
   rather than standard K-Fold to prevent temporal data leakage.
4. Tune hyperparameters (`scale_pos_weight` in XGBoost is critical because winter inversions represent an imbalanced class).
"""

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score, precision_recall_curve
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb

# ==============================================================================
# 1. FEATURE ENGINEERING & SCHEMA DEFINITION
# ==============================================================================

def create_inversion_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates thermodynamic and meteorological features critical for Front Range inversions.
    
    Expected Raw Input Columns in `df`:
    -----------------------------------
    - `boulder_temp_c`: Surface temp in Boulder (~5,300 ft) [°C]
    - `foothills_temp_c`: Temp at NCAR / Mesa Lab / Gold Hill (~6,000-8,000 ft) [°C]
    - `boulder_dewpoint_c`: Surface dewpoint in Boulder [°C]
    - `boulder_wind_speed_kts`: Surface wind speed [knots]
    - `boulder_wind_dir_deg`: Surface wind direction [degrees]
    - `cloud_cover_pct`: Cloud cover percentage [0-100]
    - `day_of_year`: Day of year [1-365]
    """
    data = df.copy()

    # Feature 1: Temperature Differential (The primary inversion signal)
    # A positive delta (mountain warmer than valley) indicates a temperature inversion
    data['delta_temp_mountain_surface'] = data['foothills_temp_c'] - data['boulder_temp_c']

    # Feature 2: Surface Temperature-Dewpoint Spread (Dewpoint Depression)
    # Small depression + low wind overnight high radiative cooling potential
    data['dewpoint_depression'] = data['boulder_temp_c'] - data['boulder_dewpoint_c']

    # Feature 3: Wind Vector Decomposition (U and V components)
    # Weak surface winds (< 3 kts) prevent mechanical mixing of boundary layer
    radians = np.radians(data['boulder_wind_dir_deg'])
    data['wind_u'] = -data['boulder_wind_speed_kts'] * np.sin(radians)  # East-West
    data['wind_v'] = -data['boulder_wind_speed_kts'] * np.cos(radians)  # North-South

    # Feature 4: Seasonality / Radiative Cooling Capacity
    # Winter months (near day 355) have short solar insolation window = stronger inversions
    data['sin_day'] = np.sin(2 * np.pi * data['day_of_year'] / 365.25)
    data['cos_day'] = np.cos(2 * np.pi * data['day_of_year'] / 365.25)

    # Feature 5: Multi-day Persistence / Rolling Indicators
    # Inversions in Boulder often compound over 2-4 days under high pressure
    data['delta_temp_24h_mean'] = data['delta_temp_mountain_surface'].rolling(window=24, min_periods=1).mean()
    data['surface_wind_24h_max'] = data['boulder_wind_speed_kts'].rolling(window=24, min_periods=1).max()

    return data


# ==============================================================================
# 2. PLACEHOLDER DATA GENERATOR (REPLACE WITH REAL DATA SOURCE)
# ==============================================================================

def generate_synthetic_data(num_samples: int = 5000) -> pd.DataFrame:
    """Generates dummy weather data mirroring Boulder winter dynamics for testing."""
    np.random.seed(42)
    day_of_year = np.random.randint(1, 365, size=num_samples)
    
    boulder_temp = np.random.uniform(-10, 15, size=num_samples)
    # Invert temperatures artificially during winter days
    is_winter = (day_of_year < 60) | (day_of_year > 300)
    foothills_temp = boulder_temp + np.where(is_winter, np.random.uniform(-2, 10, size=num_samples), np.random.uniform(-8, 0, size=num_samples))
    
    df = pd.DataFrame({
        'boulder_temp_c': boulder_temp,
        'foothills_temp_c': foothills_temp,
        'boulder_dewpoint_c': boulder_temp - np.random.uniform(1, 15, size=num_samples),
        'boulder_wind_speed_kts': np.random.uniform(0, 20, size=num_samples),
        'boulder_wind_dir_deg': np.random.uniform(0, 360, size=num_samples),
        'cloud_cover_pct': np.random.uniform(0, 100, size=num_samples),
        'day_of_year': day_of_year
    })

    # Ground truth label: 1 if upper sensor is at least 1.5°C warmer than Boulder surface
    df['inversion_present'] = ((df['foothills_temp_c'] - df['boulder_temp_c']) > 1.5).astype(int)
    return df


# ==============================================================================
# 3. TRAINING & EVALUATION PIPELINE
# ==============================================================================

def train_xgb_inversion_model(df: pd.DataFrame):
    """Processes features, trains XGBoost, and outputs evaluation metrics."""
    # 1. Engineer Features
    df_featured = create_inversion_features(df)
    
    feature_cols = [
        'delta_temp_mountain_surface', 'dewpoint_depression', 'wind_u', 'wind_v',
        'sin_day', 'cos_day', 'delta_temp_24h_mean', 'surface_wind_24h_max', 'cloud_cover_pct'
    ]
    target_col = 'inversion_present'

    X = df_featured[feature_cols]
    y = df_featured[target_col]

    # 2. Temporal Train-Test Split (e.g., 80% train, 20% test)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # Calculate class imbalance ratio for scale_pos_weight
    ratio = float(np.sum(y_train == 0)) / np.sum(y_train == 1)

    # 3. Initialize & Train XGBoost Classifier
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.03,
        scale_pos_weight=ratio,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric='logloss'
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )

    # 4. Evaluation
    y_probs = model.predict_proba(X_test)[:, 1]
    y_preds = (y_probs > 0.5).astype(int)

    print("--- XGBoost Inversion Model Results ---")
    print(f"ROC-AUC Score: {roc_auc_score(y_test, y_probs):.4f}")
    print("\nClassification Report:\n", classification_report(y_test, y_preds))

    return model, feature_cols


if __name__ == "__main__":
    # Test pipeline with dummy data
    raw_data = generate_synthetic_data()
    model, features = train_xgb_inversion_model(raw_data)