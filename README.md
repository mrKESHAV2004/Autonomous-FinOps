
# ☁️ Autonomous-FinOps
### AI-Powered Cloud Cost Optimization & Zombie Infrastructure Detection

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![TensorFlow](https://img.shields.io/badge/TensorFlow-Keras-orange?style=for-the-badge&logo=tensorflow)
![Flask](https://img.shields.io/badge/Framework-Flask-lightgrey?style=for-the-badge&logo=flask)
![Status](https://img.shields.io/badge/Status-Version%204.0-success?style=for-the-badge)

> **"Bridging the gap between DevOps agility and Financial accountability."**

---

## 📖 Executive Summary

**Autonomous-FinOps** is an intelligent financial operations engine designed to tackle the growing complexity of cloud cost management. Unlike static rule-based tools, this system uses **unsupervised machine learning** and **deep learning** to learn the unique behavioral patterns of your cloud environment.

It autonomously identifies **"Zombie Resources"**—infrastructure that is provisioned and billed but unused—and provides rigorous, actionable cost forecasts.
Autonomous-FinOps is an intelligent, automated financial operations engine designed to tackle the growing complexity of cloud cost management. As cloud environments scale, manual tracking of "zombie" resources—assets that are provisioned and billed but unused or underutilized—becomes practically impossible. This project aims to bridge the gap between DevOps and Finance by deploying autonomous AI agents that continuously monitor billing data, identify waste with high precision, and forecast future spending trends.

The motivation behind this project is to move beyond static dashboards and rule-based alerts. Instead, Autonomous-FinOps employs unsupervised learning and deep learning to adaptively learn the "normal" behavior of a cloud environment, flagging anomalies (potential waste) that static rules might miss, while providing rigorous forecasting to help teams stay within budget.

---


### 🧠 The Core Agents

| Agent | Icon | Function & Technology |
| --- | --- | --- |
| **Silver Layer** | 💿 | **Ingestion & Normalization:** Standardizes heterogeneous billing data (FOCUS-compliant), handling schema validation and separating effective cost from credits. |
| **Zombie Hunter** | 🧟 | **Anomaly Detection:** Uses an **Ensemble of Isolation Forests** (Conservative, Balanced, Aggressive) to detect resources with high cost but low usage deviations. |
| **SpotHedge** | 📈 | **Predictive Forecasting:** A multi-layer **LSTM Neural Network** that predicts future spend with 95% confidence intervals, accounting for seasonality and usage spikes. |
| **Governance** | 🛡️ | **Confidence Scoring:** A safety layer that assigns High/Medium/Low confidence probabilities to detected waste, preventing false positives from triggering actions. |

---

## 🚀 Key Features

### 1. Zombie Infrastructure Detection

Identifies idle EC2 instances, unattached EBS volumes, and unused Load Balancers that standard tools miss.

* **Method:** Analyzes the multi-dimensional relationship between `Cost`, `Usage`, and `ServiceFrequency`.
* **Result:** Prioritized list of waste with **High/Medium/Low confidence scores**.

### 2. Deep Learning Forecasting

Predicts cloud spend patterns using advanced time-series analysis.

* **Method:** Long Short-Term Memory (LSTM) networks with `Huber Loss` for outlier robustness.
* **Insight:** Provides two forecasts: **"Business As Usual" (BAU)** vs. **"Optimized"** (post-waste removal).

### 3. Interactive Dark-Mode Dashboard

A professional, responsive UI built with Flask and Bootstrap 5.

* **Visuals:** "Bend the Curve" projections, waste distribution charts, and actionable recommendation cards.

---


### 🔬 Version Details

* **Version 1 (The POC):** Established the pipeline using a single `IsolationForest`, basic `StandardScaler`, and a `CircuitBreaker` class for governance.
* **Version 2 (Feature Engineering):** Introduced `RobustScaler` to handle extreme billing outliers and added `CostPerUnit` metrics.
* **Version 3 (Ensemble):** Implemented a voting mechanism between 3 distinct anomaly detectors to reduce false positives and added cyclical date encoding (`DayOfWeekSin`).
* **Version 4 (Current):** Maximized interpretability with `ServiceFrequency` encoding (identifying rare, high-cost services), non-linear polynomial features like `CostSquared`, and asymmetric confidence intervals.

---

## 🛠️ Installation & Usage

### Prerequisites

* Python 3.8+
* TensorFlow / Keras
* Scikit-Learn
* Flask & Pandas

### Quick Start

1. **Clone the repository**
```
git clone https://github.com/yourusername/autonomous-finops.git
cd autonomous-finops

```


2. **Install Dependencies**
```
pip install -r requirements.txt

```


3. **Run the Application (Version 4)**
```
cd version-4
python interface.py

```


4. **Access the Dashboard**
Open your browser and navigate to `http://localhost:5000`. Upload your cloud billing CSV (FOCUS format) to start the analysis.

---

## 📊 Sample Data

The repository includes sample datasets for testing:

* `focus_sample.csv`: Standard billing data.
* `focus_sample_10000.csv`: Larger dataset for stress testing models.

---

<div align="center">
<sub>Powered by AI • Developed for Cloud Efficiency • Open Source</sub>
</div>

```

```
