import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import joblib  # For saving Scikit-Learn models and Scalers
import warnings
import os

# Machine Learning Libraries
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# Deep Learning for Time Series Forecasting
try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.optimizers import Adam
except ImportError:
    print("Installing TensorFlow...")
    os.system('pip install -q tensorflow')
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.optimizers import Adam

# ============================================================================
# 0. HARDWARE ACCELERATION CHECK
# ============================================================================
def check_gpu_status():
    print("\n" + "=" * 70)
    print("🚀 HARDWARE ACCELERATION CHECK")
    print("=" * 70)
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        print(f"✅ GPU Detected: {len(gpus)} device(s) available.")
        for gpu in gpus:
            print(f"   - {gpu.name} (Type: {gpu.device_type})")
        print("   LSTM training will be accelerated.")
    else:
        print("⚠️  No GPU Detected. Running on CPU.")
        print("   Training may be slower. Enable GPU in Colab: Runtime > Change runtime type > T4 GPU")

# ============================================================================
# 1. DATA INGESTION - THE SILVER LAYER
# ============================================================================
def load_and_prep_data(file_path):
    """
    Silver Layer: Loads and prepares FOCUS-compliant cloud billing data.
    """
    print("\n" + "=" * 70)
    print("🔵 SILVER LAYER: Data Ingestion & Validation")
    print("=" * 70)

    compression = 'gzip' if file_path.endswith('.gz') else None

    try:
        # Load the dataset
        df = pd.read_csv(file_path, compression=compression, low_memory=False)
        print(f"✓ Loaded {len(df):,} records from {file_path}")

        # Validate FOCUS schema compliance
        required_columns = ['ChargeCategory', 'ServiceCategory', 'RegionId',
                          'EffectiveCost', 'ConsumedQuantity']
        missing_cols = [col for col in required_columns if col not in df.columns]

        if missing_cols:
            raise ValueError(f"Missing required FOCUS columns: {missing_cols}")

        # Prioritize ChargePeriodStart for daily granularity
        datetime_priority = ['ChargePeriodStart', 'UsageDateTime', 'BillingPeriodStart', 'UsageDate']
        date_col_found = None

        for col in datetime_priority:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                date_col_found = col
                print(f"✓ Using {col} for time-series (daily granularity)")
                break

        # Create unified UsageDate column at DAY level
        if date_col_found:
            df['UsageDate'] = df[date_col_found].dt.date
        else:
            print("⚠ No datetime column found. Creating synthetic dates...")
            base_date = datetime(2024, 1, 1)
            df['UsageDate'] = [base_date.date() + timedelta(days=i % 30)
                              for i in range(len(df))]

        # Handle missing values
        df['EffectiveCost'] = df['EffectiveCost'].fillna(0)
        df['ConsumedQuantity'] = df['ConsumedQuantity'].fillna(0)
        df['ChargeCategory'] = df['ChargeCategory'].fillna('Unknown')
        df['ServiceCategory'] = df['ServiceCategory'].fillna('Unknown')

        # Separate positive costs from credits
        df['IsCredit'] = df['EffectiveCost'] < 0
        positive_costs = df[df['EffectiveCost'] >= 0]
        negative_costs = df[df['EffectiveCost'] < 0]

        total_spend = positive_costs['EffectiveCost'].sum()
        total_credits = abs(negative_costs['EffectiveCost'].sum())

        print(f"✓ Handled missing values")
        print(f"✓ Total spend (positive): ${total_spend:,.2f}")
        print(f"✓ Total credits (refunds): -${total_credits:,.2f}")

        return df

    except FileNotFoundError:
        print(f"❌ Error: File '{file_path}' not found")
        raise
    except Exception as e:
        print(f"❌ Error during data ingestion: {str(e)}")
        raise


# ============================================================================
# 2. ZOMBIE HUNTER AGENT - ANOMALY DETECTION
# ============================================================================
def zombie_hunter_agent(df):
    """
    Zombie Hunter: ML-powered anomaly detection using Isolation Forest.
    Returns: Dict containing results AND the trained model/scaler for persistence.
    """
    print("\n" + "=" * 70)
    print("🧟 ZOMBIE HUNTER AGENT: Anomaly Detection")
    print("=" * 70)

    # Only analyze positive costs
    df_positive = df[df['EffectiveCost'] > 0].copy()

    if len(df_positive) == 0:
        return {'anomaly_count': 0, 'anomalies_df': pd.DataFrame(), 'total_waste': 0, 'percentage': 0, 'model': None, 'scaler': None}

    # Log-transform costs to handle skewness
    df_positive['LogCost'] = np.log1p(df_positive['EffectiveCost'])
    df_positive['LogUsage'] = np.log1p(df_positive['ConsumedQuantity'])

    features = df_positive[['LogUsage', 'LogCost']].copy()

    # Standardize features
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)

    # Initialize Isolation Forest
    iso_forest = IsolationForest(
        contamination=0.05,
        random_state=42,
        n_estimators=100,
        n_jobs=-1 # Uses all CPU cores
    )

    print("🔍 Training Isolation Forest...")
    predictions = iso_forest.fit_predict(features_scaled)

    df_positive['is_anomaly'] = predictions
    anomalies = df_positive[df_positive['is_anomaly'] == -1].copy()

    total_anomaly_cost = anomalies['EffectiveCost'].sum()
    total_positive_cost = df_positive['EffectiveCost'].sum()
    anomaly_count = len(anomalies)

    print(f"📊 Found {anomaly_count:,} anomalies")
    print(f"💰 Potential waste: ${total_anomaly_cost:,.2f}")

    return {
        'anomaly_count': anomaly_count,
        'anomalies_df': anomalies,
        'total_waste': total_anomaly_cost,
        'percentage': anomaly_count / len(df_positive) * 100 if len(df_positive) > 0 else 0,
        # Artifacts for persistence
        'model': iso_forest,
        'scaler': scaler
    }


# ============================================================================
# 3. SPOTHEDGE AGENT - COST FORECASTING (GPU ACCELERATED)
# ============================================================================
def forecast_spend(df, forecast_days=7):
    """
    SpotHedge: LSTM-based forecasting.
    Returns: Dict containing results AND the trained model/scaler for persistence.
    """
    print("\n" + "=" * 70)
    print("📈 SPOTHEDGE AGENT: Cost Forecasting with LSTM")
    print("=" * 70)

    df_positive = df[df['EffectiveCost'] > 0].copy()
    daily_costs = df_positive.groupby('UsageDate')['EffectiveCost'].sum().sort_index()

    num_days = len(daily_costs)
    min_required_days = 14

    # Fallback if insufficient data
    if num_days < min_required_days:
        print(f"📊 Using Moving Average (Insufficient data for LSTM: {num_days} days)")
        avg_cost = daily_costs.tail(7).mean() if len(daily_costs) >= 7 else daily_costs.mean()
        forecast = [avg_cost] * forecast_days
        return {
            'forecast': forecast,
            'method': 'moving_average',
            'total_forecast': sum(forecast),
            'daily_average': avg_cost,
            'model': None,
            'scaler': None
        }

    # Prepare time series data
    costs_array = daily_costs.values.reshape(-1, 1)

    # Normalize the data
    scaler = StandardScaler()
    costs_scaled = scaler.fit_transform(costs_array)

    lookback = 7

    def create_sequences(data, lookback):
        X, y = [], []
        for i in range(len(data) - lookback):
            X.append(data[i:i+lookback])
            y.append(data[i+lookback])
        return np.array(X), np.array(y)

    X, y = create_sequences(costs_scaled, lookback)

    # Build LSTM model
    model = Sequential([
        LSTM(50, activation='relu', return_sequences=True, input_shape=(lookback, 1)),
        Dropout(0.2),
        LSTM(50, activation='relu'),
        Dropout(0.2),
        Dense(1)
    ])

    model.compile(optimizer=Adam(learning_rate=0.001), loss='mse')

    print("🔄 Training LSTM model (GPU accelerated if available)...")
    with tf.device('/GPU:0' if tf.config.list_physical_devices('GPU') else '/CPU:0'):
        model.fit(X, y, epochs=50, batch_size=16, verbose=0, validation_split=0.2)

    print("✓ Model training complete")

    # Generate forecast
    last_sequence = costs_scaled[-lookback:].reshape(1, lookback, 1)
    forecasted_scaled = []
    current_sequence = last_sequence.copy()

    for _ in range(forecast_days):
        next_pred = model.predict(current_sequence, verbose=0)
        forecasted_scaled.append(next_pred[0, 0])
        current_sequence = np.append(current_sequence[:, 1:, :], next_pred.reshape(1, 1, 1), axis=1)

    forecast = scaler.inverse_transform(np.array(forecasted_scaled).reshape(-1, 1)).flatten()

    # Safety clip
    historical_avg = daily_costs.mean()
    if forecast.mean() > historical_avg * 3:
        forecast = np.clip(forecast, 0, historical_avg * 2)

    return {
        'forecast': forecast.tolist(),
        'method': 'LSTM',
        'total_forecast': forecast.sum(),
        'daily_average': forecast.mean(),
        # Artifacts for persistence
        'model': model,
        'scaler': scaler
    }


# ============================================================================
# 4. CIRCUIT BREAKER - GOVERNANCE LAYER
# ============================================================================
class CircuitBreaker:
    def __init__(self, max_deletions=5, max_percentage=10.0):
        self.max_deletions = max_deletions
        self.max_percentage = max_percentage
        print("\n" + "=" * 70)
        print("🛡️  CIRCUIT BREAKER: Governance Layer Initialized")
        print("=" * 70)

    def evaluate(self, zombie_results):
        anomaly_count = zombie_results['anomaly_count']
        percentage = zombie_results['percentage']

        if anomaly_count > self.max_deletions:
            return {'approved': False, 'state': 'OPEN', 'reason': f"Count ({anomaly_count}) > Limit ({self.max_deletions})"}
        elif percentage > self.max_percentage:
            return {'approved': False, 'state': 'OPEN', 'reason': f"Percent ({percentage:.2f}%) > Limit ({self.max_percentage}%)"}
        else:
            return {'approved': True, 'state': 'CLOSED', 'reason': 'Within safety thresholds', 'action': 'APPROVED'}

# ============================================================================
# 5. ARTIFACT MANAGER (MODEL SAVING)
# ============================================================================
def save_artifacts(zombie_res, forecast_res, output_dir='./finops_artifacts'):
    """
    Saves trained models and scalers to disk for Live Data usage.
    """
    print("\n" + "=" * 70)
    print("💾 PERSISTING MODELS FOR LIVE DATA")
    print("=" * 70)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 1. Save Zombie Hunter (Anomaly Detection)
    if zombie_res['model'] is not None:
        joblib.dump(zombie_res['model'], f'{output_dir}/zombie_model.pkl')
        joblib.dump(zombie_res['scaler'], f'{output_dir}/zombie_scaler.pkl')
        print(f"✓ Saved Anomaly Model & Scaler to {output_dir}/zombie_*.pkl")

    # 2. Save SpotHedge (Forecasting)
    if forecast_res['model'] is not None and forecast_res['method'] == 'LSTM':
        # Save Keras Model
        forecast_res['model'].save(f'{output_dir}/forecast_lstm.keras')
        # CRITICAL: Save the scaler used for the Time Series
        joblib.dump(forecast_res['scaler'], f'{output_dir}/forecast_scaler.pkl')
        print(f"✓ Saved LSTM Model to {output_dir}/forecast_lstm.keras")
        print(f"✓ Saved Forecasting Scaler to {output_dir}/forecast_scaler.pkl")
    else:
        print("⚠ Forecasting model was moving average; nothing to save.")

    print(f"ℹ️  To use on Live Data: Load these .pkl/.keras files and apply to new inputs.")

# ============================================================================
# MAIN EXECUTION
# ============================================================================
if __name__ == "__main__":
    check_gpu_status()

    # Point this to your uploaded file
    DATA_FILE = "../FOCUS-Sample-Data/FOCUS-1.0/focus_data_table.csv.gz"

    # Generate dummy file if not exists for demo purposes
    if not os.path.exists(DATA_FILE):
        print("\n⚠ Demo Data not found. Creating dummy FOCUS data...")
        dates = pd.date_range(start='2024-01-01', periods=100)
        data = {
            'ChargePeriodStart': np.random.choice(dates, 1000),
            'RegionId': np.random.choice(['us-east-1', 'eu-west-1'], 1000),
            'ServiceCategory': np.random.choice(['Compute', 'Database', 'Storage'], 1000),
            'ChargeCategory': 'Usage',
            'ConsumedQuantity': np.random.uniform(1, 100, 1000),
            'EffectiveCost': np.random.uniform(0.1, 50, 1000)
        }
        pd.DataFrame(data).to_csv(DATA_FILE, index=False)
        print("✓ Dummy data created.")

    try:
        # 1. Ingest
        df = load_and_prep_data(DATA_FILE)

        # 2. Detect
        zombie_results = zombie_hunter_agent(df)

        # 3. Govern
        circuit_breaker = CircuitBreaker()
        governance_decision = circuit_breaker.evaluate(zombie_results)

        # 4. Forecast
        forecast_results = forecast_spend(df)

        # 5. Persist (Save to "DLL"/Files)
        save_artifacts(zombie_results, forecast_results)

        print("\n✨ Autonomous Cycle Complete.")

    except Exception as e:
        print(f"\n❌ Execution Failed: {str(e)}")
        import traceback
        traceback.print_exc()