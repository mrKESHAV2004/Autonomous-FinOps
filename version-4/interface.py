import os
import io
import base64
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import cm
import seaborn as sns
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Import optimized ML functions
try:
    from ml import DataPreprocessor, OptimizedZombieDetector, AdvancedForecaster
    USE_OPTIMIZED_ML = True
except ImportError:
    print("⚠ Warning: Could not import optimized ML functions. Using fallback implementations.")
    USE_OPTIMIZED_ML = False
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler, RobustScaler, LabelEncoder
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout

app = Flask(__name__)
app.secret_key = 'super_secret_finops_key'

# Configuration
UPLOAD_FOLDER = 'uploads'
ARTIFACT_DIR = 'finops_artifacts'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 12

# Color palette
COLORS = {
    'primary': '#4F46E5',
    'success': '#10B981',
    'danger': '#EF4444',
    'warning': '#F59E0B',
    'info': '#3B82F6',
    'gray': '#6B7280'
}

# ==========================================================
# ENHANCED HELPER FUNCTIONS
# ==========================================================

def load_and_prep_data(filepath):
    """Enhanced data preprocessing with feature engineering"""
    if USE_OPTIMIZED_ML:
        # Use optimized preprocessor from ml.py
        preprocessor = DataPreprocessor()
        # Explicitly pass sample_size=None to process all records
        _, df = preprocessor.load_and_preprocess(filepath, sample_size=None)
        return df
    else:
        # Fallback implementation
        try:
            df = pd.read_csv(filepath)
        except Exception as e:
            raise Exception(f"Failed to read CSV: {str(e)}")
        
        # Date processing
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
            base_date = datetime.now().date() - timedelta(days=len(df))
            df['UsageDate'] = [base_date + timedelta(days=i) for i in range(len(df))]
        
        # Standardize column names
        cost_cols = ['EffectiveCost', 'Cost', 'Amount', 'UnblendedCost']
        usage_cols = ['ConsumedQuantity', 'UsageQuantity', 'UsageAmount']
        
        # Find and rename cost column
        for col in cost_cols:
            if col in df.columns:
                df.rename(columns={col: 'EffectiveCost'}, inplace=True)
                break
        
        # Find and rename usage column
        for col in usage_cols:
            if col in df.columns:
                df.rename(columns={col: 'ConsumedQuantity'}, inplace=True)
                break
        
        if 'ConsumedQuantity' not in df.columns:
            df['ConsumedQuantity'] = 1
        
        # Convert to numeric
        df['EffectiveCost'] = pd.to_numeric(df['EffectiveCost'], errors='coerce').fillna(0)
        df['ConsumedQuantity'] = pd.to_numeric(df['ConsumedQuantity'], errors='coerce').fillna(1)
        
        # Filter positive costs (matching ml.py logic)
        df = df[df['EffectiveCost'] > 0].copy()
        
        if len(df) == 0:
            raise Exception("No positive cost records found in the data")
        
        # Basic feature engineering
        df['LogCost'] = np.log1p(df['EffectiveCost'])
        df['LogUsage'] = np.log1p(df['ConsumedQuantity'])
        df['CostPerUnit'] = df['EffectiveCost'] / (df['ConsumedQuantity'] + 1e-6)
        df['LogCostPerUnit'] = np.log1p(df['CostPerUnit'])
        
        # Statistical features
        df['CostZScore'] = (df['EffectiveCost'] - df['EffectiveCost'].mean()) / (df['EffectiveCost'].std() + 1e-6)
        df['UsageZScore'] = (df['ConsumedQuantity'] - df['ConsumedQuantity'].mean()) / (df['ConsumedQuantity'].std() + 1e-6)
        df['CostUsageInteraction'] = df['LogCost'] * df['LogUsage']
        
        # New Features (Aligning with ml.py improvements)
        df['CostSquared'] = df['EffectiveCost'] ** 2
        df['UsageSquared'] = df['ConsumedQuantity'] ** 2
        df['LogCostRatio'] = df['LogCost'] / (df['LogUsage'] + 1e-6)
        
        if 'ServiceCategory' in df.columns:
            service_freq = df['ServiceCategory'].value_counts(normalize=True)
            df['ServiceFrequency'] = df['ServiceCategory'].map(service_freq)
        
        print(f"✓ Preprocessed {len(df):,} records with enhanced features (Fallback)")
        return df

def detect_zombies(df):
    """Enhanced zombie detection with multiple features"""
    if USE_OPTIMIZED_ML:
        # Use optimized detector from ml.py
        detector = OptimizedZombieDetector()
        results = detector.detect_anomalies(df)
        
        zombies = results['zombies']
        df_with_scores = results['df_with_scores']
        
        # Calculate confidence summary
        confidence_summary = {'High': 0, 'Medium': 0, 'Low': 0}
        if len(zombies) > 0 and 'confidence' in zombies.columns:
            for conf in zombies['confidence']:
                if conf in confidence_summary:
                    confidence_summary[conf] += 1
        
        return df_with_scores, zombies, detector.model, detector.scaler, confidence_summary
    else:
        # Fallback implementation
        if len(df) < 20:
            df['is_anomaly'] = 1
            df['anomaly_score'] = 0
            df['confidence'] = 'Low'
            return df, pd.DataFrame(), None, None, {'High': 0, 'Medium': 0, 'Low': 0}
        
        # Select features (Updated to include new ml.py features)
        feature_candidates = [
            'LogCost', 'LogUsage', 'CostPerUnit', 'LogCostPerUnit', 
            'CostZScore', 'UsageZScore', 'CostUsageInteraction',
            'CostSquared', 'UsageSquared', 'LogCostRatio', 'ServiceFrequency'
        ]
        available_features = [f for f in feature_candidates if f in df.columns]
        
        if len(available_features) < 2:
            available_features = ['LogCost', 'LogUsage']
        
        X = df[available_features].fillna(0).values
        
        # Scale with RobustScaler (matching ml.py)
        scaler = RobustScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Adaptive contamination
        contamination = min(0.1, max(0.01, 50/len(df)))
        
        # Train Isolation Forest
        iso_forest = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            max_features=1.0,
            random_state=42,
            n_jobs=-1,
            bootstrap=False,
            verbose=0
        )
        
        df['anomaly_score'] = iso_forest.fit_predict(X_scaled)
        df['decision_function'] = iso_forest.decision_function(X_scaled)
        df['anomaly_probability'] = 1 / (1 + np.exp(-df['decision_function']))
        
        zombies = df[df['anomaly_score'] == -1].copy()
        
        # Calculate confidence
        confidence_summary = {'High': 0, 'Medium': 0, 'Low': 0}
        if len(zombies) > 0:
            conditions = [
                zombies['anomaly_probability'] > 0.7,
                zombies['anomaly_probability'] > 0.4,
                zombies['anomaly_probability'] <= 0.4
            ]
            choices = ['High', 'Medium', 'Low']
            zombies['confidence'] = np.select(conditions, choices, default='Medium')
            
            # Update confidence summary
            for conf in zombies['confidence']:
                if conf in confidence_summary:
                    confidence_summary[conf] += 1
        
        return df, zombies, iso_forest, scaler, confidence_summary

def train_and_forecast(df, forecast_days=7):
    """Enhanced LSTM forecasting"""
    if USE_OPTIMIZED_ML:
        # Use optimized forecaster from ml.py
        forecaster = AdvancedForecaster(lookback_window=14, forecast_days=forecast_days)
        results = forecaster.forecast(df)
        
        # Aggregate daily costs for return
        daily_costs = df.groupby('UsageDate')['EffectiveCost'].sum().sort_index()
        
        forecast = np.array(results['forecast'])
        forecast_lower = np.array(results['confidence_intervals']['lower']) if results['confidence_intervals'] else forecast * 0.9
        forecast_upper = np.array(results['confidence_intervals']['upper']) if results['confidence_intervals'] else forecast * 1.1
        
        return daily_costs, forecast, forecast_lower, forecast_upper, results['model'], results['scaler']
    else:
        # Fallback implementation
        if len(df) < 14:
            daily_costs = pd.Series(dtype=float)
            forecast = np.zeros(forecast_days)
            return daily_costs, forecast, forecast * 0.9, forecast * 1.1, None, None
        
        # Aggregate daily costs
        daily_costs = df.groupby('UsageDate')['EffectiveCost'].sum().sort_index()
        
        if len(daily_costs) < 21:  # Need at least 21 days for good forecasting
            avg_cost = daily_costs.mean() if len(daily_costs) > 0 else 0
            forecast = np.ones(forecast_days) * avg_cost
            return daily_costs, forecast, forecast * 0.9, forecast * 1.1, None, None
        
        # Prepare enhanced features
        data = daily_costs.values.reshape(-1, 1)
        
        # Create multiple features
        df_features = pd.DataFrame({
            'cost': data.flatten(),
            'rolling_mean_7': pd.Series(data.flatten()).rolling(7, min_periods=1).mean(),
            'rolling_std_7': pd.Series(data.flatten()).rolling(7, min_periods=1).std(),
            'day_of_week': pd.Series(range(len(data))) % 7
        }).bfill().ffill()
        
        # Handle infinite values (Safety check matching ml.py)
        df_features.replace([np.inf, -np.inf], 0, inplace=True)
        
        # Scale features with RobustScaler (matching ml.py)
        scalers = {}
        scaled_features = []
        for col in df_features.columns:
            scaler = RobustScaler()
            scaled_col = scaler.fit_transform(df_features[[col]].values)
            scaled_features.append(scaled_col)
            scalers[col] = scaler
        
        X_scaled = np.concatenate(scaled_features, axis=1)
        
        # Create sequences
        lookback = min(14, len(X_scaled) - forecast_days)
        X, y = [], []
        for i in range(len(X_scaled) - lookback - forecast_days + 1):
            X.append(X_scaled[i:i + lookback])
            y.append(X_scaled[i + lookback:i + lookback + forecast_days, 0])
        
        X, y = np.array(X), np.array(y)
        
        if len(X) == 0:
            avg_cost = daily_costs.mean()
            forecast = np.ones(forecast_days) * avg_cost
            return daily_costs, forecast, forecast * 0.9, forecast * 1.1, None, None
        
        # Build LSTM model
        model = Sequential([
            LSTM(64, return_sequences=True, input_shape=(lookback, len(df_features.columns))),
            Dropout(0.3),
            LSTM(32, return_sequences=False),
            Dropout(0.2),
            Dense(32, activation='relu'),
            Dense(forecast_days)
        ])
        
        model.compile(optimizer='adam', loss='huber', metrics=['mae'])
        
        # Train
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        early_stopping = tf.keras.callbacks.EarlyStopping(
            monitor='val_loss', 
            patience=10, 
            restore_best_weights=True
        )
        
        model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=100,
            batch_size=32,
            callbacks=[early_stopping],
            verbose=0
        )
        
        # Generate forecast
        last_sequence = X[-1:]
        forecast_scaled = model.predict(last_sequence, verbose=0)[0]
        
        # Inverse transform
        cost_scaler = scalers['cost']
        forecast = cost_scaler.inverse_transform(
            forecast_scaled.reshape(-1, 1)
        ).flatten()
        
        forecast = np.maximum(forecast, 0)
        
        # Confidence intervals
        val_predictions = model.predict(X_val, verbose=0)
        errors = y_val - val_predictions
        std_error = np.std(errors, axis=0) if len(errors) > 0 else np.std(forecast) * 0.1
        
        forecast_upper = forecast + 1.96 * std_error
        forecast_lower = np.maximum(forecast - 1.96 * std_error, 0)
        
        return daily_costs, forecast, forecast_lower, forecast_upper, model, scalers

def generate_plots(daily_costs, forecast, forecast_lower, forecast_upper, 
                  zombie_savings, zombies, confidence_summary):
    """Generate enhanced visualizations"""
    plots = {}
    
    # 1. Main Forecast Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Historical data
    if len(daily_costs) > 0:
        hist_dates = pd.to_datetime(daily_costs.index)
        ax1.plot(hist_dates, daily_costs.values, 
                label='Historical Spend', 
                color=COLORS['primary'], 
                linewidth=2.5,
                marker='o',
                markersize=4)
    
    # Forecast
    if len(forecast) > 0 and len(daily_costs) > 0:
        last_date = hist_dates[-1]
        future_dates = [last_date + timedelta(days=i+1) for i in range(len(forecast))]
        
        # BAU forecast
        ax1.plot(future_dates, forecast, 
                label='BAU Forecast', 
                color=COLORS['danger'], 
                linestyle='--', 
                linewidth=2)
        
        # Confidence interval
        ax1.fill_between(future_dates, forecast_lower, forecast_upper, 
                       color=COLORS['danger'], alpha=0.15, label='95% CI')
        
        # Optimized forecast
        daily_waste = zombie_savings / max(len(daily_costs), 1)
        optimized_forecast = np.maximum(forecast - daily_waste, 0)
        
        ax1.plot(future_dates, optimized_forecast, 
                label='Optimized Forecast', 
                color=COLORS['success'], 
                linestyle='-', 
                linewidth=2.5)
    
    ax1.set_title('Cloud Spend Forecast & Optimization', fontsize=14, fontweight='bold')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Daily Cost ($)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
    
    # 2. Confidence Distribution
    labels = list(confidence_summary.keys())
    values = list(confidence_summary.values())
    colors = [COLORS['danger'], COLORS['warning'], COLORS['info']]
    
    ax2.bar(labels, values, color=colors)
    ax2.set_title('Detection Confidence Levels', fontsize=14, fontweight='bold')
    ax2.set_ylabel('Count')
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for i, v in enumerate(values):
        ax2.text(i, v + 0.5, str(v), ha='center', fontweight='bold')
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    plots['main_plot'] = base64.b64encode(buf.getvalue()).decode()
    plt.close()
    
    # 3. Zombie Analysis Plot
    if len(zombies) > 0 and 'ServiceCategory' in zombies.columns:
        fig, ax = plt.subplots(figsize=(10, 6))
        
        service_waste = zombies.groupby('ServiceCategory')['EffectiveCost'].sum().sort_values(ascending=False).head(10)
        
        colors_bar = plt.cm.coolwarm(np.linspace(0.2, 0.8, len(service_waste)))
        bars = ax.barh(range(len(service_waste)), service_waste.values, color=colors_bar)
        
        ax.set_yticks(range(len(service_waste)))
        ax.set_yticklabels(service_waste.index)
        ax.set_xlabel('Waste Amount ($)')
        ax.set_title('Top Wasteful Service Categories', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')
        
        for i, (bar, val) in enumerate(zip(bars, service_waste.values)):
            ax.text(val + val*0.01, i, f'${val:,.0f}', va='center', fontsize=10)
        
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        plots['zombie_analysis'] = base64.b64encode(buf.getvalue()).decode()
        plt.close()
    
    return plots

def generate_recommendations(zombies, total_waste, waste_percentage, forecast_savings):
    """Generate actionable recommendations"""
    recommendations = []
    
    # 1. Severity assessment
    if waste_percentage > 10:
        severity = "CRITICAL"
        priority = "high"
        icon = "bi-exclamation-triangle"
    elif waste_percentage > 5:
        severity = "HIGH"
        priority = "high"
        icon = "bi-exclamation-circle"
    else:
        severity = "MODERATE"
        priority = "medium"
        icon = "bi-info-circle"
    
    recommendations.append({
        'priority': priority,
        'icon': icon,
        'title': f'{severity}: Waste Level Detected',
        'description': f'{waste_percentage:.1f}% of total spend is potentially wasteful.',
        'action': 'Immediate review recommended' if priority == 'high' else 'Schedule review this week'
    })
    
    # 2. Top service recommendation
    if len(zombies) > 0 and 'ServiceCategory' in zombies.columns:
        service_waste = zombies.groupby('ServiceCategory')['EffectiveCost'].sum()
        if len(service_waste) > 0:
            top_service = service_waste.idxmax()
            top_waste = service_waste.max()
            
            recommendations.append({
                'priority': 'high',
                'icon': 'bi-funnel',
                'title': f'Focus Area: {top_service}',
                'description': f'Accounts for ${top_waste:,.2f} of total waste.',
                'action': f'Start optimization with {top_service} resources'
            })
    
    # 3. Savings opportunity
    if forecast_savings > 0:
        monthly_savings = forecast_savings * 30/7
        
        recommendations.append({
            'priority': 'high',
            'icon': 'bi-cash-coin',
            'title': 'Significant Savings Potential',
            'description': f'${forecast_savings:,.0f} in 7 days (${monthly_savings:,.0f} monthly).',
            'action': 'Implement recommendations within 48 hours'
        })
    
    # 4. Confidence-based recommendation
    if len(zombies) > 0 and 'confidence' in zombies.columns:
        high_conf = (zombies['confidence'] == 'High').sum()
        if high_conf > 0:
            recommendations.append({
                'priority': 'medium',
                'icon': 'bi-shield-check',
                'title': 'High Confidence Detections',
                'description': f'{high_conf} resources with high confidence of being wasteful.',
                'action': 'Review high confidence items first'
            })
    
    return recommendations

# ==========================================================
# FLASK ROUTES
# ==========================================================

@app.route('/')
def home():
    # Landing page (FinOps monograph style)
    return render_template('finOps.html')


@app.route('/upload', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('Please select a file', 'danger')
            return redirect(request.url)
        
        if not file.filename.endswith('.csv'):
            flash('Only CSV files are supported', 'danger')
            return redirect(request.url)
        
        # Save file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{file.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        try:
            # 1. Load and preprocess
            df = load_and_prep_data(filepath)
            
            if len(df) < 10:
                flash('Insufficient data. Need at least 10 records with positive costs.', 'warning')
                return redirect(request.url)
            
            # 2. Detect zombies
            df, zombies, z_model, z_scaler, confidence_summary = detect_zombies(df)
            total_waste = zombies['EffectiveCost'].sum() if len(zombies) > 0 else 0
            zombie_count = len(zombies)
            total_spend = df['EffectiveCost'].sum()
            waste_percentage = (total_waste / total_spend * 100) if total_spend > 0 else 0
            
            # 3. Forecast
            daily_costs, forecast, forecast_lower, forecast_upper, f_model, f_scaler = train_and_forecast(df)
            
            # 4. Generate plots
            plots = generate_plots(daily_costs, forecast, forecast_lower, forecast_upper, 
                                 total_waste, zombies, confidence_summary)
            
            # 5. Calculate metrics
            period_days = len(daily_costs)
            forecast_bau = forecast.sum()
            daily_waste_avg = total_waste / period_days if period_days > 0 else 0
            forecast_opt = np.maximum(forecast - daily_waste_avg, 0).sum()
            potential_savings = forecast_bau - forecast_opt
            savings_ratio = (potential_savings / forecast_bau * 100) if forecast_bau > 0 else 0
            avg_daily_cost = daily_costs.mean() if period_days > 0 else 0
            
            # 6. Generate recommendations
            recommendations = generate_recommendations(zombies, total_waste, waste_percentage, potential_savings)
            
            # 7. Prepare zombies preview
            if len(zombies) > 0:
                preview_cols = ['UsageDate', 'ServiceCategory', 'EffectiveCost']
                if 'confidence' in zombies.columns:
                    preview_cols.append('confidence')
                
                zombies_preview = zombies[preview_cols].head(10).copy()
                zombies_preview['EffectiveCost'] = zombies_preview['EffectiveCost'].apply(lambda x: f"${x:,.2f}")
                zombies_html = zombies_preview.to_html(
                    classes='table table-striped table-hover align-middle',
                    index=False,
                    escape=False
                )
            else:
                zombies_html = """
                <div class="alert alert-success text-center">
                    <i class="bi bi-check-circle me-2"></i>
                    No zombie resources detected! Your cloud spend appears to be efficient.
                </div>
                """
            
            # 8. Waste distribution
            if len(zombies) > 0 and 'ServiceCategory' in zombies.columns:
                waste_dist = zombies.groupby('ServiceCategory')['EffectiveCost'].sum().nlargest(5)
                if len(waste_dist) > 0:
                    waste_dist_html = waste_dist.to_frame().to_html(
                        classes='table table-sm table-hover', 
                        float_format='${:,.2f}'.format,
                        header=False
                    )
                else:
                    waste_dist_html = "<p class='text-muted'>No category data available</p>"
            else:
                waste_dist_html = "<p class='text-muted'>No category data available</p>"
            
            # 9. Prepare results
            results = {
                'total_spend': f"${total_spend:,.2f}",
                'zombie_waste': f"${total_waste:,.2f}",
                'zombie_count': f"{zombie_count:,}",
                'forecast_bau': f"${forecast_bau:,.2f}",
                'forecast_opt': f"${forecast_opt:,.2f}",
                'savings': f"${potential_savings:,.2f}",
                'zombie_pct_of_total': f"{waste_percentage:.1f}%",
                'savings_pct_vs_bau': f"{savings_ratio:.1f}%",
                'avg_daily_cost': f"${avg_daily_cost:,.2f}",
                'avg_daily_zombie': f"${daily_waste_avg:,.2f}",
                'period_days': period_days,
                'total_records': len(df),
                'insight_headline': "AI-Powered Cloud Waste Analysis Complete",
                'insight_detail': [
                    f"Analyzed {len(df):,} records spanning {period_days} days",
                    f"Detected {zombie_count:,} potential zombie resources",
                    f"Identified ${potential_savings:,.0f} in 7-day savings opportunity"
                ],
                'plots': plots,
                'recommendations': recommendations,
                'waste_distribution': waste_dist_html,
                'confidence_summary': confidence_summary,
                'zombies_preview': zombies_html,
                'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return render_template('dashboard.html', results=results)
            
        except Exception as e:
            flash(f'Analysis failed: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('index.html')

@app.route('/sample')
def sample_data():
    """Provide sample data format"""
    sample_csv = """UsageDate,ServiceCategory,EffectiveCost,ConsumedQuantity
2024-01-01,Compute,125.50,100
2024-01-01,Storage,45.25,50
2024-01-02,Compute,130.75,105
2024-01-02,Storage,46.80,52
2024-01-03,Compute,28.00,5
2024-01-03,Storage,48.10,55
2024-01-04,Database,85.30,20
2024-01-04,Network,12.40,15"""
    
    from flask import Response
    return Response(
        sample_csv,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=sample_finops_data.csv"}
    )

if __name__ == '__main__':
    print("🚀 FinOps Analyzer is running!")
    print("📊 Open http://localhost:5000 in your browser")
    print("📈 Upload your cloud billing CSV to get started")
    app.run(debug=True, port=5000, host='0.0.0.0')