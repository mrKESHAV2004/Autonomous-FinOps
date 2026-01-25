import os

import io

import base64

import numpy as np

import pandas as pd

import joblib

import matplotlib

matplotlib.use('Agg') # Fix for Flask/Matplotlib thread safety

import matplotlib.pyplot as plt

import tensorflow as tf

from flask import Flask, render_template, request, redirect, url_for, flash

from sklearn.ensemble import IsolationForest

from sklearn.preprocessing import StandardScaler

from tensorflow.keras.models import Sequential, load_model

from tensorflow.keras.layers import LSTM, Dense, Dropout

from tensorflow.keras.optimizers import Adam



app = Flask(__name__)

app.secret_key = 'super_secret_finops_key'



# Configuration

UPLOAD_FOLDER = 'uploads'

ARTIFACT_DIR = 'finops_artifacts'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

os.makedirs(ARTIFACT_DIR, exist_ok=True)



# --- HELPER FUNCTIONS ---



def load_and_prep_data(filepath):

    """Ingests and standardizes the uploaded CSV."""

    df = pd.read_csv(filepath)

    

    # Normalize dates

    date_cols = ['ChargePeriodStart', 'UsageDateTime', 'BillingPeriodStart', 'UsageDate']

    date_col_found = None

    for col in date_cols:

        if col in df.columns:

            df[col] = pd.to_datetime(df[col], errors='coerce')

            date_col_found = col

            break

            

    if date_col_found:

        df['UsageDate'] = df[date_col_found].dt.date

    else:

        # Create synthetic dates if missing

        base_date = pd.to_datetime('2024-01-01')

        df['UsageDate'] = [base_date.date() + pd.Timedelta(days=i % 30) for i in range(len(df))]



    # Numeric conversion

    df['EffectiveCost'] = pd.to_numeric(df['EffectiveCost'], errors='coerce').fillna(0)

    df['ConsumedQuantity'] = pd.to_numeric(df['ConsumedQuantity'], errors='coerce').fillna(0)

    

    # Filter positive costs only

    df = df[df['EffectiveCost'] > 0].copy()

    

    # Log transforms for ML

    df['LogCost'] = np.log1p(df['EffectiveCost'])

    df['LogUsage'] = np.log1p(df['ConsumedQuantity'])

    

    return df



def detect_zombies(df):

    """Trains Isolation Forest and identifies anomalies."""

    features = df[['LogUsage', 'LogCost']]

    scaler = StandardScaler()

    X_scaled = scaler.fit_transform(features)

    

    # Train Model (Retraining on upload to ensure fit)

    iso_forest = IsolationForest(contamination=0.05, random_state=42, n_jobs=-1)

    df['is_anomaly'] = iso_forest.fit_predict(X_scaled)

    

    zombies = df[df['is_anomaly'] == -1].copy()

    

    return df, zombies, iso_forest, scaler



def train_and_forecast(df, forecast_days=7):

    """Trains LSTM on daily spend and forecasts future."""

    daily_costs = df.groupby('UsageDate')['EffectiveCost'].sum().sort_index()

    

    # Data Prep

    data = daily_costs.values.reshape(-1, 1)

    scaler = StandardScaler()

    scaled_data = scaler.fit_transform(data)

    

    lookback = 7

    if len(daily_costs) < (lookback + 2):

        return None, 0, [], None # Not enough data

        

    X, y = [], []

    for i in range(len(scaled_data) - lookback):

        X.append(scaled_data[i:i+lookback])

        y.append(scaled_data[i+lookback])

    X, y = np.array(X), np.array(y)

    

    # LSTM Model

    model = Sequential([

        LSTM(50, activation='relu', return_sequences=True, input_shape=(lookback, 1)),

        LSTM(50, activation='relu'),

        Dense(1)

    ])

    model.compile(optimizer='adam', loss='mse')

    model.fit(X, y, epochs=30, batch_size=8, verbose=0)

    

    # Forecast

    curr_seq = scaled_data[-lookback:].reshape(1, lookback, 1)

    preds_scaled = []

    

    for _ in range(forecast_days):

        pred = model.predict(curr_seq, verbose=0)

        preds_scaled.append(pred[0,0])

        # Update sequence with new prediction

        curr_seq = np.append(curr_seq[:, 1:, :], pred.reshape(1, 1, 1), axis=1)

        

    forecast = scaler.inverse_transform(np.array(preds_scaled).reshape(-1, 1)).flatten()

    

    # --- IMPROVEMENT: Calculate Optimized Forecast ---

    # We assume if we fix the zombies, that daily waste is removed from the forecast

    return daily_costs, forecast, model, scaler



def generate_plot(daily_costs, forecast, zombie_savings):

    """Generates the 'Bend the Curve' graph."""

    plt.figure(figsize=(10, 6))

    

    # Historical Data

    dates = daily_costs.index.astype(str)

    plt.plot(dates, daily_costs.values, label='Historical Spend', color='gray', linewidth=2)

    

    # Future Dates

    last_date = pd.to_datetime(daily_costs.index[-1])

    future_dates = [(last_date + pd.Timedelta(days=i+1)).strftime('%Y-%m-%d') for i in range(len(forecast))]

    

    # 1. BAU Forecast (Business As Usual)

    plt.plot(future_dates, forecast, label='BAU Forecast (Risk)', color='red', linestyle='--', marker='o')

    

    # 2. Optimized Forecast (The Improvement)

    # We subtract the average daily zombie waste from the forecast

    daily_waste = zombie_savings / len(daily_costs)

    optimized_forecast = np.maximum(forecast - daily_waste, 0)

    

    plt.plot(future_dates, optimized_forecast, label='Optimized Forecast (w/ FinOps)', color='green', linestyle='-', marker='x', linewidth=2)

    

    plt.title('Cloud Spend Projection: BAU vs. Optimized')

    plt.xlabel('Date')

    plt.ylabel('Cost ($)')

    plt.xticks(rotation=45)

    plt.legend()

    plt.grid(True, alpha=0.3)

    plt.tight_layout()

    

    # Save to base64

    img = io.BytesIO()

    plt.savefig(img, format='png')

    img.seek(0)

    plot_url = base64.b64encode(img.getvalue()).decode()

    plt.close()

    return plot_url



# --- ROUTES ---



@app.route('/', methods=['GET', 'POST'])

def index():

    if request.method == 'POST':

        if 'file' not in request.files:

            flash('No file part')

            return redirect(request.url)

        file = request.files['file']

        if file.filename == '':

            flash('No selected file')

            return redirect(request.url)

        

        if file:

            filepath = os.path.join(UPLOAD_FOLDER, file.filename)

            file.save(filepath)

            

            # Process Data

            try:

                df = load_and_prep_data(filepath)

                

                # 1. Detect Zombies

                df, zombies, z_model, z_scaler = detect_zombies(df)

                total_waste = zombies['EffectiveCost'].sum()

                zombie_count = len(zombies)

                

                # 2. Forecast

                daily_costs, forecast, f_model, f_scaler = train_and_forecast(df)

                

                # 3. Generate Graph

                chart_data = generate_plot(daily_costs, forecast, total_waste)

                

                # Prepare data for dashboard

                total_spend = df['EffectiveCost'].sum()

                forecast_sum_bau = forecast.sum()

                period_days = len(daily_costs)

                

                # Optimization logic

                daily_waste = total_waste / period_days if period_days > 0 else 0

                forecast_sum_opt = np.maximum(forecast - daily_waste, 0).sum()

                potential_savings = forecast_sum_bau - forecast_sum_opt

                

                zombie_share = (total_waste / total_spend * 100) if total_spend > 0 else 0

                savings_share = (potential_savings / forecast_sum_bau * 100) if forecast_sum_bau > 0 else 0

                avg_daily_cost = daily_costs.mean() if period_days > 0 else 0

                avg_daily_zombie = daily_waste

                

                if total_spend > 0:

                    insight_headline = f"Zombie waste accounts for {zombie_share:.1f}% of your historical effective spend."

                else:

                    insight_headline = "Zombie waste detected in your environment."

                

                if forecast_sum_bau > 0:

                    insight_detail = (

                        f"By removing these zombies, you could avoid about ${potential_savings:,.2f} in the next 7 days, "

                        f"reducing projected spend by approximately {savings_share:.1f}%."

                    )

                else:

                    insight_detail = "We could not compute a reliable 7-day forecast from the current data."

                

                results = {

                    'total_spend': f"${total_spend:,.2f}",

                    'zombie_waste': f"${total_waste:,.2f}",

                    'zombie_count': zombie_count,

                    'forecast_bau': f"${forecast_sum_bau:,.2f}",

                    'forecast_opt': f"${forecast_sum_opt:,.2f}",

                    'savings': f"${potential_savings:,.2f}",

                    'zombie_pct_of_total': f"{zombie_share:.1f}%",

                    'savings_pct_vs_bau': f"{savings_share:.1f}%",

                    'avg_daily_cost': f"${avg_daily_cost:,.2f}",

                    'avg_daily_zombie': f"${avg_daily_zombie:,.2f}",

                    'period_days': period_days,

                    'insight_headline': insight_headline,

                    'insight_detail': insight_detail,

                    'chart': chart_data,

                    'zombies_preview': zombies[['UsageDate', 'ServiceCategory', 'EffectiveCost']].head(5).to_html(classes='table table-striped', index=False)

                }

                return render_template('dashboard.html', results=results)
            except Exception as e:
                flash(f"Error processing file: {str(e)}")
                return redirect(request.url)

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)