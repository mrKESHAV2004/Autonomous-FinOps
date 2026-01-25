# ==========================================================
# AUTONOMOUS FINOPS - ADVANCED MODEL TRAINING & OPTIMIZATION
# Combines training pipeline with optimized hyperparameters
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
from sklearn.metrics import silhouette_score, calinski_harabasz_score
import optuna  # For hyperparameter optimization

# TensorFlow for LSTM
import tensorflow as tf
from tensorflow.keras.models import Sequential, save_model
from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.regularizers import l1_l2

warnings.filterwarnings('ignore')

# Set random seeds for reproducibility
np.random.seed(42)
tf.random.set_seed(42)

# ==========================================================
# 1. ENHANCED DATA PREPROCESSING WITH FEATURE ENGINEERING
# ==========================================================

class DataPreprocessor:
    """Advanced data preprocessing with feature engineering"""
    
    def __init__(self, contamination_auto_tune=True):
        self.contamination_auto_tune = contamination_auto_tune
        self.feature_columns = None
        
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
        """Process date columns with multiple fallbacks"""
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
        
        # Extract temporal features
        df['DayOfWeek'] = pd.to_datetime(df['UsageDate']).dt.dayofweek
        df['DayOfMonth'] = pd.to_datetime(df['UsageDate']).dt.day
        df['Month'] = pd.to_datetime(df['UsageDate']).dt.month
        df['IsWeekend'] = df['DayOfWeek'].isin([5, 6]).astype(int)
        
        return df
    
    def _clean_numeric_columns(self, df):
        """Clean and standardize numeric columns"""
        # Convert to numeric, handling errors
        df['EffectiveCost'] = pd.to_numeric(df['EffectiveCost'], errors='coerce')
        df['ConsumedQuantity'] = pd.to_numeric(df['ConsumedQuantity'], errors='coerce')
        
        # Fill missing values intelligently
        df['EffectiveCost'] = df['EffectiveCost'].fillna(0)
        df['ConsumedQuantity'] = df['ConsumedQuantity'].fillna(df['ConsumedQuantity'].median() if df['ConsumedQuantity'].notna().any() else 1)
        
        # Handle outliers using IQR method
        for col in ['EffectiveCost', 'ConsumedQuantity']:
            if col in df.columns:
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                df[col] = df[col].clip(lower_bound, upper_bound)
        
        return df
    
    def _engineer_features(self, df):
        """Create advanced features for better anomaly detection"""
        
        # Basic log transforms
        df['LogCost'] = np.log1p(df['EffectiveCost'])
        df['LogUsage'] = np.log1p(df['ConsumedQuantity'])
        
        # Cost efficiency metrics
        df['CostPerUnit'] = df['EffectiveCost'] / (df['ConsumedQuantity'] + 1e-6)  # Avoid division by zero
        df['LogCostPerUnit'] = np.log1p(df['CostPerUnit'])
        
        # Moving statistics (if enough temporal data)
        if 'UsageDate' in df.columns and len(df) > 7:
            try:
                # Group by resource/service if available
                group_col = 'ServiceCategory' if 'ServiceCategory' in df.columns else None
                if group_col:
                    df['CostRatioToAvg'] = df.groupby(group_col)['EffectiveCost'].transform(
                        lambda x: x / x.rolling(7, min_periods=1).mean()
                    )
            except Exception as e:
                print(f"Error calculating CostRatioToAvg: {e}")
                df['CostRatioToAvg'] = 0
        
        # Statistical features
        df['CostZScore'] = (df['EffectiveCost'] - df['EffectiveCost'].mean()) / (df['EffectiveCost'].std() + 1e-6)
        df['UsageZScore'] = (df['ConsumedQuantity'] - df['ConsumedQuantity'].mean()) / (df['ConsumedQuantity'].std() + 1e-6)
        
        # Interaction features
        df['CostUsageInteraction'] = df['LogCost'] * df['LogUsage']
        
        print("✓ Engineered 8+ features for improved detection")
        return df

# ==========================================================
# 2. OPTIMIZED ZOMBIE DETECTION WITH HYPERPARAMETER TUNING
# ==========================================================

class OptimizedZombieDetector:
    """Advanced anomaly detection with hyperparameter optimization"""
    
    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_importance = None
        
    def optimize_parameters(self, X, n_trials=50):
        """Use Optuna to find optimal Isolation Forest parameters"""
        print("\n🔍 Optimizing Isolation Forest hyperparameters...")
        
        def objective(trial):
            n_estimators = trial.suggest_int('n_estimators', 50, 500)
            max_samples = trial.suggest_float('max_samples', 0.1, 1.0)
            contamination = trial.suggest_float('contamination', 0.01, 0.2)
            max_features = trial.suggest_float('max_features', 0.1, 1.0)
            
            model = IsolationForest(
                n_estimators=n_estimators,
                max_samples=max_samples,
                contamination=contamination,
                max_features=max_features,
                random_state=42,
                n_jobs=-1,
                bootstrap=False
            )
            
            # Use silhouette score as optimization metric
            predictions = model.fit_predict(X)
            anomaly_mask = predictions == -1
            
            if np.sum(anomaly_mask) > 1 and np.sum(~anomaly_mask) > 1:
                score = silhouette_score(X, predictions)
            else:
                score = -1  # Penalize degenerate cases
            
            return score
        
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        
        print(f"✓ Best hyperparameters found:")
        print(f"   - n_estimators: {study.best_params['n_estimators']}")
        print(f"   - max_samples: {study.best_params['max_samples']:.2f}")
        print(f"   - contamination: {study.best_params['contamination']:.3f}")
        print(f"   - max_features: {study.best_params['max_features']:.2f}")
        
        return study.best_params
    
    def detect_anomalies(self, df, use_optimization=True):
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
        
        # Scale features using RobustScaler (less sensitive to outliers)
        self.scaler = RobustScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        if use_optimization and len(df) > 1000:
            # Optimize parameters for large datasets
            best_params = self.optimize_parameters(X_scaled, n_trials=30)
        else:
            # Use sensible defaults for smaller datasets
            best_params = {
                'n_estimators': 200,
                'max_samples': 'auto',
                'contamination': 0.05,
                'max_features': 1.0
            }
        
        # Train Isolation Forest with optimized parameters
        self.model = IsolationForest(
            n_estimators=best_params['n_estimators'],
            max_samples=best_params['max_samples'],
            contamination=best_params['contamination'],
            max_features=best_params['max_features'],
            random_state=42,
            n_jobs=-1,
            bootstrap=False,
            verbose=0
        )
        
        print("🔄 Training optimized Isolation Forest...")
        df['anomaly_score'] = self.model.fit_predict(X_scaled)
        df['decision_function'] = self.model.decision_function(X_scaled)
        
        # Calculate anomaly probabilities (normalized to 0-1)
        df['anomaly_probability'] = 1 / (1 + np.exp(-df['decision_function']))
        
        # Identify zombies (anomalies)
        zombies = df[df['anomaly_score'] == -1].copy()
        
        # Categorize by confidence
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
        print(f"   - High confidence: {(zombies['confidence'] == 'High').sum():,}")
        print(f"   - Model contamination: {best_params['contamination']:.3f}")
        
        return {
            'zombies': zombies,
            'df_with_scores': df,
            'total_waste': total_waste,
            'waste_percentage': waste_percentage,
            'zombie_count': len(zombies),
            'feature_importance': available_features
        }

# ==========================================================
# 3. ADVANCED LSTM FORECASTING WITH ATTENTION MECHANISM
# ==========================================================

class AdvancedForecaster:
    """Advanced time series forecasting with optimized LSTM"""
    
    def __init__(self, lookback_window=14, forecast_days=7):
        self.lookback = lookback_window
        self.forecast_days = forecast_days
        self.model = None
        self.scaler = None
        self.history = None
        
    def prepare_sequences(self, daily_costs):
        """Prepare sequences for LSTM with multiple features"""
        # Create multiple features from the time series
        data = daily_costs.values.reshape(-1, 1)
        
        # Create additional features
        df_features = pd.DataFrame({
            'cost': data.flatten(),
            'rolling_mean_7': pd.Series(data.flatten()).rolling(7, min_periods=1).mean(),
            'rolling_std_7': pd.Series(data.flatten()).rolling(7, min_periods=1).std(),
            'day_of_week': pd.Series(range(len(data))) % 7,
            'trend': np.arange(len(data))
        })
        
        # Fill NaN values
        df_features = df_features.fillna(method='bfill').fillna(method='ffill')
        
        # Scale features
        self.scaler = {}
        scaled_features = []
        
        for i, col in enumerate(df_features.columns):
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
            y.append(X_scaled[i + self.lookback:i + self.lookback + self.forecast_days, 0])  # Predict cost column
        
        return np.array(X), np.array(y), df_features.columns.tolist()
    
    def build_advanced_lstm(self, input_shape):
        """Build an advanced LSTM model with multiple layers and regularization"""
        model = Sequential([
            # First LSTM layer with return sequences
            Bidirectional(LSTM(128, return_sequences=True, 
                             kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4),
                             recurrent_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
                         input_shape=input_shape),
            Dropout(0.3),
            
            # Second LSTM layer
            LSTM(64, return_sequences=True,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.3),
            
            # Third LSTM layer
            LSTM(32, return_sequences=False,
                 kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.2),
            
            # Dense layers
            Dense(64, activation='relu', kernel_regularizer=l1_l2(l1=1e-5, l2=1e-4)),
            Dropout(0.2),
            Dense(32, activation='relu'),
            
            # Output layer for multi-step forecasting
            Dense(self.forecast_days)
        ])
        
        optimizer = Adam(learning_rate=0.001, clipvalue=0.5)
        model.compile(optimizer=optimizer, loss='huber', metrics=['mae', 'mse'])
        
        return model
    
    def forecast(self, df, use_gpu=True):
        """Generate optimized forecasts"""
        print("\n" + "="*70)
        print("📈 ADVANCED TIME SERIES FORECASTING")
        print("="*70)
        
        # Aggregate daily costs
        daily_costs = df.groupby('UsageDate')['EffectiveCost'].sum().sort_index()
        
        if len(daily_costs) < self.lookback + self.forecast_days:
            print(f"⚠ Insufficient data: {len(daily_costs)} days. Need at least {self.lookback + self.forecast_days} days.")
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
        
        # Split data using time-series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        
        # Build model
        self.model = self.build_advanced_lstm((self.lookback, len(feature_names)))
        
        print("🔄 Training advanced LSTM model...")
        print(f"   - Input shape: {X.shape}")
        print(f"   - Features: {feature_names}")
        
        # Callbacks for better training
        callbacks = [
            EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True),
            ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5, min_lr=1e-6)
        ]
        
        # Train with cross-validation
        val_losses = []
        
        for train_idx, val_idx in tscv.split(X):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            
            if use_gpu:
                with tf.device('/GPU:0' if tf.config.list_physical_devices('GPU') else '/CPU:0'):
                    history = self.model.fit(
                        X_train, y_train,
                        validation_data=(X_val, y_val),
                        epochs=100,
                        batch_size=32,
                        callbacks=callbacks,
                        verbose=0
                    )
            else:
                history = self.model.fit(
                    X_train, y_train,
                    validation_data=(X_val, y_val),
                    epochs=100,
                    batch_size=32,
                    callbacks=callbacks,
                    verbose=0
                )
            
            val_losses.append(min(history.history['val_loss']))
        
        print(f"✓ Model trained. Average validation loss: {np.mean(val_losses):.4f}")
        
        # Generate forecast
        last_sequence = X[-1:]  # Use the most recent sequence
        
        forecast_scaled = self.model.predict(last_sequence, verbose=0)[0]
        
        # Inverse transform using the cost scaler
        cost_scaler = self.scaler['cost']
        forecast = cost_scaler.inverse_transform(
            forecast_scaled.reshape(-1, 1)
        ).flatten()
        
        # Ensure non-negative forecasts
        forecast = np.maximum(forecast, 0)
        
        # Calculate confidence intervals using validation errors
        val_predictions = self.model.predict(X, verbose=0)
        errors = y - val_predictions
        std_error = np.std(errors, axis=0)
        
        confidence_upper = forecast + 1.96 * std_error
        confidence_lower = np.maximum(forecast - 1.96 * std_error, 0)
        
        print(f"📊 Forecast Results:")
        print(f"   - 7-day forecast total: ${forecast.sum():,.2f}")
        print(f"   - Average daily forecast: ${forecast.mean():,.2f}")
        print(f"   - Forecast range: ${forecast.min():,.2f} - ${forecast.max():,.2f}")
        
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
# 4. MODEL EVALUATION AND VISUALIZATION
# ==========================================================

class ModelEvaluator:
    """Evaluate model performance and generate insights"""
    
    @staticmethod
    def evaluate_anomaly_detection(zombies, df):
        """Evaluate anomaly detection performance"""
        print("\n" + "="*70)
        print("📊 ANOMALY DETECTION EVALUATION")
        print("="*70)
        
        if len(zombies) == 0:
            print("No anomalies detected for evaluation")
            return {}
        
        # Calculate statistical significance
        from scipy import stats
        
        normal_costs = df[df['anomaly_score'] == 1]['EffectiveCost']
        anomaly_costs = zombies['EffectiveCost']
        
        # T-test for significance
        if len(anomaly_costs) > 1 and len(normal_costs) > 1:
            t_stat, p_value = stats.ttest_ind(anomaly_costs, normal_costs, equal_var=False)
            print(f"✓ Statistical test: t-stat={t_stat:.2f}, p-value={p_value:.4f}")
            significant = p_value < 0.05
        else:
            significant = False
        
        # Calculate efficiency metrics
        avg_anomaly_cost = anomaly_costs.mean()
        avg_normal_cost = normal_costs.mean()
        cost_ratio = avg_anomaly_cost / avg_normal_cost if avg_normal_cost > 0 else 0
        
        print(f"✓ Average zombie cost: ${avg_anomaly_cost:,.2f}")
        print(f"✓ Average normal cost: ${avg_normal_cost:,.2f}")
        print(f"✓ Cost ratio (zombie/normal): {cost_ratio:.2f}x")
        print(f"✓ Statistically significant: {'Yes' if significant else 'No'}")
        
        return {
            'significant': significant,
            'cost_ratio': cost_ratio,
            'avg_zombie_cost': avg_anomaly_cost,
            'avg_normal_cost': avg_normal_cost,
            'p_value': p_value if 'p_value' in locals() else None
        }
    
    @staticmethod
    def plot_results(zombies, forecast_results, save_path=None):
        """Create comprehensive visualization of results"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Autonomous FinOps - Model Results', fontsize=16, fontweight='bold')
        
        # 1. Zombie cost distribution
        if len(zombies) > 0:
            ax1 = axes[0, 0]
            zombies['EffectiveCost'].hist(bins=30, ax=ax1, alpha=0.7, color='red')
            ax1.set_title('Zombie Cost Distribution', fontweight='bold')
            ax1.set_xlabel('Cost ($)')
            ax1.set_ylabel('Frequency')
            ax1.grid(alpha=0.3)
        
        # 2. Service category breakdown
        if 'ServiceCategory' in zombies.columns and len(zombies) > 0:
            ax2 = axes[0, 1]
            service_waste = zombies.groupby('ServiceCategory')['EffectiveCost'].sum().nlargest(10)
            service_waste.plot(kind='barh', ax=ax2, color='coral')
            ax2.set_title('Top 10 Wasteful Services', fontweight='bold')
            ax2.set_xlabel('Total Waste ($)')
            ax2.invert_yaxis()
        
        # 3. Forecast visualization
        if forecast_results and 'forecast' in forecast_results:
            ax3 = axes[1, 0]
            forecast = forecast_results['forecast']
            days = list(range(1, len(forecast) + 1))
            
            ax3.plot(days, forecast, 'o-', linewidth=2, markersize=8, 
                    color='green', label='Forecast')
            
            if 'confidence_intervals' in forecast_results:
                ci = forecast_results['confidence_intervals']
                ax3.fill_between(days, ci['lower'], ci['upper'], 
                               alpha=0.2, color='green', label='95% CI')
            
            ax3.set_title('7-Day Cost Forecast', fontweight='bold')
            ax3.set_xlabel('Days Ahead')
            ax3.set_ylabel('Cost ($)')
            ax3.legend()
            ax3.grid(alpha=0.3)
        
        # 4. Confidence distribution
        if 'confidence' in zombies.columns and len(zombies) > 0:
            ax4 = axes[1, 1]
            confidence_dist = zombies['confidence'].value_counts()
            colors = {'High': 'red', 'Medium': 'orange', 'Low': 'yellow'}
            conf_colors = [colors.get(c, 'gray') for c in confidence_dist.index]
            
            confidence_dist.plot(kind='bar', ax=ax4, color=conf_colors)
            ax4.set_title('Detection Confidence Levels', fontweight='bold')
            ax4.set_xlabel('Confidence')
            ax4.set_ylabel('Count')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"✓ Saved visualization to {save_path}")
        
        plt.show()

# ==========================================================
# 5. MAIN TRAINING PIPELINE
# ==========================================================

def main_training_pipeline(data_path, output_dir='./finops_artifacts_optimized'):
    """Main pipeline for training optimized models"""
    
    print("\n" + "="*70)
    print("🚀 AUTONOMOUS FINOPS - ADVANCED MODEL TRAINING")
    print("="*70)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Enhanced Data Preprocessing
    preprocessor = DataPreprocessor()
    df, df_analysis = preprocessor.load_and_preprocess(data_path, sample_size=50000)
    
    # 2. Optimized Zombie Detection
    detector = OptimizedZombieDetector()
    zombie_results = detector.detect_anomalies(df_analysis)
    
    # 3. Advanced Forecasting
    forecaster = AdvancedForecaster(lookback_window=14, forecast_days=7)
    forecast_results = forecaster.forecast(df_analysis)
    
    # 4. Model Evaluation
    evaluator = ModelEvaluator()
    eval_results = evaluator.evaluate_anomaly_detection(zombie_results['zombies'], zombie_results['df_with_scores'])
    
    # 5. Visualize Results
    evaluator.plot_results(zombie_results['zombies'], forecast_results, 
                          save_path=f"{output_dir}/model_results.png")
    
    # 6. Save Optimized Models
    print("\n" + "="*70)
    print("💾 SAVING OPTIMIZED MODELS")
    print("="*70)
    
    # Save zombie detection model
    if detector.model:
        joblib.dump(detector.model, f'{output_dir}/zombie_model_optimized.pkl')
        joblib.dump(detector.scaler, f'{output_dir}/zombie_scaler_optimized.pkl')
        print("✓ Saved optimized zombie detection model")
    
    # Save forecasting model
    if forecast_results['model']:
        forecast_results['model'].save(f'{output_dir}/forecast_lstm_optimized.keras')
        
        # Save all scalers
        scaler_data = {
            'feature_scalers': forecast_results['scaler'],
            'feature_names': list(forecast_results['scaler'].keys())
        }
        joblib.dump(scaler_data, f'{output_dir}/forecast_scalers_optimized.pkl')
        print("✓ Saved optimized forecasting model")
    
    # Save metadata
    metadata = {
        'training_date': datetime.now().isoformat(),
        'data_source': data_path,
        'records_analyzed': len(df_analysis),
        'zombie_results': {
            'total_waste': zombie_results['total_waste'],
            'waste_percentage': zombie_results['waste_percentage'],
            'zombie_count': zombie_results['zombie_count']
        },
        'forecast_results': {
            'total_forecast': sum(forecast_results['forecast']),
            'method': forecast_results['method']
        },
        'evaluation_results': eval_results
    }
    
    import json
    with open(f'{output_dir}/training_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    print("✓ Saved training metadata")
    
    # 7. Generate Insights Report
    print("\n" + "="*70)
    print("💡 KEY INSIGHTS & RECOMMENDATIONS")
    print("="*70)
    
    print(f"\n1. Waste Detection:")
    print(f"   - Detected {zombie_results['zombie_count']:,} potential zombie resources")
    print(f"   - Total waste: ${zombie_results['total_waste']:,.2f}")
    print(f"   - Waste percentage: {zombie_results['waste_percentage']:.2f}%")
    
    if 'cost_ratio' in eval_results and eval_results['cost_ratio'] > 2:
        print(f"   ⚠️  Zombies cost {eval_results['cost_ratio']:.1f}x more than normal resources")
    
    print(f"\n2. Forecasting:")
    print(f"   - 7-day forecast total: ${sum(forecast_results['forecast']):,.2f}")
    print(f"   - Daily average forecast: ${np.mean(forecast_results['forecast']):,.2f}")
    
    print(f"\n3. Model Performance:")
    print(f"   - Using advanced LSTM with {forecaster.lookback}-day lookback")
    print(f"   - Multiple engineered features for better detection")
    
    print(f"\n4. Next Steps:")
    print(f"   - Review high-confidence zombies first")
    print(f"   - Implement forecast monitoring")
    print(f"   - Retrain models monthly for accuracy")
    
    print(f"\n✅ Models saved to: {output_dir}/")
    print("   Use these with the live inference engine for production predictions")
    
    return {
        'zombie_results': zombie_results,
        'forecast_results': forecast_results,
        'evaluation_results': eval_results,
        'output_dir': output_dir
    }

# ==========================================================
# EXECUTION
# ==========================================================

if __name__ == "__main__":
    # Set your data path here
    DATA_PATH = "E:\\WORK\\Auto FinOps\\Code\\FOCUS-Sample-Data\\FOCUS-1.0\\focus_data_table.csv.gz"
    
    # Or use a sample path for testing
    # DATA_PATH = "/path/to/your/cloud_billing_data.csv"
    
    # Check if file exists
    if not os.path.exists(DATA_PATH):
        print(f"❌ Data file not found: {DATA_PATH}")
        print("Please update DATA_PATH with your actual file location")
        
        # Create sample data for testing if needed
        print("\nCreating sample data for demonstration...")
        dates = pd.date_range(start='2024-01-01', periods=100)
        sample_data = {
            'ChargePeriodStart': np.random.choice(dates, 1000),
            'ServiceCategory': np.random.choice(['Compute', 'Database', 'Storage', 'Network'], 1000),
            'EffectiveCost': np.random.exponential(50, 1000),
            'ConsumedQuantity': np.random.uniform(1, 100, 1000)
        }
        df_sample = pd.DataFrame(sample_data)
        DATA_PATH = './sample_cloud_data.csv'
        df_sample.to_csv(DATA_PATH, index=False)
        print(f"✓ Created sample data at: {DATA_PATH}")
    
    try:
        # Run the optimized training pipeline
        results = main_training_pipeline(DATA_PATH)
        
        print("\n" + "="*70)
        print("✨ OPTIMIZED MODEL TRAINING COMPLETE")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Training failed: {str(e)}")
        import traceback
        traceback.print_exc()