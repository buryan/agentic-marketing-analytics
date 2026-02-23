#!/usr/bin/env python3
"""Display Channel Halo Effect Analysis — Dashboard Generator"""

import pandas as pd
import numpy as np
import json
import warnings
from pathlib import Path
from datetime import datetime
from scipy import stats
warnings.filterwarnings('ignore')

# ── Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
INPUT  = PROJECT_ROOT / "data" / "input"
OUTPUT = PROJECT_ROOT / "output"
DATA_FILE = INPUT / "HALO - data - Data per MKG channel.csv"
HTML_OUT  = OUTPUT / "display-halo-report.html"

# ── Constants ──────────────────────────────────────────────────────────
DISPLAY_CHANNEL = 'display'
EXCLUDE_CHANNELS = {'Total', 'N/A', 'display'}
MAX_LAG_DAYS = 14
KEY_METRICS = ['Activations', 'NOR', 'M1+VFM', 'VFM', 'GR']
DISPLAY_DRIVERS = ['Spend', 'Impressions']
MIN_CHANNEL_DAYS = 180
CORRELATION_SIGNIFICANCE = 0.05

# ── 1. Load Data ───────────────────────────────────────────────────────
print("Loading data...")

def parse_space_num(val):
    """Parse numbers with space thousands separator: '2 822 108' -> 2822108."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    if s == '' or s.startswith('#'):
        return np.nan
    cleaned = s.replace('\u00a0', '').replace(' ', '')
    try:
        return float(cleaned)
    except ValueError:
        return np.nan

df = pd.read_csv(DATA_FILE)
df.rename(columns={'Dimension 1': 'channel', 'Dimension 2': 'date'}, inplace=True)

# Drop Total summary row and NaN channels
df = df[df['channel'] != 'Total'].copy()
df = df[df['date'] != 'Total'].copy()
df['channel'] = df['channel'].fillna('N/A')

# Parse date
df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
df = df.dropna(subset=['date']).copy()

# Parse metric columns
metric_cols = [c for c in df.columns if c not in ('channel', 'date')]
for col in metric_cols:
    df[col] = df[col].apply(parse_space_num)

# ── 2. Data Validation ────────────────────────────────────────────────
print("\n=== DATA VALIDATION ===")
validation = {}

date_min, date_max = df['date'].min(), df['date'].max()
total_days = (date_max - date_min).days + 1
v1 = f"Range: {date_min.strftime('%Y-%m-%d')} to {date_max.strftime('%Y-%m-%d')} ({total_days} days)"
validation['v1_dates'] = v1; print(f"V1: {v1}")

channels_all = sorted(df['channel'].unique())
channel_counts = df.groupby('channel')['date'].count()
v2 = f"Channels: {len(channels_all)}. Full coverage ({channel_counts.max()}d): {sum(channel_counts == channel_counts.max())}. Partial: {sum(channel_counts < channel_counts.max())}"
validation['v2_channels'] = v2; print(f"V2: {v2}")

display_df = df[df['channel'] == DISPLAY_CHANNEL]
v3 = f"Display rows: {len(display_df)}. Spend range: {display_df['Spend'].min():,.0f} - {display_df['Spend'].max():,.0f}, mean: {display_df['Spend'].mean():,.0f}"
validation['v3_display'] = v3; print(f"V3: {v3}")

target_channels = sorted([c for c in channels_all
                           if c not in EXCLUDE_CHANNELS
                           and channel_counts.get(c, 0) >= MIN_CHANNEL_DAYS])
excluded = [c for c in channels_all if c not in target_channels and c not in EXCLUDE_CHANNELS]
v4 = f"Included: {len(target_channels)} channels. Excluded (< {MIN_CHANNEL_DAYS}d): {excluded if excluded else 'none'}"
validation['v4_included'] = v4; print(f"V4: {v4}")

# ── 3. Build Analysis DataFrames ──────────────────────────────────────
print("\nBuilding analysis frames...")

display_data = df[df['channel'] == DISPLAY_CHANNEL][['date'] + metric_cols].set_index('date').sort_index()
display_spend = display_data['Spend']
display_impressions = display_data['Impressions']

channel_dfs = {}
for ch in target_channels:
    ch_df = df[df['channel'] == ch][['date'] + metric_cols].set_index('date').sort_index()
    channel_dfs[ch] = ch_df

# ── 4. Method 1: Lagged Cross-Correlation ─────────────────────────────
print("Computing lagged correlations...")

def compute_lagged_correlations(driver, target, max_lag=MAX_LAG_DAYS):
    """Pearson correlation at lags 0..max_lag. Lag N = driver day T vs target day T+N."""
    results = []
    common = driver.dropna().index.intersection(target.dropna().index)
    if len(common) < 30:
        return results
    for lag in range(0, max_lag + 1):
        shifted = target.shift(-lag)
        valid = driver.dropna().index.intersection(shifted.dropna().index)
        if len(valid) < 30:
            continue
        d = driver.loc[valid].values
        t = shifted.loc[valid].values
        mask = ~(np.isnan(d) | np.isnan(t))
        d, t = d[mask], t[mask]
        if len(d) < 30:
            continue
        corr, p_val = stats.pearsonr(d, t)
        results.append({'lag': lag, 'correlation': float(corr), 'p_value': float(p_val),
                        'n_obs': int(len(d)), 'significant': bool(p_val < CORRELATION_SIGNIFICANCE)})
    return results

correlation_results = {}
for driver_name in DISPLAY_DRIVERS:
    driver = display_data[driver_name]
    for ch in target_channels:
        for metric in KEY_METRICS:
            if metric not in channel_dfs[ch].columns:
                continue
            target = channel_dfs[ch][metric]
            key = f"{driver_name}|{ch}|{metric}"
            corrs = compute_lagged_correlations(driver, target)
            if corrs:
                correlation_results[key] = corrs

def find_best_lag(corr_list):
    sig = [c for c in corr_list if c['significant']]
    if not sig:
        return None
    return max(sig, key=lambda x: abs(x['correlation']))

optimal_lags = {}
for key, corrs in correlation_results.items():
    best = find_best_lag(corrs)
    if best:
        optimal_lags[key] = best

def build_heatmap(driver_name, metric_name):
    rows = []
    for ch in target_channels:
        key = f"{driver_name}|{ch}|{metric_name}"
        if key in correlation_results:
            lag_vals = {c['lag']: c['correlation'] for c in correlation_results[key]}
            row = {'channel': ch}
            for lag in range(MAX_LAG_DAYS + 1):
                row[f'lag_{lag}'] = lag_vals.get(lag, None)
            # Mark best lag
            bkey = f"{driver_name}|{ch}|{metric_name}"
            if bkey in optimal_lags:
                row['best_lag'] = optimal_lags[bkey]['lag']
                row['best_corr'] = optimal_lags[bkey]['correlation']
            else:
                row['best_lag'] = None
                row['best_corr'] = None
            rows.append(row)
    return rows

heatmaps = {
    'spend_nor': build_heatmap('Spend', 'NOR'),
    'spend_activations': build_heatmap('Spend', 'Activations'),
    'spend_m1vfm': build_heatmap('Spend', 'M1+VFM'),
    'impressions_nor': build_heatmap('Impressions', 'NOR'),
}

# ── 5. Method 2: High vs Low Display Spend Period Comparison ──────────
print("Computing period comparison...")

def compute_period_comparison(display_spend_series, channel_dfs, metric):
    weekly_spend = display_spend_series.resample('W-MON').sum()
    t33 = weekly_spend.quantile(0.33)
    t67 = weekly_spend.quantile(0.67)
    high_weeks = set(weekly_spend[weekly_spend >= t67].index)
    low_weeks = set(weekly_spend[weekly_spend <= t33].index)

    results = []
    for ch in target_channels:
        if metric not in channel_dfs[ch].columns:
            continue
        ch_weekly = channel_dfs[ch][metric].resample('W-MON').sum()
        high_vals = ch_weekly.loc[ch_weekly.index.isin(high_weeks)].dropna()
        low_vals = ch_weekly.loc[ch_weekly.index.isin(low_weeks)].dropna()
        if len(high_vals) < 5 or len(low_vals) < 5:
            continue
        high_mean = float(high_vals.mean())
        low_mean = float(low_vals.mean())
        uplift = ((high_mean - low_mean) / low_mean * 100) if low_mean != 0 else None
        t_stat, p_val = stats.ttest_ind(high_vals, low_vals, equal_var=False)
        results.append({
            'channel': ch, 'high_display_mean': high_mean, 'low_display_mean': low_mean,
            'uplift_pct': uplift, 'p_value': float(p_val),
            'significant': bool(p_val < CORRELATION_SIGNIFICANCE),
            'n_high': int(len(high_vals)), 'n_low': int(len(low_vals))
        })
    return sorted(results, key=lambda x: abs(x.get('uplift_pct') or 0), reverse=True)

period_results = {}
for metric in KEY_METRICS:
    period_results[metric] = compute_period_comparison(display_spend, channel_dfs, metric)

# ── 6. Method 3: Granger Causality Test ───────────────────────────────
print("Computing Granger causality...")

def granger_test(driver_series, target_series, max_lag=7):
    combined = pd.DataFrame({'driver': driver_series, 'target': target_series}).dropna()
    if len(combined) < 60:
        return None
    target = combined['target'].values
    driver = combined['driver'].values
    n = len(target)
    best = None
    for lag in range(1, max_lag + 1):
        if n - lag < 30:
            continue
        y = target[lag:]
        X_r = np.column_stack([np.ones(len(y))] + [target[lag-i-1:n-i-1] for i in range(lag)])
        X_u = np.column_stack([X_r] + [driver[lag-i-1:n-i-1].reshape(-1, 1) for i in range(lag)])
        try:
            beta_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
            beta_u = np.linalg.lstsq(X_u, y, rcond=None)[0]
            ssr_r = np.sum((y - X_r @ beta_r) ** 2)
            ssr_u = np.sum((y - X_u @ beta_u) ** 2)
            df1 = lag
            df2 = len(y) - X_u.shape[1]
            if ssr_u == 0 or df2 <= 0:
                continue
            f_stat = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
            p_value = float(1 - stats.f.cdf(f_stat, df1, df2))
            if best is None or p_value < best['p_value']:
                best = {'lag': int(lag), 'f_stat': float(f_stat), 'p_value': p_value,
                        'significant': bool(p_value < CORRELATION_SIGNIFICANCE)}
        except np.linalg.LinAlgError:
            continue
    return best

granger_results = {}
for ch in target_channels:
    for metric in KEY_METRICS:
        if metric not in channel_dfs[ch].columns:
            continue
        result = granger_test(display_spend, channel_dfs[ch][metric])
        if result:
            granger_results[f"{ch}|{metric}"] = result

# ── 7. Method 4: Incremental Contribution Estimate ────────────────────
print("Computing incremental contribution...")

non_display = df[~df['channel'].isin(EXCLUDE_CHANNELS)]
total_other = non_display.groupby('date')[KEY_METRICS].sum()

def estimate_contribution(display_spend, total_metric):
    combined = pd.DataFrame({
        'display_spend': display_spend,
        'display_lag3': display_spend.shift(3),
        'display_lag7': display_spend.shift(7),
        'total': total_metric
    }).dropna()
    if len(combined) < 90:
        return None
    combined['dow'] = combined.index.dayofweek
    dow_dum = pd.get_dummies(combined['dow'], prefix='dow', drop_first=True).astype(float)
    combined['month'] = combined.index.month
    mon_dum = pd.get_dummies(combined['month'], prefix='mon', drop_first=True).astype(float)
    X = pd.concat([combined[['display_spend', 'display_lag3', 'display_lag7']], dow_dum, mon_dum], axis=1)
    X_c = np.column_stack([np.ones(len(X)), X.values])
    y = combined['total'].values
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_pred = X_c @ beta
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = float(1 - ss_res / ss_tot) if ss_tot != 0 else 0
        coeff = float(beta[1])
        avg_spend = float(combined['display_spend'].mean())
        avg_total = float(combined['total'].mean())
        contrib = float(coeff * avg_spend / avg_total * 100) if avg_total != 0 else 0
        return {'coefficient': coeff, 'r_squared': r2, 'avg_display_spend': avg_spend,
                'avg_total': avg_total, 'contribution_pct': contrib, 'n_obs': int(len(combined))}
    except np.linalg.LinAlgError:
        return None

incremental = {}
for metric in KEY_METRICS:
    if metric in total_other.columns:
        result = estimate_contribution(display_spend, total_other[metric])
        if result:
            incremental[metric] = result

# ── 8. Method 5: YoY Display Change Detection ─────────────────────────
print("Computing YoY analysis...")

def yoy_analysis(display_spend, channel_dfs, metric):
    display_monthly = display_spend.resample('ME').sum()
    results = []
    for date in display_monthly.index:
        yoy_date = date - pd.DateOffset(years=1)
        prior = display_monthly[display_monthly.index.to_period('M') == yoy_date.to_period('M')]
        if len(prior) == 0 or prior.iloc[0] == 0:
            continue
        current_spend = float(display_monthly.loc[date])
        prior_spend = float(prior.iloc[0])
        display_yoy = (current_spend - prior_spend) / prior_spend * 100
        if abs(display_yoy) < 20:
            continue
        row = {'month': date.strftime('%Y-%m'), 'display_yoy_pct': round(display_yoy, 1)}
        for ch in target_channels:
            if metric not in channel_dfs[ch].columns:
                continue
            ch_m = channel_dfs[ch][metric].resample('ME').sum()
            ch_cur = ch_m[ch_m.index.to_period('M') == date.to_period('M')]
            ch_pri = ch_m[ch_m.index.to_period('M') == yoy_date.to_period('M')]
            if len(ch_cur) > 0 and len(ch_pri) > 0 and ch_pri.iloc[0] != 0:
                row[ch] = round((float(ch_cur.iloc[0]) - float(ch_pri.iloc[0])) / float(ch_pri.iloc[0]) * 100, 1)
        results.append(row)
    return results

yoy_results = {}
for metric in ['NOR', 'Activations', 'M1+VFM']:
    yoy_results[metric] = yoy_analysis(display_spend, channel_dfs, metric)

# ── 9. Trend Overlay Data ─────────────────────────────────────────────
print("Preparing trend data...")

def prepare_trends(driver, channel_dfs, metric, window=28):
    trends = {}
    d_roll = driver.rolling(window=window, min_periods=14).mean()
    d_base = d_roll.dropna().iloc[0] if len(d_roll.dropna()) > 0 else None
    if d_base and d_base != 0:
        trends['display'] = (d_roll / d_base * 100).dropna()
    focus = ['sem', 'seo', 'direct', 'affiliate', 'email']
    for ch in focus:
        if ch not in channel_dfs or metric not in channel_dfs[ch].columns:
            continue
        s = channel_dfs[ch][metric].rolling(window=window, min_periods=14).mean()
        base = s.dropna().iloc[0] if len(s.dropna()) > 0 else None
        if base and base != 0:
            trends[ch] = (s / base * 100).dropna()
    return trends

trend_spend_nor = prepare_trends(display_spend, channel_dfs, 'NOR')
trend_spend_act = prepare_trends(display_spend, channel_dfs, 'Activations')
trend_impr_nor = prepare_trends(display_impressions, channel_dfs, 'NOR')

def serialize_trends(trend_dict):
    if not trend_dict:
        return {'dates': [], 'series': {}}
    all_dates = sorted(set().union(*[set(s.index) for s in trend_dict.values()]))
    return {
        'dates': [d.strftime('%Y-%m-%d') for d in all_dates],
        'series': {name: [float(s.get(d)) if d in s.index and not np.isnan(s.get(d, np.nan)) else None
                          for d in all_dates]
                   for name, s in trend_dict.items()}
    }

# ── 10. Executive Summary ─────────────────────────────────────────────
print("Building executive summary...")

channel_corr_scores = {}
for key, best in optimal_lags.items():
    ch = key.split('|')[1]
    if ch not in channel_corr_scores:
        channel_corr_scores[ch] = []
    channel_corr_scores[ch].append(abs(best['correlation']))
avg_scores = {ch: float(np.mean(s)) for ch, s in channel_corr_scores.items()}
top_halo = sorted(avg_scores.items(), key=lambda x: x[1], reverse=True)[:5]

all_opt_lags = [v['lag'] for v in optimal_lags.values()]
median_lag = int(np.median(all_opt_lags)) if all_opt_lags else None
lag_range = (min(all_opt_lags), max(all_opt_lags)) if all_opt_lags else None

granger_sig = sum(1 for r in granger_results.values() if r['significant'])

exec_summary = {
    'top_halo': top_halo,
    'median_lag': median_lag,
    'lag_range': lag_range,
    'granger_sig': granger_sig,
    'granger_total': len(granger_results),
    'incr_nor_pct': incremental.get('NOR', {}).get('contribution_pct'),
    'incr_m1vfm_pct': incremental.get('M1+VFM', {}).get('contribution_pct'),
    'display_total_spend': float(display_spend.sum()),
    'display_avg_spend': float(display_spend.mean()),
    'display_total_impr': float(display_impressions.sum()),
    'display_avg_impr': float(display_impressions.mean()),
    'n_channels': len(target_channels),
    'n_days': int(total_days),
}

# Period comparison uplift counts
for metric in KEY_METRICS:
    sig_up = [r for r in period_results.get(metric, []) if r['significant'] and r.get('uplift_pct') and r['uplift_pct'] > 0]
    exec_summary[f'period_sig_{metric}'] = len(sig_up)

# ── 11. Serialize for HTML ────────────────────────────────────────────
print("Serializing for HTML...")

def safe_val(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, pd.Timestamp):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v

data_payload = {
    'exec': exec_summary,
    'heatmaps': heatmaps,
    'period': {m: [{k: safe_val(v) for k, v in r.items()} for r in rs]
               for m, rs in period_results.items()},
    'granger': {k: {kk: safe_val(vv) for kk, vv in v.items()} for k, v in granger_results.items()},
    'incremental': {k: {kk: safe_val(vv) for kk, vv in v.items()} for k, v in incremental.items()},
    'optimal_lags': {k: {kk: safe_val(vv) for kk, vv in v.items()} for k, v in optimal_lags.items()},
    'trends': {
        'spend_nor': serialize_trends(trend_spend_nor),
        'spend_act': serialize_trends(trend_spend_act),
        'impr_nor': serialize_trends(trend_impr_nor),
    },
    'yoy': yoy_results,
    'channels': target_channels,
}

val_list = [{"check": k, "result": v} for k, v in validation.items()]

data_json = json.dumps(data_payload, default=str)
val_json = json.dumps(val_list, default=str)

# Date helpers
def fmt_d(ts):
    return ts.strftime('%b %-d, %Y')

subtitle = f"Daily channel data | {fmt_d(date_min)} - {fmt_d(date_max)} | {len(target_channels)} channels analyzed"

# ── 12. Generate HTML ─────────────────────────────────────────────────
print("Generating HTML...")

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Display Channel Halo Effect Analysis</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
:root {{
  --bg: #0b0f19; --card: #111827; --border: #1e293b;
  --blue: #3b82f6; --green: #10b981; --red: #ef4444; --orange: #f59e0b;
  --purple: #a78bfa; --cyan: #06b6d4;
  --text: #e2e8f0; --muted: #94a3b8; --white: #fff;
}}
body {{ font-family: 'Space Grotesk', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
.header {{ padding: 20px 32px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 1.5rem; font-weight: 700; }}
.header .subtitle {{ color: var(--muted); font-size: 0.85rem; }}
.nav-bar {{ display: flex; gap: 8px; padding: 16px 32px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }}
.tab-btn {{ padding: 6px 14px; border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.82rem; transition: all 0.2s; }}
.tab-btn:hover {{ color: var(--text); }}
.tab-btn.active {{ background: var(--card); color: var(--white); border-color: var(--border); }}
.content {{ padding: 24px 32px; max-width: 1600px; margin: 0 auto; }}
.grid {{ display: grid; gap: 16px; }}
.g2 {{ grid-template-columns: repeat(2, 1fr); }}
.g3 {{ grid-template-columns: repeat(3, 1fr); }}
.g4 {{ grid-template-columns: repeat(4, 1fr); }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }}
.card h3 {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 8px; font-weight: 500; }}
.card .big {{ font-size: 1.8rem; font-weight: 700; font-family: 'SF Mono', 'Fira Code', monospace; }}
.card .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
.callout {{ padding: 16px 20px; border-radius: 8px; margin: 16px 0; border-left: 4px solid; }}
.callout.blue {{ background: rgba(59,130,246,0.1); border-color: var(--blue); }}
.callout.green {{ background: rgba(16,185,129,0.1); border-color: var(--green); }}
.callout.orange {{ background: rgba(245,158,11,0.1); border-color: var(--orange); }}
.callout.red {{ background: rgba(239,68,68,0.1); border-color: var(--red); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; font-family: 'SF Mono', 'Fira Code', monospace; }}
th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--muted);
  font-weight: 500; position: sticky; top: 0; background: var(--card); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
tr:hover td {{ background: rgba(255,255,255,0.02); }}
.table-wrap {{ max-height: 500px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border); }}
.pos {{ color: var(--green); }} .neg {{ color: var(--red); }} .warn {{ color: var(--orange); }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
.badge-green {{ background: rgba(16,185,129,0.15); color: var(--green); }}
.badge-orange {{ background: rgba(245,158,11,0.15); color: var(--orange); }}
.badge-red {{ background: rgba(239,68,68,0.15); color: var(--red); }}
.badge-blue {{ background: rgba(59,130,246,0.15); color: var(--blue); }}
.badge-purple {{ background: rgba(167,139,250,0.15); color: var(--purple); }}
.chart-container {{ position: relative; height: 350px; background: var(--card); border-radius: 10px; border: 1px solid var(--border); padding: 16px; }}
.section-title {{ font-size: 1.1rem; font-weight: 600; margin: 24px 0 12px; }}
.section-title:first-child {{ margin-top: 0; }}
.filter-bar {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
.filter-btn {{ padding: 4px 12px; border-radius: 4px; border: 1px solid var(--border); background: var(--card);
  color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.78rem; transition: all 0.2s; }}
.filter-btn.active {{ background: var(--blue); color: var(--white); border-color: var(--blue); }}
.methodology-box {{ background: rgba(59,130,246,0.05); border: 1px solid rgba(59,130,246,0.2); border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
.methodology-box h3 {{ color: var(--blue); margin-bottom: 8px; }}
.methodology-box p {{ color: var(--muted); font-size: 0.85rem; line-height: 1.6; }}
.hm-cell {{ display: inline-block; width: 100%; text-align: center; padding: 3px 2px; border-radius: 3px; font-size: 0.72rem; }}
@media (max-width: 1200px) {{ .g4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 768px) {{ .g2, .g3, .g4 {{ grid-template-columns: 1fr; }} .content {{ padding: 16px; }} }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Display Channel Halo Effect Analysis</h1>
    <div class="subtitle">{subtitle}</div>
  </div>
  <div class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>

<div class="nav-bar">
  <button class="tab-btn active" onclick="setTab(0)">Exec Summary</button>
  <button class="tab-btn" onclick="setTab(1)">Correlation &amp; Lag</button>
  <button class="tab-btn" onclick="setTab(2)">Period Comparison</button>
  <button class="tab-btn" onclick="setTab(3)">Channel Detail</button>
  <button class="tab-btn" onclick="setTab(4)">Trend Overlays</button>
  <button class="tab-btn" onclick="setTab(5)">Methodology</button>
</div>

<div class="content" id="mainContent"></div>

<script>
const D = {data_json};
const VAL = {val_json};
let currentTab = 0;
let chartInstances = [];

function destroyCharts() {{
  chartInstances.forEach(c => {{ try {{ c.destroy(); }} catch(e) {{}} }});
  chartInstances = [];
}}

function fmt(v, type) {{
  if (v === null || v === undefined || isNaN(v)) return '—';
  if (type === '$') return (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {{maximumFractionDigits:0}});
  if (type === 'pct') return (v > 0 ? '+' : '') + v.toFixed(1) + '%';
  if (type === 'n') return Math.round(v).toLocaleString();
  if (type === 'r') return v.toFixed(3);
  if (type === 'r2') return v.toFixed(2);
  if (type === 'p') return v < 0.001 ? '<0.001' : v.toFixed(3);
  return String(v);
}}

function corrClass(v) {{
  if (v === null || v === undefined || isNaN(v)) return '';
  if (v > 0.3) return 'pos';
  if (v < -0.3) return 'neg';
  return '';
}}

function chartOpts(title) {{
  return {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      title: {{ display: !!title, text: title || '', color: '#e2e8f0', font: {{ family: 'Space Grotesk', size: 14 }} }},
      legend: {{ labels: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 11 }} }} }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }}, maxTicksLimit: 20 }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }}
    }}
  }};
}}

function setTab(t) {{
  currentTab = t;
  document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === t));
  render();
}}

function render() {{
  destroyCharts();
  const el = document.getElementById('mainContent');
  const tabs = [renderExec, renderCorrelation, renderPeriod, renderChannelDetail, renderTrends, renderMethodology];
  el.innerHTML = tabs[currentTab]();
  if (currentTab === 1) initCorrelationCharts();
  if (currentTab === 2) initPeriodCharts();
  if (currentTab === 4) initTrendCharts();
}}

// ── Tab 0: Exec Summary ──
function renderExec() {{
  const e = D.exec;
  const topCh = e.top_halo || [];

  let verdict = '';
  const sigCount = e.granger_sig || 0;
  const total = e.granger_total || 0;
  if (sigCount > total * 0.4) {{
    verdict = `<div class="callout green"><strong>Strong halo evidence.</strong> Display spend Granger-causes ${{sigCount}} of ${{total}} channel-metric pairs tested (${{(sigCount/total*100).toFixed(0)}}%). Multiple channels show statistically significant uplift during high-Display periods.</div>`;
  }} else if (sigCount > total * 0.15) {{
    verdict = `<div class="callout orange"><strong>Moderate halo evidence.</strong> Display spend shows predictive power for ${{sigCount}} of ${{total}} pairs (${{(sigCount/total*100).toFixed(0)}}%). Some channels respond to Display activity, but the effect is not universal.</div>`;
  }} else {{
    verdict = `<div class="callout blue"><strong>Weak halo evidence.</strong> Only ${{sigCount}} of ${{total}} pairs show Granger causality (${{(sigCount/total*100).toFixed(0)}}%). Display may have limited cross-channel impact, or the effect operates through mechanisms not captured here.</div>`;
  }}

  let topTable = '<table><thead><tr><th>Rank</th><th>Channel</th><th>Avg |Correlation|</th><th>Best Metric</th></tr></thead><tbody>';
  topCh.forEach((ch, i) => {{
    topTable += `<tr><td>${{i+1}}</td><td>${{ch[0]}}</td><td class="${{ch[1] > 0.3 ? 'pos' : 'warn'}}">${{ch[1].toFixed(3)}}</td><td>—</td></tr>`;
  }});
  topTable += '</tbody></table>';

  let findings = '<ol style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">';
  if (topCh.length > 0) findings += `<li>Top halo-affected channel: <strong>${{topCh[0][0]}}</strong> (avg |r| = ${{topCh[0][1].toFixed(3)}}).</li>`;
  if (e.median_lag !== null) findings += `<li>Median optimal lag: <strong>${{e.median_lag}} days</strong> (range: ${{e.lag_range ? e.lag_range[0] + '-' + e.lag_range[1] : '—'}} days).</li>`;
  findings += `<li>Granger causality: <strong>${{sigCount}}</strong> of ${{total}} channel-metric pairs significant at p < 0.05.</li>`;
  if (e.incr_nor_pct !== null) findings += `<li>Estimated Display contribution to non-Display orders (NOR): <strong>${{e.incr_nor_pct.toFixed(1)}}%</strong>.</li>`;
  if (e.incr_m1vfm_pct !== null) findings += `<li>Estimated Display contribution to non-Display revenue (M1+VFM): <strong>${{e.incr_m1vfm_pct.toFixed(1)}}%</strong>.</li>`;
  findings += '</ol>';

  return `
    <div class="methodology-box">
      <h3>What is the Halo Effect?</h3>
      <p>The halo effect measures whether Display advertising drives incremental performance in <em>other</em> marketing channels.
      When users see Display ads, they may later convert via SEM, SEO, direct visits, or other channels — attributing the conversion away from Display
      even though Display initiated the journey. This analysis quantifies that cross-channel lift using correlation, period comparison, and Granger causality.</p>
    </div>
    <div class="grid g4">
      <div class="card"><h3>Display Total Spend</h3><div class="big">${{fmt(e.display_total_spend,'$')}}</div><div class="sub">Avg ${{fmt(e.display_avg_spend,'$')}}/day</div></div>
      <div class="card"><h3>Display Total Impressions</h3><div class="big">${{fmt(e.display_total_impr,'n')}}</div><div class="sub">Avg ${{fmt(e.display_avg_impr,'n')}}/day</div></div>
      <div class="card"><h3>Top Halo Channel</h3><div class="big">${{topCh.length > 0 ? topCh[0][0] : '—'}}</div><div class="sub">Avg |r| = ${{topCh.length > 0 ? topCh[0][1].toFixed(3) : '—'}}</div></div>
      <div class="card"><h3>Median Optimal Lag</h3><div class="big">${{e.median_lag !== null ? e.median_lag + 'd' : '—'}}</div><div class="sub">${{e.lag_range ? 'Range: ' + e.lag_range[0] + '-' + e.lag_range[1] + ' days' : ''}}</div></div>
    </div>
    ${{verdict}}
    <div class="section-title">Top 5 Halo-Affected Channels</div>
    <div class="card">${{topTable}}</div>
    <div class="section-title">Key Findings</div>
    <div class="card">${{findings}}</div>
  `;
}}

// ── Tab 1: Correlation & Lag ──
function renderCorrelation() {{
  function heatmapTable(data, title, driverLabel, metricLabel) {{
    if (!data || data.length === 0) return `<p class="sub">No data for ${{title}}</p>`;
    let h = `<div class="section-title">${{title}} (${{driverLabel}} &rarr; ${{metricLabel}})</div>`;
    h += '<div class="card table-wrap" style="overflow-x:auto;"><table><thead><tr><th>Channel</th><th>Best Lag</th><th>Best r</th>';
    for (let lag = 0; lag <= 14; lag++) h += `<th>L${{lag}}</th>`;
    h += '</tr></thead><tbody>';
    const sorted = [...data].sort((a,b) => Math.abs(b.best_corr||0) - Math.abs(a.best_corr||0));
    sorted.forEach(row => {{
      h += `<tr><td>${{row.channel}}</td>`;
      h += `<td>${{row.best_lag !== null ? row.best_lag + 'd' : '—'}}</td>`;
      h += `<td class="${{corrClass(row.best_corr)}}">${{row.best_corr !== null ? row.best_corr.toFixed(3) : '—'}}</td>`;
      for (let lag = 0; lag <= 14; lag++) {{
        const v = row['lag_' + lag];
        if (v === null || v === undefined) {{
          h += '<td style="color:var(--border)">—</td>';
        }} else {{
          const abs = Math.abs(v);
          const opacity = Math.min(abs * 2.5, 0.5) + 0.05;
          const bg = v > 0 ? `rgba(16,185,129,${{opacity}})` : `rgba(239,68,68,${{opacity}})`;
          const highlight = row.best_lag === lag ? 'border:1px solid var(--white);' : '';
          h += `<td><span class="hm-cell" style="background:${{bg}};${{highlight}}">${{v.toFixed(2)}}</span></td>`;
        }}
      }}
      h += '</tr>';
    }});
    h += '</tbody></table></div>';
    return h;
  }}

  let lagDist = '<div class="section-title">Optimal Lag Distribution</div><div class="chart-container"><canvas id="lagDistChart"></canvas></div>';

  return `
    <div class="callout blue"><strong>Reading the heatmaps:</strong> Each cell shows the Pearson correlation between Display activity on day T and the target channel metric on day T+Lag. Green = positive correlation (Display up &rarr; channel up). Red = negative. White border = optimal lag for that channel. Channels sorted by strongest correlation.</div>
    ${{heatmapTable(D.heatmaps.spend_nor, 'Display Spend vs Net Orders', 'Spend', 'NOR')}}
    ${{heatmapTable(D.heatmaps.spend_activations, 'Display Spend vs Activations', 'Spend', 'Activations')}}
    ${{heatmapTable(D.heatmaps.spend_m1vfm, 'Display Spend vs Revenue (M1+VFM)', 'Spend', 'M1+VFM')}}
    ${{heatmapTable(D.heatmaps.impressions_nor, 'Display Impressions vs Net Orders', 'Impressions', 'NOR')}}
    ${{lagDist}}
  `;
}}

function initCorrelationCharts() {{
  const lags = Object.values(D.optimal_lags).map(v => v.lag);
  if (lags.length === 0) return;
  const counts = Array(15).fill(0);
  lags.forEach(l => {{ if (l >= 0 && l <= 14) counts[l]++; }});
  const ctx = document.getElementById('lagDistChart');
  if (!ctx) return;
  const c = new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: Array.from({{length:15}}, (_,i) => 'Lag ' + i),
      datasets: [{{ label: 'Count of optimal lags', data: counts, backgroundColor: '#3b82f6', borderRadius: 4 }}]
    }},
    options: chartOpts('Distribution of Optimal Lags Across All Channel-Metric Pairs')
  }});
  chartInstances.push(c);
}}

// ── Tab 2: Period Comparison ──
function renderPeriod() {{
  const metrics = ['NOR', 'Activations', 'M1+VFM', 'VFM', 'GR'];
  let html = '<div class="callout blue"><strong>Methodology:</strong> Weeks split into terciles by Display spend. Top &frac13; = "High Display", bottom &frac13; = "Low Display". Uplift = (High - Low) / Low. Welch\\'s t-test for significance (p &lt; 0.05).</div>';

  metrics.forEach(metric => {{
    const data = D.period[metric];
    if (!data || data.length === 0) return;
    html += `<div class="section-title">Display Spend Impact on ${{metric}}</div>`;
    html += '<div class="card table-wrap"><table><thead><tr><th>Channel</th><th>High Display Mean</th><th>Low Display Mean</th><th>Uplift %</th><th>p-value</th><th>Sig?</th></tr></thead><tbody>';
    data.forEach(r => {{
      const isMoney = ['M1+VFM', 'VFM', 'GR'].includes(metric);
      const fmtType = isMoney ? '$' : 'n';
      html += `<tr><td>${{r.channel}}</td>
        <td>${{fmt(r.high_display_mean, fmtType)}}</td>
        <td>${{fmt(r.low_display_mean, fmtType)}}</td>
        <td class="${{r.uplift_pct > 0 ? 'pos' : 'neg'}}">${{fmt(r.uplift_pct, 'pct')}}</td>
        <td>${{fmt(r.p_value, 'p')}}</td>
        <td>${{r.significant ? '<span class="badge badge-green">Yes</span>' : '<span class="badge badge-red">No</span>'}}</td></tr>`;
    }});
    html += '</tbody></table></div>';
  }});

  html += '<div class="section-title">Uplift Comparison (NOR)</div><div class="chart-container"><canvas id="periodChart"></canvas></div>';
  return html;
}}

function initPeriodCharts() {{
  const data = D.period['NOR'];
  if (!data || data.length === 0) return;
  const ctx = document.getElementById('periodChart');
  if (!ctx) return;
  const sorted = [...data].sort((a,b) => (b.uplift_pct||0) - (a.uplift_pct||0));
  const labels = sorted.map(r => r.channel);
  const vals = sorted.map(r => r.uplift_pct);
  const colors = vals.map(v => v > 0 ? (v > 5 ? '#10b981' : '#f59e0b') : '#ef4444');
  const c = new Chart(ctx, {{
    type: 'bar',
    data: {{ labels, datasets: [{{ label: 'Uplift % (High vs Low Display Spend)', data: vals, backgroundColor: colors, borderRadius: 4 }}] }},
    options: {{ ...chartOpts('Channel NOR Uplift: High vs Low Display Spend Weeks'), indexAxis: 'y' }}
  }});
  chartInstances.push(c);
}}

// ── Tab 3: Channel Detail ──
function renderChannelDetail() {{
  let html = '';
  const channels = D.channels;

  // Build per-channel summary
  channels.forEach(ch => {{
    // Correlation summary
    let bestCorrs = [];
    Object.entries(D.optimal_lags).forEach(([key, val]) => {{
      const parts = key.split('|');
      if (parts[1] === ch) bestCorrs.push({{ driver: parts[0], metric: parts[2], ...val }});
    }});
    bestCorrs.sort((a,b) => Math.abs(b.correlation) - Math.abs(a.correlation));

    // Granger summary
    let grangerPairs = [];
    Object.entries(D.granger).forEach(([key, val]) => {{
      if (key.startsWith(ch + '|')) grangerPairs.push({{ metric: key.split('|')[1], ...val }});
    }});

    // Period summary (NOR)
    const periodNor = (D.period['NOR'] || []).find(r => r.channel === ch);

    html += `<div class="card" style="margin-bottom:16px;">
      <h3 style="color:var(--white);font-size:1rem;font-weight:600;margin-bottom:12px;">${{ch}}</h3>
      <div class="grid g3" style="margin-bottom:12px;">
        <div>
          <span style="color:var(--muted);font-size:0.78rem;">Best Correlation</span><br>
          <strong class="${{bestCorrs.length > 0 ? corrClass(bestCorrs[0].correlation) : ''}}">${{bestCorrs.length > 0 ? bestCorrs[0].correlation.toFixed(3) : '—'}}</strong>
          <span style="color:var(--muted);font-size:0.75rem;">${{bestCorrs.length > 0 ? ' (' + bestCorrs[0].driver + ' → ' + bestCorrs[0].metric + ', lag ' + bestCorrs[0].lag + 'd)' : ''}}</span>
        </div>
        <div>
          <span style="color:var(--muted);font-size:0.78rem;">NOR Uplift (High vs Low Display)</span><br>
          <strong class="${{periodNor && periodNor.uplift_pct > 0 ? 'pos' : 'neg'}}">${{periodNor ? fmt(periodNor.uplift_pct, 'pct') : '—'}}</strong>
          ${{periodNor && periodNor.significant ? '<span class="badge badge-green" style="margin-left:6px;">Sig</span>' : ''}}
        </div>
        <div>
          <span style="color:var(--muted);font-size:0.78rem;">Granger Causality</span><br>
          <strong>${{grangerPairs.filter(g => g.significant).length}}/${{grangerPairs.length}} significant</strong>
        </div>
      </div>`;

    if (bestCorrs.length > 0) {{
      html += '<table style="font-size:0.78rem;"><thead><tr><th>Driver</th><th>Metric</th><th>Lag</th><th>Correlation</th></tr></thead><tbody>';
      bestCorrs.slice(0, 5).forEach(c => {{
        html += `<tr><td>${{c.driver}}</td><td>${{c.metric}}</td><td>${{c.lag}}d</td><td class="${{corrClass(c.correlation)}}">${{c.correlation.toFixed(3)}}</td></tr>`;
      }});
      html += '</tbody></table>';
    }}
    html += '</div>';
  }});
  return html;
}}

// ── Tab 4: Trend Overlays ──
let activeTrend = 'spend_nor';

function renderTrends() {{
  const trendKeys = [
    ['spend_nor', 'Display Spend vs Channel NOR'],
    ['spend_act', 'Display Spend vs Channel Activations'],
    ['impr_nor', 'Display Impressions vs Channel NOR']
  ];
  let filterBar = '<div class="filter-bar">';
  trendKeys.forEach(([key, label]) => {{
    filterBar += `<button class="filter-btn ${{activeTrend === key ? 'active' : ''}}" onclick="activeTrend='${{key}}';render()">${{label}}</button>`;
  }});
  filterBar += '</div>';

  return `
    <div class="callout blue"><strong>Indexed trends:</strong> All series normalized to index=100 on their first available 28-day rolling mean. This allows visual comparison of directional movements regardless of absolute scale. Focus channels: SEM, SEO, Direct, Affiliate, Email.</div>
    ${{filterBar}}
    <div class="chart-container" style="height:450px;"><canvas id="trendChart"></canvas></div>
  `;
}}

function initTrendCharts() {{
  const tData = D.trends[activeTrend];
  if (!tData || !tData.dates || tData.dates.length === 0) return;
  const ctx = document.getElementById('trendChart');
  if (!ctx) return;

  // Downsample labels for readability
  const step = Math.max(1, Math.floor(tData.dates.length / 30));
  const labels = tData.dates.map((d, i) => i % step === 0 ? d : '');

  const colors = {{
    display: '#f59e0b',
    sem: '#3b82f6',
    seo: '#10b981',
    direct: '#a78bfa',
    affiliate: '#ef4444',
    email: '#06b6d4'
  }};

  const datasets = Object.entries(tData.series).map(([name, vals]) => ({{
    label: name === 'display' ? 'Display (driver)' : name,
    data: vals,
    borderColor: colors[name] || '#94a3b8',
    backgroundColor: 'transparent',
    borderWidth: name === 'display' ? 3 : 2,
    borderDash: name === 'display' ? [] : [5, 3],
    pointRadius: 0,
    tension: 0.3
  }}));

  const c = new Chart(ctx, {{
    type: 'line',
    data: {{ labels: tData.dates, datasets }},
    options: {{
      ...chartOpts('Indexed Trend Overlay (28-day rolling, base=100)'),
      scales: {{
        x: {{
          ticks: {{ color: '#94a3b8', font: {{ size: 9 }}, maxTicksLimit: 20, maxRotation: 45 }},
          grid: {{ color: '#1e293b' }}
        }},
        y: {{
          ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }},
          grid: {{ color: '#1e293b' }},
          title: {{ display: true, text: 'Index (100 = baseline)', color: '#94a3b8' }}
        }}
      }}
    }}
  }});
  chartInstances.push(c);
}}

// ── Tab 5: Methodology ──
function renderMethodology() {{
  let valTbl = '<table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>';
  VAL.forEach(v => {{
    valTbl += `<tr><td>${{v.check}}</td><td style="font-size:0.8rem;">${{v.result}}</td></tr>`;
  }});
  valTbl += '</tbody></table>';

  // Incremental contribution detail
  let incrTbl = '<table><thead><tr><th>Metric</th><th>Coefficient</th><th>R&sup2;</th><th>Contribution %</th><th>N obs</th></tr></thead><tbody>';
  Object.entries(D.incremental).forEach(([metric, r]) => {{
    incrTbl += `<tr><td>${{metric}}</td><td>${{r.coefficient ? r.coefficient.toFixed(4) : '—'}}</td>
      <td>${{r.r_squared ? r.r_squared.toFixed(3) : '—'}}</td>
      <td class="${{r.contribution_pct > 0 ? 'pos' : 'neg'}}">${{r.contribution_pct ? r.contribution_pct.toFixed(1) + '%' : '—'}}</td>
      <td>${{r.n_obs || '—'}}</td></tr>`;
  }});
  incrTbl += '</tbody></table>';

  return `
    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Analysis Methods</div>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;margin-bottom:12px;">
        <strong>Method 1: Lagged Cross-Correlation.</strong> For each (Display driver, target channel, metric) triple, compute Pearson correlation at lags 0-14 days. Lag N means Display on day T is correlated with the target on day T+N. The "optimal lag" is the lag with highest |r| among significant (p &lt; 0.05) results.
      </p>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;margin-bottom:12px;">
        <strong>Method 2: High vs Low Display Period Comparison.</strong> Weekly Display spend is split into terciles. Top &frac13; ("High Display") and bottom &frac13; ("Low Display") weeks are compared for each target channel metric. Welch's t-test assesses significance.
      </p>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;margin-bottom:12px;">
        <strong>Method 3: Granger Causality.</strong> Tests whether lagged Display spend improves prediction of a target channel metric beyond the target's own lagged values. Uses F-test comparing restricted (own lags) vs unrestricted (own lags + Display lags) OLS models.
      </p>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;">
        <strong>Method 4: Incremental Contribution.</strong> Regression of total non-Display metric on Display spend (same-day + 3-day + 7-day lags), controlling for day-of-week and month seasonality. Coefficient &times; avg spend / avg total gives estimated contribution %.
      </p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Incremental Contribution Estimates</div>
      ${{incrTbl}}
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Limitations & Caveats</div>
      <ul style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        <li>Correlation does not imply causation. Both Display and other channels may be driven by shared factors (seasonality, promotions, macro trends).</li>
        <li>Granger causality tests predictive power, not true causality. External confounders are not controlled.</li>
        <li>The incremental contribution regression uses simple OLS with day-of-week and month controls. It cannot isolate the causal effect of Display spend.</li>
        <li>Channels with fewer than {MIN_CHANNEL_DAYS} days of data are excluded from analysis.</li>
        <li>Numbers parsed from space-separated format; verify totals against source.</li>
        <li>A proper causal analysis would require a randomized experiment (e.g., geo-based Display holdout test).</li>
      </ul>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Metric Definitions</div>
      <table>
        <tr><td style="color:var(--muted);">NOR</td><td>Net Orders — count of completed orders.</td></tr>
        <tr><td style="color:var(--muted);">Activations</td><td>New customer activations.</td></tr>
        <tr><td style="color:var(--muted);">M1+VFM</td><td>Month 1+ Value for Money — primary revenue metric.</td></tr>
        <tr><td style="color:var(--muted);">VFM</td><td>Value for Money — total attributed value.</td></tr>
        <tr><td style="color:var(--muted);">GR</td><td>Gross Revenue.</td></tr>
        <tr><td style="color:var(--muted);">Spend</td><td>Media spend (Display driver variable).</td></tr>
        <tr><td style="color:var(--muted);">Impressions</td><td>Ad impressions served (Display driver variable).</td></tr>
      </table>
    </div>

    <div class="card">
      <div class="section-title" style="margin-top:0;">Data Validation Results</div>
      ${{valTbl}}
    </div>
  `;
}}

// Initial render
setTab(0);
</script>
</body>
</html>'''

# ── 13. Write HTML ────────────────────────────────────────────────────
with open(HTML_OUT, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nHTML report saved to: {HTML_OUT}")
print(f"File size: {len(html)/1024:.0f} KB")
print("Done!")
