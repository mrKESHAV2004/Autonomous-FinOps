# ==========================================================
# AUTONOMOUS FINOPS - ADVANCED MODEL TRAINING & OPTIMIZATION
# OPTIMIZED VERSION - Enhanced Accuracy & Data Interpretation
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
from sklearn.preprocessing import StandardScaler, RobustScaler, LabelEncoder
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, mean_squared_error

# TensorFlow for LSTM
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint
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
        else:
            print("✓ Processing all available records (No sampling)")
        
        print(f"✓ Loaded {len(df):,} total records")
        
        # Handle dates
        df = self._process_dates(df)
        
        # Clean and standardize numeric columns
        df = self._clean_numeric_columns(df)
        
        # Feature engineering
        df = self._engineer_features(df)
        
        # Filter for analysis
        # MODIFIED: Reverted to positive costs only to avoid skewing anomaly detection with zero-cost items
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
        # Basic log transforms (handle zeros properly)
        df['LogCost'] = np.log1p(df['EffectiveCost'])
        df['LogUsage'] = np.log1p(df['ConsumedQuantity'])
        
        # Cost efficiency metrics
        df['CostPerUnit'] = df['EffectiveCost'] / (df['ConsumedQuantity'] + 1e-6)
        df['LogCostPerUnit'] = np.log1p(df['CostPerUnit'])
        
        # Advanced efficiency ratios
        df['CostUsageRatio'] = df['EffectiveCost'] / (df['ConsumedQuantity'] + 1e-6)
        df['UsageCostRatio'] = df['ConsumedQuantity'] / (df['EffectiveCost'] + 1e-6)
        
        # Statistical features with robust scaling
        cost_mean = df['EffectiveCost'].mean()
        cost_std = df['EffectiveCost'].std() + 1e-6
        usage_mean = df['ConsumedQuantity'].mean()
        usage_std = df['ConsumedQuantity'].std() + 1e-6
        
        df['CostZScore'] = (df['EffectiveCost'] - cost_mean) / cost_std
        df['UsageZScore'] = (df['ConsumedQuantity'] - usage_mean) / usage_std
        
        # Percentile-based features
        df['CostPercentile'] = df['EffectiveCost'].rank(pct=True)
        df['UsagePercentile'] = df['ConsumedQuantity'].rank(pct=True)
        
        # Interaction features
        df['CostUsageInteraction'] = df['LogCost'] * df['LogUsage']
        df['CostUsageDiff'] = df['LogCost'] - df['LogUsage']
        df['CostUsageSum'] = df['LogCost'] + df['LogUsage']
        
        # Temporal features if date available
        if 'UsageDate' in df.columns:
            df['UsageDate'] = pd.to_datetime(df['UsageDate'])
            df['DayOfWeek'] = df['UsageDate'].dt.dayofweek
            df['DayOfMonth'] = df['UsageDate'].dt.day
            df['Month'] = df['UsageDate'].dt.month
            df['Quarter'] = df['UsageDate'].dt.quarter
            df['IsWeekend'] = (df['DayOfWeek'] >= 5).astype(int)
            
            # Cyclical encoding for temporal features
            df['DayOfWeekSin'] = np.sin(2 * np.pi * df['DayOfWeek'] / 7)
            df['DayOfWeekCos'] = np.cos(2 * np.pi * df['DayOfWeek'] / 7)
            df['MonthSin'] = np.sin(2 * np.pi * df['Month'] / 12)
            df['MonthCos'] = np.cos(2 * np.pi * df['Month'] / 12)
        
        # Service category encoding if available
        if 'ServiceCategory' in df.columns:
            le = LabelEncoder()
            df['ServiceCategoryEncoded'] = le.fit_transform(df['ServiceCategory'].astype(str))
            # Service-specific statistics
            service_stats = df.groupby('ServiceCategory').agg({
                'EffectiveCost': ['mean', 'std'],
                'ConsumedQuantity': ['mean', 'std']
            }).reset_index()
            service_stats.columns = ['ServiceCategory', 'ServiceCostMean', 'ServiceCostStd', 
                                   'ServiceUsageMean', 'ServiceUsageStd']
            df = df.merge(service_stats, on='ServiceCategory', how='left')
            df['CostVsServiceMean'] = df['EffectiveCost'] / (df['ServiceCostMean'] + 1e-6)
            df['UsageVsServiceMean'] = df['ConsumedQuantity'] / (df['ServiceUsageMean'] + 1e-6)
        
        # Rolling statistics (if temporal data available)
        if 'UsageDate' in df.columns and len(df) > 7:
            df_sorted = df.sort_values('UsageDate')
            df_sorted['RollingCostMean7'] = df_sorted['EffectiveCost'].rolling(window=7, min_periods=1).mean()
            df_sorted['RollingCostStd7'] = df_sorted['EffectiveCost'].rolling(window=7, min_periods=1).std()
            df_sorted['RollingUsageMean7'] = df_sorted['ConsumedQuantity'].rolling(window=7, min_periods=1).mean()
            df_sorted['CostVsRollingMean'] = df_sorted['EffectiveCost'] / (df_sorted['RollingCostMean7'] + 1e-6)
            df = df_sorted.copy()
        
        # Outlier indicators using IQR method
        Q1_cost = df['EffectiveCost'].quantile(0.25)
        Q3_cost = df['EffectiveCost'].quantile(0.75)
        IQR_cost = Q3_cost - Q1_cost
        df['IsCostOutlier'] = ((df['EffectiveCost'] < (Q1_cost - 1.5 * IQR_cost)) | 
                              (df['EffectiveCost'] > (Q3_cost + 1.5 * IQR_cost))).astype(int)
        
        Q1_usage = df['ConsumedQuantity'].quantile(0.25)
        Q3_usage = df['ConsumedQuantity'].quantile(0.75)
        IQR_usage = Q3_usage - Q1_usage
        df['IsUsageOutlier'] = ((df['ConsumedQuantity'] < (Q1_usage - 1.5 * IQR_usage)) | 
                               (df['ConsumedQuantity'] > (Q3_usage + 1.5 * IQR_usage))).astype(int)
        
        # NEW: Advanced Feature Engineering for Higher Accuracy
        
        # 1. Frequency Encoding (Rareness of service)
        if 'ServiceCategory' in df.columns:
            service_freq = df['ServiceCategory'].value_counts(normalize=True)
            df['ServiceFrequency'] = df['ServiceCategory'].map(service_freq)
            
        # 2. Month Timing (Billing Spikes often happen at start/end)
        if 'DayOfMonth' in df.columns:
            df['IsStartOfMonth'] = (df['DayOfMonth'] <= 5).astype(int)
            df['IsEndOfMonth'] = (df['DayOfMonth'] >= 25).astype(int)
            
        # 3. Polynomial Features (Non-linear relationships)
        df['CostSquared'] = df['EffectiveCost'] ** 2
        df['UsageSquared'] = df['ConsumedQuantity'] ** 2
        
        # 4. Log-Log Ratios (Elasticity proxy)
        df['LogCostRatio'] = df['LogCost'] / (df['LogUsage'] + 1e-6)
        
        feature_count = len([col for col in df.columns if col not in ['UsageDate', 'ServiceCategory', 
                                                                      'EffectiveCost', 'ConsumedQuantity']])
        print(f"✓ Engineered {feature_count} features for improved detection")
        return df

# ==========================================================
# 2. OPTIMIZED ZOMBIE DETECTION
# ==========================================================

class OptimizedZombieDetector:
    """Advanced anomaly detection with ensemble methods and optimized parameters"""
    
    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_importance = None
        
    def _select_best_features(self, df, target_col='EffectiveCost'):
        """Select most informative features for anomaly detection"""
        feature_candidates = [
            'LogCost', 'LogUsage', 'CostPerUnit', 'LogCostPerUnit',
            'CostZScore', 'UsageZScore', 'CostUsageInteraction',
            'CostUsageRatio', 'UsageCostRatio', 'CostPercentile', 'UsagePercentile',
            'CostUsageDiff', 'CostUsageSum', 'IsCostOutlier', 'IsUsageOutlier',
            # New Features
            'ServiceFrequency', 'IsStartOfMonth', 'IsEndOfMonth', 
            'CostSquared', 'UsageSquared', 'LogCostRatio'
        ]
        
        # Add temporal features if available
        if 'DayOfWeekSin' in df.columns:
            feature_candidates.extend(['DayOfWeekSin', 'DayOfWeekCos', 'MonthSin', 'MonthCos'])
        
        # Add service-specific features if available
        if 'CostVsServiceMean' in df.columns:
            feature_candidates.extend(['CostVsServiceMean', 'UsageVsServiceMean'])
        
        # Add rolling features if available
        if 'CostVsRollingMean' in df.columns:
            feature_candidates.append('CostVsRollingMean')
        
        available_features = [f for f in feature_candidates if f in df.columns]
        
        # Feature selection using correlation and variance
        if len(available_features) > 5:
            # Remove low variance features
            variances = df[available_features].var()
            high_var_features = variances[variances > 1e-6].index.tolist()
            
            # Select features with good correlation to cost
            if target_col in df.columns:
                correlations = df[high_var_features].corrwith(df[target_col]).abs()
                top_features = correlations.nlargest(min(15, len(high_var_features))).index.tolist()
                available_features = top_features
        
        if len(available_features) < 2:
            available_features = ['LogCost', 'LogUsage']
        
        return available_features
    
    def detect_anomalies(self, df):
        """Detect anomalies with optimized ensemble methods"""
        print("\n" + "="*70)
        print("🧟 OPTIMIZED ZOMBIE DETECTION (ENSEMBLE)")
        print("="*70)
        
        # Select best features
        available_features = self._select_best_features(df)
        print(f"✓ Selected {len(available_features)} features: {available_features[:5]}...")
        
        X = df[available_features].fillna(0).values
        
        # Scale features using RobustScaler (more robust to outliers)
        self.scaler = RobustScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Adaptive contamination based on data size and distribution
        # Use percentile-based estimation for better accuracy
        # Slightly higher floor to avoid under-detecting anomalies
        contamination_base = min(0.15, max(0.02, 50/len(df)))
        
        # Refine contamination using cost distribution
        if len(df) > 100:
            # Estimate contamination from cost distribution
            cost_percentiles = df['EffectiveCost'].quantile([0.95, 0.99])
            high_cost_threshold = cost_percentiles[0.95]
            very_high_cost_threshold = cost_percentiles[0.99]
            
            high_cost_ratio = (df['EffectiveCost'] > high_cost_threshold).sum() / len(df)
            very_high_cost_ratio = (df['EffectiveCost'] > very_high_cost_threshold).sum() / len(df)
            
            # Use a combination of methods
            contamination = min(0.15, max(contamination_base, 
                                         high_cost_ratio * 0.5 + very_high_cost_ratio * 2))
        else:
            contamination = contamination_base
        
        print(f"✓ Adaptive contamination: {contamination:.4f}")
        
        # Ensemble approach: Train multiple Isolation Forests with different parameters
        models = []
        predictions = []
        decision_scores = []
        
        # Model 1: Standard Isolation Forest
        iso1 = IsolationForest(
            n_estimators=300,
            contamination=contamination,
            max_features=min(1.0, len(available_features) / len(available_features)),
            random_state=42,
            n_jobs=-1,
            bootstrap=False,
            verbose=0
        )
        pred1 = iso1.fit_predict(X_scaled)
        dec1 = iso1.decision_function(X_scaled)
        models.append(iso1)
        predictions.append(pred1)
        decision_scores.append(dec1)
        
        # Model 2: More aggressive (higher contamination)
        iso2 = IsolationForest(
            n_estimators=300,
            contamination=min(contamination * 1.5, 0.2),
            max_features=0.8,
            random_state=43,
            n_jobs=-1,
            bootstrap=True,
            verbose=0
        )
        pred2 = iso2.fit_predict(X_scaled)
        dec2 = iso2.decision_function(X_scaled)
        models.append(iso2)
        predictions.append(pred2)
        decision_scores.append(dec2)
        
        # Model 3: More conservative
        iso3 = IsolationForest(
            n_estimators=200,
            contamination=max(contamination * 0.7, 0.01),
            max_features=1.0,
            random_state=44,
            n_jobs=-1,
            bootstrap=False,
            verbose=0
        )
        pred3 = iso3.fit_predict(X_scaled)
        dec3 = iso3.decision_function(X_scaled)
        models.append(iso3)
        predictions.append(pred3)
        decision_scores.append(dec3)
        
        # Ensemble prediction: majority vote
        ensemble_pred = np.array(predictions).sum(axis=0)
        # Anomaly if at least 2 out of 3 models agree
        df['anomaly_score'] = np.where(ensemble_pred <= -1, -1, 1)
        
        # Ensemble decision function: average
        ensemble_decision = np.array(decision_scores).mean(axis=0)
        df['decision_function'] = ensemble_decision
        
        # Normalize decision function to probability
        # Blend z-score sigmoid with rank percentile to reduce “all low” cases
        dec_std = np.std(ensemble_decision) + 1e-6
        dec_z = (ensemble_decision - np.mean(ensemble_decision)) / dec_std
        prob_sigmoid = 1 / (1 + np.exp(-dec_z))
        prob_rank = pd.Series(ensemble_decision).rank(pct=True).to_numpy()
        df['anomaly_probability'] = 0.6 * prob_sigmoid + 0.4 * prob_rank
        
        # Store primary model for saving
        self.model = models[0]
        
        # Identify zombies (anomalies)
        zombies = df[df['anomaly_score'] == -1].copy()
        
        # Enhanced confidence scoring
        if len(zombies) > 0:
            # Combine multiple signals for confidence
            zombie_scores = zombies['anomaly_probability'].copy()
            
            # Boost confidence for high-cost anomalies
            if 'EffectiveCost' in zombies.columns:
                cost_percentile = zombies['EffectiveCost'].rank(pct=True)
                zombie_scores = zombie_scores * (0.6 + 0.4 * cost_percentile)
            
            # Boost confidence for low-usage anomalies
            if 'ConsumedQuantity' in zombies.columns:
                usage_percentile = 1 - zombies['ConsumedQuantity'].rank(pct=True)
                zombie_scores = zombie_scores * (0.6 + 0.4 * usage_percentile)
            
            # Normalize scores to [0,1]
            z_min, z_max = zombie_scores.min(), zombie_scores.max()
            if z_max > z_min:
                zombie_scores = (zombie_scores - z_min) / (z_max - z_min)
            
            # Categorize by enhanced confidence (slightly lower thresholds to avoid all-low)
            conditions = [
                zombie_scores >= 0.65,
                zombie_scores >= 0.45,
                zombie_scores < 0.45
            ]
            choices = ['High', 'Medium', 'Low']
            zombies['confidence'] = np.select(conditions, choices, default='Medium')
            
            # Add confidence to main dataframe
            df.loc[df['anomaly_score'] == -1, 'confidence'] = zombies['confidence'].values
        
        # Calculate statistics
        total_waste = zombies['EffectiveCost'].sum() if len(zombies) > 0 else 0
        total_spend = df['EffectiveCost'].sum()
        waste_percentage = (total_waste / total_spend * 100) if total_spend > 0 else 0
        
        # Feature importance (using first model)
        if hasattr(self.model, 'feature_importances_'):
            self.feature_importance = dict(zip(available_features, self.model.feature_importances_))
        
        print(f"📊 Results:")
        print(f"   - Zombies detected: {len(zombies):,}")
        print(f"   - Potential waste: ${total_waste:,.2f}")
        print(f"   - Waste percentage: {waste_percentage:.2f}%")
        
        if 'confidence' in zombies.columns:
            conf_counts = zombies['confidence'].value_counts()
            print(f"   - High confidence: {conf_counts.get('High', 0):,}")
            print(f"   - Medium confidence: {conf_counts.get('Medium', 0):,}")
            print(f"   - Low confidence: {conf_counts.get('Low', 0):,}")
        
        return {
            'zombies': zombies,
            'df_with_scores': df,
            'total_waste': total_waste,
            'waste_percentage': waste_percentage,
            'zombie_count': len(zombies),
            'feature_importance': self.feature_importance
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
        """Prepare enhanced sequences for LSTM with advanced features"""
        data = daily_costs.values.flatten()
        dates = pd.to_datetime(daily_costs.index)
        
        # Create comprehensive feature set
        df_features = pd.DataFrame({
            'cost': data,
            # Rolling statistics with multiple windows
            'rolling_mean_7': pd.Series(data).rolling(7, min_periods=1).mean(),
            'rolling_mean_14': pd.Series(data).rolling(14, min_periods=1).mean(),
            'rolling_mean_30': pd.Series(data).rolling(30, min_periods=1).mean(),
            'rolling_std_7': pd.Series(data).rolling(7, min_periods=1).std(),
            'rolling_std_14': pd.Series(data).rolling(14, min_periods=1).std(),
            # Lag features
            'lag_1': pd.Series(data).shift(1),
            'lag_7': pd.Series(data).shift(7),
            'lag_14': pd.Series(data).shift(14),
            # Rate of change
            'pct_change_1': pd.Series(data).pct_change(1),
            'pct_change_7': pd.Series(data).pct_change(7),
            # Exponential moving averages
            'ema_7': pd.Series(data).ewm(span=7, adjust=False).mean(),
            'ema_14': pd.Series(data).ewm(span=14, adjust=False).mean(),
        })
        
        # Add temporal features
        df_features['day_of_week'] = dates.dayofweek
        df_features['day_of_month'] = dates.day
        df_features['month'] = dates.month
        df_features['is_weekend'] = (dates.dayofweek >= 5).astype(int)
        
        # Cyclical encoding
        df_features['day_of_week_sin'] = np.sin(2 * np.pi * df_features['day_of_week'] / 7)
        df_features['day_of_week_cos'] = np.cos(2 * np.pi * df_features['day_of_week'] / 7)
        df_features['month_sin'] = np.sin(2 * np.pi * df_features['month'] / 12)
        df_features['month_cos'] = np.cos(2 * np.pi * df_features['month'] / 12)
        
        # Handle infinite values (from pct_change on zero costs)
        df_features.replace([np.inf, -np.inf], np.nan, inplace=True)
        
        # Fill NaN values (backward fill then forward fill)
        df_features = df_features.bfill().ffill()
        # Final fill with 0 for any remaining NaNs (better for stability than mean)
        df_features = df_features.fillna(0)
        
        # Scale features individually
        self.scaler = {}
        scaled_features = []
        
        for col in df_features.columns:
            scaler = RobustScaler()  # Use RobustScaler for better outlier handling
            scaled_col = scaler.fit_transform(df_features[[col]].values)
            scaled_features.append(scaled_col)
            self.scaler[col] = scaler
        
        # Combine scaled features
        X_scaled = np.concatenate(scaled_features, axis=1)
        
        # Create sequences with proper lookback
        X, y = [], []
        for i in range(len(X_scaled) - self.lookback - self.forecast_days + 1):
            X.append(X_scaled[i:i + self.lookback])
            y.append(X_scaled[i + self.lookback:i + self.lookback + self.forecast_days, 0])
        
        return np.array(X), np.array(y), df_features.columns.tolist()
    
    def build_optimized_lstm(self, input_shape):
        """Build optimized LSTM model with improved architecture"""
        # Use Sequential for simplicity but with better architecture
        model = Sequential([
            # First LSTM layer with more units
            LSTM(128, return_sequences=True, input_shape=input_shape,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4),
                 recurrent_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.3),
            
            # Second LSTM layer
            LSTM(64, return_sequences=True,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4),
                 recurrent_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.25),
            
            # Third LSTM layer
            LSTM(32, return_sequences=False,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.2),
            
            # Dense layers
            Dense(64, activation='relu', kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.15),
            Dense(32, activation='relu'),
            Dense(self.forecast_days)
        ])
        
        # Use adaptive learning rate optimizer
        optimizer = Adam(learning_rate=0.001, beta_1=0.9, beta_2=0.999, epsilon=1e-7)
        
        # Use Huber loss for robustness to outliers
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
        
        # Use time series split for better validation
        tscv = TimeSeriesSplit(n_splits=3)
        splits = list(tscv.split(X))
        
        # Use the last split for train/val
        train_idx, val_idx = splits[-1]
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        # Additional callback for model checkpointing
        checkpoint = ModelCheckpoint(
            'best_lstm_model.keras',
            monitor='val_loss',
            save_best_only=True,
            mode='min',
            verbose=0
        )
        callbacks.append(checkpoint)
        
        # Train with validation
        # Ensure batch_size is at least 1 to avoid TensorFlow internal errors
        adaptive_batch_size = max(1, min(32, len(X_train) // 4 if len(X_train) > 0 else 1))
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=150,  # Increased epochs
            batch_size=adaptive_batch_size,  # Adaptive batch size
            callbacks=callbacks,
            verbose=0
        )
        
        # Load best weights
        if os.path.exists('best_lstm_model.keras'):
            self.model.load_weights('best_lstm_model.keras')
            os.remove('best_lstm_model.keras')
        
        best_val_loss = min(history.history['val_loss'])
        print(f"✓ Model trained. Best validation loss: {best_val_loss:.4f}")
        
        # Calculate training metrics
        train_pred = self.model.predict(X_train, verbose=0)
        val_pred = self.model.predict(X_val, verbose=0)
        
        train_mae = mean_absolute_error(y_train, train_pred)
        val_mae = mean_absolute_error(y_val, val_pred)
        train_rmse = np.sqrt(mean_squared_error(y_train, train_pred))
        val_rmse = np.sqrt(mean_squared_error(y_val, val_pred))
        
        print(f"   - Train MAE: {train_mae:.4f}, Val MAE: {val_mae:.4f}")
        print(f"   - Train RMSE: {train_rmse:.4f}, Val RMSE: {val_rmse:.4f}")
        
        # Generate forecast (robust against empty sequences)
        if len(X) == 0:
            # Fallback: simple mean-based forecast
            avg_cost = daily_costs.mean() if len(daily_costs) > 0 else 0
            forecast = np.ones(self.forecast_days) * avg_cost
        else:
            # Use multiple recent sequences for more robust prediction,
            # but guard against empty slices to avoid TensorFlow internal errors.
            num_sequences = min(5, len(X))
            start_index = max(0, len(X) - num_sequences)
            recent_indices = list(range(start_index, len(X)))
            forecast_scaled_list = []
            
            for idx in recent_indices:
                seq = X[idx:idx+1]
                # Skip if sequence is unexpectedly empty
                if seq.shape[0] == 0:
                    continue
                pred = self.model.predict(seq, verbose=0)[0]
                forecast_scaled_list.append(pred)
            
            if not forecast_scaled_list:
                # Safe fallback: use the very last sequence only
                last_sequence = X[-1:]
                forecast_scaled = self.model.predict(last_sequence, verbose=0)[0]
            else:
                # Average predictions from recent sequences
                forecast_scaled = np.mean(forecast_scaled_list, axis=0)
            
            # Inverse transform
            cost_scaler = self.scaler['cost']
            forecast = cost_scaler.inverse_transform(
                forecast_scaled.reshape(-1, 1)
            ).flatten()
            
            # Ensure non-negative forecasts
            forecast = np.maximum(forecast, 0)
        
        # Enhanced confidence intervals using quantile regression approach
        val_predictions = self.model.predict(X_val, verbose=0)
        
        # Calculate errors for each forecast day
        errors = y_val - val_predictions
        
        # Use percentile-based confidence intervals for each day
        confidence_upper = []
        confidence_lower = []
        
        for day_idx in range(self.forecast_days):
            day_errors = errors[:, day_idx] if errors.ndim > 1 else errors
            
            # Calculate percentiles
            error_95 = np.percentile(np.abs(day_errors), 95)
            error_median = np.median(np.abs(day_errors))
            
            # Use asymmetric intervals based on error distribution
            upper_bound = forecast[day_idx] + error_95
            lower_bound = np.maximum(forecast[day_idx] - error_95, 0)
            
            confidence_upper.append(upper_bound)
            confidence_lower.append(lower_bound)
        
        confidence_upper = np.array(confidence_upper)
        confidence_lower = np.array(confidence_lower)
        
        # Calculate forecast statistics
        forecast_total = forecast.sum()
        forecast_mean = forecast.mean()
        forecast_std = forecast.std()
        forecast_cv = forecast_std / forecast_mean if forecast_mean > 0 else 0
        
        print(f"📊 Forecast Results:")
        print(f"   - {self.forecast_days}-day forecast total: ${forecast_total:,.2f}")
        print(f"   - Average daily forecast: ${forecast_mean:,.2f}")
        print(f"   - Forecast coefficient of variation: {forecast_cv:.4f}")
        
        # Calculate forecast accuracy metrics
        metrics = {
            'train_mae': float(train_mae),
            'val_mae': float(val_mae),
            'train_rmse': float(train_rmse),
            'val_rmse': float(val_rmse),
            'forecast_mean': float(forecast_mean),
            'forecast_std': float(forecast_std),
            'forecast_cv': float(forecast_cv)
        }
        
        return {
            'forecast': forecast.tolist(),
            'confidence_intervals': {
                'upper': confidence_upper.tolist(),
                'lower': confidence_lower.tolist()
            },
            'method': 'advanced_lstm_optimized',
            'model': self.model,
            'scaler': self.scaler,
            'historical_data': daily_costs.tolist(),
            'metrics': metrics,
            'feature_names': list(self.scaler.keys())
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
        # MODIFIED: Changed sample_size from 50000 to None to process ALL records
        df, df_analysis = preprocessor.load_and_preprocess(data_path, sample_size=None)
        
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
        
        # Save metadata with enhanced information
        import json
        metadata = {
            'training_date': datetime.now().isoformat(),
            'data_source': data_path,
            'records_analyzed': len(df_analysis),
            'zombie_count': zombie_results['zombie_count'],
            'total_waste': zombie_results['total_waste'],
            'waste_percentage': zombie_results['waste_percentage'],
            'forecast_total': sum(forecast_results['forecast']),
            'forecast_metrics': forecast_results.get('metrics', {}),
            'feature_importance': zombie_results.get('feature_importance', {}),
            'model_version': 'optimized_v3'
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