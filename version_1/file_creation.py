# ==========================================================
# AUTONOMOUS FINOPS – LIVE INFERENCE ENGINE
# Uses persisted .pkl & .keras artifacts
# ==========================================================

import pandas as pd
import numpy as np
import joblib
import tensorflow as tf
from tensorflow.keras.models import load_model

ARTIFACT_DIR = "./finops_artifacts"

ZOMBIE_MODEL_PATH = f"{ARTIFACT_DIR}/zombie_model.pkl"
ZOMBIE_SCALER_PATH = f"{ARTIFACT_DIR}/zombie_scaler.pkl"

FORECAST_MODEL_PATH = f"{ARTIFACT_DIR}/forecast_lstm.keras"
FORECAST_SCALER_PATH = f"{ARTIFACT_DIR}/forecast_scaler.pkl"


# ==========================================================
# 1. LOAD TRAINED ARTIFACTS
# ==========================================================
def load_models():
    zombie_model = joblib.load(ZOMBIE_MODEL_PATH)
    zombie_scaler = joblib.load(ZOMBIE_SCALER_PATH)

    forecast_model = load_model(FORECAST_MODEL_PATH)
    forecast_scaler = joblib.load(FORECAST_SCALER_PATH)

    print("✅ All production models loaded successfully")
    return zombie_model, zombie_scaler, forecast_model, forecast_scaler


# ==========================================================
# 2. PREPROCESS LIVE DATA (MUST MATCH TRAINING)
# ==========================================================
def preprocess_live_data(file_path):

    df = pd.read_csv(file_path)

    # Datetime normalization
    date_cols = ['ChargePeriodStart','UsageDateTime','BillingPeriodStart']
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors='coerce')
            df['UsageDate'] = df[c].dt.date
            break

    # Clean numeric
    df['EffectiveCost'] = pd.to_numeric(df['EffectiveCost'], errors='coerce').fillna(0)
    df['ConsumedQuantity'] = pd.to_numeric(df['ConsumedQuantity'], errors='coerce').fillna(0)

    # Only positive spend
    df = df[df['EffectiveCost'] > 0]

    # Log transform (MUST match training)
    df['LogCost'] = np.log1p(df['EffectiveCost'])
    df['LogUsage'] = np.log1p(df['ConsumedQuantity'])

    return df


# ==========================================================
# 3. LIVE ZOMBIE DETECTION
# ==========================================================
def run_live_zombie_detection(df, model, scaler):

    features = df[['LogUsage','LogCost']]
    scaled = scaler.transform(features)

    preds = model.predict(scaled)
    df['is_anomaly'] = preds

    zombies = df[df['is_anomaly'] == -1]

    print(f"🧟 LIVE Zombies detected: {len(zombies)}")
    print(f"💰 LIVE potential waste: ${zombies['EffectiveCost'].sum():,.2f}")

    return zombies


# ==========================================================
# 4. LIVE SPEND FORECASTING
# ==========================================================
def run_live_forecast(df, model, scaler, days=7):

    daily = (
        df.groupby('UsageDate')['EffectiveCost']
        .sum()
        .sort_index()
    )

    data = daily.values.reshape(-1,1)

    # Normalize using TRAINED scaler
    scaled = scaler.transform(data)

    lookback = 7
    seq = scaled[-lookback:].reshape(1,lookback,1)

    preds = []

    for _ in range(days):
        p = model.predict(seq, verbose=0)[0][0]
        preds.append(p)
        seq = np.append(seq[:,1:,:], [[[p]]], axis=1)

    forecast = scaler.inverse_transform(np.array(preds).reshape(-1,1)).flatten()
    forecast = np.clip(forecast,0,None)

    print(f"📈 LIVE 7-day forecast: ${forecast.sum():,.2f}")

    return forecast


# ==========================================================
# MAIN – RUN ON YOUR UPLOADED FILE
# ==========================================================
if __name__ == "__main__":

    LIVE_FILE = "D:\Code\FOCUS-Sample-Data\FOCUS-1.0\\focus_data_table.csv.gz"   # <-- your uploaded file

    print("\n" + "="*60)
    print("🚀 AUTONOMOUS FINOPS – LIVE PREDICTION")
    print("="*60)

    # Load models
    zombie_model, zombie_scaler, forecast_model, forecast_scaler = load_models()

    # Load live data
    live_df = preprocess_live_data(LIVE_FILE)

    # Zombie Detection
    zombies = run_live_zombie_detection(
        live_df,
        zombie_model,
        zombie_scaler
    )

    # Forecasting
    forecast = run_live_forecast(
        live_df,
        forecast_model,
        forecast_scaler
    )

    print("\n" + "="*60)
    print("🎯 LIVE INFERENCE COMPLETE")
    print("="*60)
