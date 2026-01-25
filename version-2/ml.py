# ==========================================================
# AUTONOMOUS FINOPS - ADVANCED MODEL TRAINING & OPTIMIZATION
# ==========================================================

import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import warnings
import os
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import silhouette_score
import optuna

# TensorFlow for LSTM
import tensorflow as tf
from tensorflow.keras.models import Sequential, save_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.regularizers import l1_l2

warnings.filterwarnings('ignore')

# Set random seeds for reproducibility
np.random.seed(42)
tf.random.set_seed(42)

# ==========================================================
# 1. ENHANCED DATA PREPROCESSING
# ==========================================================

class DataPreprocessor:
    """Advanced data preprocessing with feature engineering"""
    
    def load_and_preprocess(self, file_path, sample_size=None):
        """Load and preprocess data with advanced features"""
        print("\n" + "="*70)
        print("📊 ENHANCED DATA PREPROCESSING")
        print("="*70)
        
        # Load data
        compression = 'gzip' if file_path.endswith('.gz') else None
        df = pd.read_csv(file_path, compression=compression, low_memory=False)
        
        if sample_size and sample_size < len(df):
            df = df.sample(sample_size, random_state=42)
            print(f"✓ Sampled {sample_size:,} records for faster processing")
        
        print(f"✓ Loaded {len(df):,} total records")
        
        # Handle dates
        df = self._process_dates(df)
        
        # Clean and standardize numeric columns
        df = self._clean_numeric_columns(df)
        
        # Feature engineering
        df = self._engineer_features(df)
        
        # Filter for analysis
        df_analysis = df[df['EffectiveCost'] > 0].copy()
        print(f"✓ {len(df_analysis):,} records with positive costs for analysis")
        
        return df, df_analysis
    
    def _process_dates(self, df):
        """Process date columns"""
        date_columns = ['ChargePeriodStart', 'UsageDateTime', 'BillingPeriodStart', 'UsageDate']
        
        for date_col in date_columns:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df['UsageDate'] = df[date_col].dt.date
                print(f"✓ Using {date_col} for temporal analysis")
                break
        
        if 'UsageDate' not in df.columns:
            print("⚠ No date column found. Creating synthetic dates...")
            base_date = datetime.now().date() - timedelta(days=len(df))
            df['UsageDate'] = [base_date + timedelta(days=i) for i in range(len(df))]
        
        return df
    
    def _clean_numeric_columns(self, df):
        """Clean and standardize numeric columns"""
        # Convert to numeric
        df['EffectiveCost'] = pd.to_numeric(df['EffectiveCost'], errors='coerce')
        df['ConsumedQuantity'] = pd.to_numeric(df['ConsumedQuantity'], errors='coerce')
        
        # Fill missing values
        df['EffectiveCost'] = df['EffectiveCost'].fillna(0)
        median_usage = df['ConsumedQuantity'].median() if df['ConsumedQuantity'].notna().any() else 1
        df['ConsumedQuantity'] = df['ConsumedQuantity'].fillna(median_usage)
        
        return df
    
    def _engineer_features(self, df):
        """Create advanced features for better anomaly detection"""
        # Basic log transforms
        df['LogCost'] = np.log1p(df['EffectiveCost'])
        df['LogUsage'] = np.log1p(df['ConsumedQuantity'])
        
        # Cost efficiency metrics
        df['CostPerUnit'] = df['EffectiveCost'] / (df['ConsumedQuantity'] + 1e-6)
        df['LogCostPerUnit'] = np.log1p(df['CostPerUnit'])
        
        # Statistical features
        df['CostZScore'] = (df['EffectiveCost'] - df['EffectiveCost'].mean()) / (df['EffectiveCost'].std() + 1e-6)
        df['UsageZScore'] = (df['ConsumedQuantity'] - df['ConsumedQuantity'].mean()) / (df['ConsumedQuantity'].std() + 1e-6)
        df['CostUsageInteraction'] = df['LogCost'] * df['LogUsage']
        
        print("✓ Engineered 7 features for improved detection")
        return df

# ==========================================================
# 2. OPTIMIZED ZOMBIE DETECTION
# ==========================================================

class OptimizedZombieDetector:
    """Advanced anomaly detection with optimized parameters"""
    
    def __init__(self):
        self.model = None
        self.scaler = None
        
    def detect_anomalies(self, df):
        """Detect anomalies with optimized parameters"""
        print("\n" + "="*70)
        print("🧟 OPTIMIZED ZOMBIE DETECTION")
        print("="*70)
        
        # Select features for anomaly detection
        feature_candidates = ['LogCost', 'LogUsage', 'CostPerUnit', 'LogCostPerUnit', 
                            'CostZScore', 'UsageZScore', 'CostUsageInteraction']
        available_features = [f for f in feature_candidates if f in df.columns]
        
        if len(available_features) < 2:
            available_features = ['LogCost', 'LogUsage']
        
        print(f"✓ Using features: {available_features}")
        X = df[available_features].fillna(0).values
        
        # Scale features using RobustScaler
        self.scaler = RobustScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Adaptive contamination
        contamination = min(0.1, max(0.01, 50/len(df)))
        
        # Train Isolation Forest
        self.model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            max_features=1.0,
            random_state=42,
            n_jobs=-1,
            bootstrap=False,
            verbose=0
        )
        
        print("🔄 Training optimized Isolation Forest...")
        df['anomaly_score'] = self.model.fit_predict(X_scaled)
        df['decision_function'] = self.model.decision_function(X_scaled)
        
        # Calculate anomaly probabilities
        df['anomaly_probability'] = 1 / (1 + np.exp(-df['decision_function']))
        
        # Identify zombies (anomalies)
        zombies = df[df['anomaly_score'] == -1].copy()
        
        # Categorize by confidence
        if len(zombies) > 0:
            conditions = [
                zombies['anomaly_probability'] > 0.7,
                zombies['anomaly_probability'] > 0.4,
                zombies['anomaly_probability'] <= 0.4
            ]
            choices = ['High', 'Medium', 'Low']
            zombies['confidence'] = np.select(conditions, choices, default='Medium')
        
        # Calculate statistics
        total_waste = zombies['EffectiveCost'].sum()
        total_spend = df['EffectiveCost'].sum()
        waste_percentage = (total_waste / total_spend * 100) if total_spend > 0 else 0
        
        print(f"📊 Results:")
        print(f"   - Zombies detected: {len(zombies):,}")
        print(f"   - Potential waste: ${total_waste:,.2f}")
        print(f"   - Waste percentage: {waste_percentage:.2f}%")
        
        if 'confidence' in zombies.columns:
            print(f"   - High confidence: {(zombies['confidence'] == 'High').sum():,}")
        
        return {
            'zombies': zombies,
            'df_with_scores': df,
            'total_waste': total_waste,
            'waste_percentage': waste_percentage,
            'zombie_count': len(zombies)
        }

# ==========================================================
# 3. ADVANCED LSTM FORECASTING
# ==========================================================

class AdvancedForecaster:
    """Advanced time series forecasting with optimized LSTM"""
    
    def __init__(self, lookback_window=14, forecast_days=7):
        self.lookback = lookback_window
        self.forecast_days = forecast_days
        self.model = None
        self.scaler = None
        
    def prepare_sequences(self, daily_costs):
        """Prepare sequences for LSTM"""
        data = daily_costs.values.reshape(-1, 1)
        
        # Create features
        df_features = pd.DataFrame({
            'cost': data.flatten(),
            'rolling_mean_7': pd.Series(data.flatten()).rolling(7, min_periods=1).mean(),
            'rolling_std_7': pd.Series(data.flatten()).rolling(7, min_periods=1).std(),
            'day_of_week': pd.Series(range(len(data))) % 7
        }).fillna(method='bfill').fillna(method='ffill')
        
        # Scale features
        self.scaler = {}
        scaled_features = []
        
        for col in df_features.columns:
            scaler = StandardScaler()
            scaled_col = scaler.fit_transform(df_features[[col]].values)
            scaled_features.append(scaled_col)
            self.scaler[col] = scaler
        
        # Combine scaled features
        X_scaled = np.concatenate(scaled_features, axis=1)
        
        # Create sequences
        X, y = [], []
        for i in range(len(X_scaled) - self.lookback - self.forecast_days + 1):
            X.append(X_scaled[i:i + self.lookback])
            y.append(X_scaled[i + self.lookback:i + self.lookback + self.forecast_days, 0])
        
        return np.array(X), np.array(y), df_features.columns.tolist()
    
    def build_optimized_lstm(self, input_shape):
        """Build optimized LSTM model"""
        model = Sequential([
            LSTM(64, return_sequences=True, input_shape=input_shape,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.3),
            LSTM(32, return_sequences=False,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.2),
            Dense(32, activation='relu'),
            Dense(self.forecast_days)
        ])
        
        optimizer = Adam(learning_rate=0.001)
        model.compile(optimizer=optimizer, loss='huber', metrics=['mae', 'mse'])
        
        return model
    
    def forecast(self, df):
        """Generate optimized forecasts"""
        print("\n" + "="*70)
        print("📈 ADVANCED TIME SERIES FORECASTING")
        print("="*70)
        
        # Aggregate daily costs
        daily_costs = df.groupby('UsageDate')['EffectiveCost'].sum().sort_index()
        
        if len(daily_costs) < self.lookback + self.forecast_days:
            print(f"⚠ Insufficient data: {len(daily_costs)} days.")
            avg_cost = daily_costs.mean() if len(daily_costs) > 0 else 0
            forecast = np.ones(self.forecast_days) * avg_cost
            return {
                'forecast': forecast.tolist(),
                'confidence_intervals': None,
                'method': 'average',
                'model': None
            }
        
        print(f"✓ Preparing {len(daily_costs)} days of historical data")
        
        # Prepare sequences
        X, y, feature_names = self.prepare_sequences(daily_costs)
        
        # Build model
        self.model = self.build_optimized_lstm((self.lookback, len(feature_names)))
        
        print("🔄 Training advanced LSTM model...")
        
        # Callbacks
        callbacks = [
            EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True),
            ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5, min_lr=1e-6)
        ]
        
        # Split data
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # Train
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=100,
            batch_size=32,
            callbacks=callbacks,
            verbose=0
        )
        
        print(f"✓ Model trained. Final loss: {history.history['val_loss'][-1]:.4f}")
        
        # Generate forecast
        last_sequence = X[-1:]
        forecast_scaled = self.model.predict(last_sequence, verbose=0)[0]
        
        # Inverse transform
        cost_scaler = self.scaler['cost']
        forecast = cost_scaler.inverse_transform(
            forecast_scaled.reshape(-1, 1)
        ).flatten()
        
        # Ensure non-negative forecasts
        forecast = np.maximum(forecast, 0)
        
        # Calculate confidence intervals
        val_predictions = self.model.predict(X_val, verbose=0)
        errors = y_val - val_predictions
        std_error = np.std(errors, axis=0) if len(errors) > 0 else np.std(forecast) * 0.1
        
        confidence_upper = forecast + 1.96 * std_error
        confidence_lower = np.maximum(forecast - 1.96 * std_error, 0)
        
        print(f"📊 Forecast Results:")
        print(f"   - 7-day forecast total: ${forecast.sum():,.2f}")
        print(f"   - Average daily forecast: ${forecast.mean():,.2f}")
        
        return {
            'forecast': forecast.tolist(),
            'confidence_intervals': {
                'upper': confidence_upper.tolist(),
                'lower': confidence_lower.tolist()
            },
            'method': 'advanced_lstm',
            'model': self.model,
            'scaler': self.scaler,
            'historical_data': daily_costs.tolist()
        }

# ==========================================================
# 4. MAIN TRAINING PIPELINE
# ==========================================================

def main_training_pipeline(data_path, output_dir='./finops_artifacts'):
    """Main pipeline for training optimized models"""
    
    print("\n" + "="*70)
    print("🚀 AUTONOMOUS FINOPS - ADVANCED MODEL TRAINING")
    print("="*70)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 1. Enhanced Data Preprocessing
        preprocessor = DataPreprocessor()
        df, df_analysis = preprocessor.load_and_preprocess(data_path, sample_size=50000)
        
        # 2. Optimized Zombie Detection
        detector = OptimizedZombieDetector()
        zombie_results = detector.detect_anomalies(df_analysis)
        
        # 3. Advanced Forecasting
        forecaster = AdvancedForecaster(lookback_window=14, forecast_days=7)
        forecast_results = forecaster.forecast(df_analysis)
        
        # 4. Save Models
        print("\n" + "="*70)
        print("💾 SAVING OPTIMIZED MODELS")
        print("="*70)
        
        # Save zombie detection model
        if detector.model:
            joblib.dump(detector.model, f'{output_dir}/zombie_model.pkl')
            joblib.dump(detector.scaler, f'{output_dir}/zombie_scaler.pkl')
            print("✓ Saved zombie detection model")
        
        # Save forecasting model
        if forecast_results['model']:
            forecast_results['model'].save(f'{output_dir}/forecast_lstm.keras')
            
            # Save scalers
            scaler_data = {
                'feature_scalers': forecast_results['scaler'],
                'feature_names': list(forecast_results['scaler'].keys())
            }
            joblib.dump(scaler_data, f'{output_dir}/forecast_scalers.pkl')
            print("✓ Saved forecasting model")
        
        # Save metadata
        import json
        metadata = {
            'training_date': datetime.now().isoformat(),
            'data_source': data_path,
            'records_analyzed': len(df_analysis),
            'zombie_count': zombie_results['zombie_count'],
            'total_waste': zombie_results['total_waste'],
            'forecast_total': sum(forecast_results['forecast'])
        }
        
        with open(f'{output_dir}/training_metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print("\n" + "="*70)
        print("✨ TRAINING COMPLETE")
        print("="*70)
        print(f"✓ Models saved to: {output_dir}/")
        print(f"✓ Ready for production inference")
        
        return {
            'success': True,
            'zombie_count': zombie_results['zombie_count'],
            'total_waste': zombie_results['total_waste'],
            'forecast_total': sum(forecast_results['forecast']),
            'output_dir': output_dir
        }
        
    except Exception as e:
        print(f"\n❌ Training failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

# ==========================================================
# EXECUTION
# ==========================================================

if __name__ == "__main__":
    # Set your data path here
    DATA_PATH = "../focus_data_table.csv.gz"
    
    # Check if file exists
    if not os.path.exists(DATA_PATH):
        print(f"❌ Data file not found: {DATA_PATH}")
        print("\nCreating sample data for demonstration...")
        
        # Create sample data
        np.random.seed(42)
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
        sample_data = []
        
        for date in dates:
            for _ in range(100):  # 100 records per day
                service = np.random.choice(['Compute', 'Database', 'Storage', 'Network'])
                cost = np.random.exponential(50)
                usage = np.random.uniform(1, 100)
                
                # Create some anomalies (5%)
                if np.random.random() < 0.05:
                    cost = cost * 5  # Expensive but low usage
                    usage = usage * 0.2
                
                sample_data.append({
                    'UsageDate': date.date(),
                    'ServiceCategory': service,
                    'EffectiveCost': cost,
                    'ConsumedQuantity': usage
                })
        
        df_sample = pd.DataFrame(sample_data)
        DATA_PATH = './sample_cloud_data.csv'
        df_sample.to_csv(DATA_PATH, index=False)
        print(f"✓ Created sample data at: {DATA_PATH}")
    
    # Run training
    results = main_training_pipeline(DATA_PATH)
    
    if results['success']:
        print(f"\n🎯 Training Summary:")
        print(f"   - Zombies detected: {results['zombie_count']:,}")
        print(f"   - Potential waste: ${results['total_waste']:,.2f}")
        print(f"   - 7-day forecast: ${results['forecast_total']:,.2f}")
    else:
        print(f"\n❌ Training failed: {results.get('error', 'Unknown error')}")