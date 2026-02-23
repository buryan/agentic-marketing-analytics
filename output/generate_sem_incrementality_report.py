#!/usr/bin/env python3
"""SEM Incrementality Test — Dashboard Generator"""

import pandas as pd
import numpy as np
import json
import warnings
from pathlib import Path
from datetime import datetime
warnings.filterwarnings('ignore')

# ── Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
INPUT  = PROJECT_ROOT / "data" / "input"
OUTPUT = PROJECT_ROOT / "output"
PERF_FILE = INPUT / "sem_incrementality_data.xlsx"
CE_FILE   = INPUT / "sem_incrementality_google_ads_changes.xlsx"
HTML_OUT  = OUTPUT / "sem-incrementality-report.html"

# ── Constants / Thresholds ────────────────────────────────────────────
BREAKEVEN_MROAS = 0.80
ROAS_GAP_THRESHOLD = 3       # % relative
CONFIDENCE_MIN_SPEND = 3000  # $/arm

# ── 1. Load Data ───────────────────────────────────────────────────────
print("Loading data...")
df = pd.read_excel(PERF_FILE, sheet_name='Data')
ce = pd.read_excel(CE_FILE, sheet_name='data')

# Fix Region: NaN → "NA"
df['Region'] = df['Region'].fillna('NA')
# Parse dates
df['DateParsed'] = pd.to_datetime(df['Date'], format='%m/%d/%Y')
ce['change_date'] = pd.to_datetime(ce['change_date'])
ce['change_date_time'] = pd.to_datetime(ce['change_date_time'])

# ── 2. Data Validation ────────────────────────────────────────────────
print("\n=== DATA VALIDATION ===")
validation = {}

# V1: Column detection
v1 = "Column 'Campaign original' found" if 'Campaign original' in df.columns else "MISSING"
validation['v1'] = v1; print(f"V1: {v1}")

# V2: Region check
regions = sorted(df['Region'].unique())
v2 = f"Regions: {regions}"
validation['v2'] = v2; print(f"V2: {v2}")

# V3: Date range
date_min, date_max = df['DateParsed'].min(), df['DateParsed'].max()
lp_split = df[df['After learning period']=='YES']['DateParsed'].min()
v3 = f"Range: {date_min.strftime('%Y-%m-%d')} to {date_max.strftime('%Y-%m-%d')}, Post-LP from {lp_split.strftime('%Y-%m-%d')}"
validation['v3'] = v3; print(f"V3: {v3}")

# V4: Pairing completeness
v4_parts = []
for region in ['NA','INTL']:
    rdf = df[df['Region']==region]
    pairs = rdf['Campaign original'].nunique()
    # Check both arms exist for each pair
    arm_check = rdf.groupby('Campaign original')['Arm'].apply(lambda x: set(x.unique()))
    unpaired = [k for k,v in arm_check.items() if v != {'Control','Treatment'}]
    v4_parts.append(f"{region}: {pairs} pairs, unpaired: {len(unpaired)}")
v4 = "; ".join(v4_parts)
validation['v4'] = v4; print(f"V4: {v4}")

# V5: Arm balance
v5_parts = []
for region in ['NA','INTL']:
    rdf = df[df['Region']==region]
    dates = rdf['DateParsed'].unique()
    combos = rdf.groupby(['Campaign original','DateParsed','Arm']).size().reset_index()
    pivot = combos.pivot_table(index=['Campaign original','DateParsed'], columns='Arm', values=0, fill_value=0)
    gaps = ((pivot.get('Control',0)==0) | (pivot.get('Treatment',0)==0)).sum()
    v5_parts.append(f"{region}: {gaps} gaps")
v5 = "; ".join(v5_parts)
validation['v5'] = v5; print(f"V5: {v5}")

# V6: Zero-order days
orders_df = df[df['Metric']=='Orders']
zero_orders = orders_df[orders_df['Value']==0]
v6 = f"Zero-order campaign×day observations: {len(zero_orders)} out of {len(orders_df)}"
validation['v6'] = v6; print(f"V6: {v6}")

# V7: Program distribution
v7_parts = []
for region in ['NA','INTL']:
    rdf = df[df['Region']==region]
    for prog in sorted(rdf['Program'].unique()):
        n = rdf[rdf['Program']==prog]['Campaign original'].nunique()
        v7_parts.append(f"{region}-{prog}: {n}")
v7 = ", ".join(v7_parts)
validation['v7'] = v7; print(f"V7: {v7}")

# V8: Metric completeness
all_metrics = ['AOV','Activations','CPC','CTR','CVR','Clicks','Costs','Impressions','M1 Vfm','Orders','ROI','Reactivations']
found = sorted(df['Metric'].unique())
missing = [m for m in all_metrics if m not in found]
v8 = f"Found: {len(found)}/12 metrics. Missing: {missing if missing else 'none'}"
validation['v8'] = v8; print(f"V8: {v8}")

# V9: Totals sanity
v9_parts = []
for region in ['NA','INTL']:
    rdf = df[(df['Region']==region) & (df['After learning period']=='YES')]
    for arm in ['Control','Treatment']:
        adf = rdf[rdf['Arm']==arm]
        costs = adf[adf['Metric']=='Costs']['Value'].sum()
        m1 = adf[adf['Metric']=='M1 Vfm']['Value'].sum()
        orders = adf[adf['Metric']=='Orders']['Value'].sum()
        v9_parts.append(f"{region} {arm}: Costs=${costs:,.0f}, M1VFM=${m1:,.0f}, Orders={orders:,.0f}")
v9 = "; ".join(v9_parts)
validation['v9'] = v9; print(f"V9: {v9}")

# V10: Change events coverage
perf_campaigns = set(df['Campaign'].unique())
ce_campaigns = set(ce['campaign_name'].unique())
no_history = perf_campaigns - ce_campaigns
v10 = f"CE covers {len(ce_campaigns)} campaigns. {len(no_history)} perf campaigns with no change history: {no_history if no_history else 'none'}"
validation['v10'] = v10; print(f"V10: {v10}")

# V11: Mid-test tROAS changes
post_lp_start = df[df['After learning period'] == 'YES']['DateParsed'].min()
post_lp_end = df['DateParsed'].max()

# Derived date values
test_start = df['DateParsed'].min()
test_end = post_lp_end
lp_end = post_lp_start - pd.Timedelta(days=1)
test_days = (test_end - test_start).days + 1
post_lp_days = (post_lp_end - post_lp_start).days + 1
lp_days = (lp_end - test_start).days + 1

# Dynamic pair counts
pair_counts = {}
total_pairs = 0
for region in ['NA', 'INTL']:
    rdf = df[df['Region'] == region]
    region_pairs = rdf['Campaign original'].nunique()
    pair_counts[region] = {'total': region_pairs}
    total_pairs += region_pairs
    for prog in sorted(rdf['Program'].unique()):
        pair_counts[region][prog] = rdf[rdf['Program'] == prog]['Campaign original'].nunique()

# Formatted date helpers
def fmt_date(ts):
    return ts.strftime('%b %-d')

def fmt_date_full(ts):
    return ts.strftime('%b %-d, %Y')

date_subtitle = (f"50:50 tROAS Split Test | {fmt_date(test_start)} - {fmt_date_full(test_end)} "
                 f"| Post-LP: {fmt_date(post_lp_start)}-{fmt_date(post_lp_end)}")

na_prog_parts = ', '.join(f"{prog}:{pair_counts['NA'].get(prog, 0)}"
                          for prog in sorted(k for k in pair_counts['NA'] if k != 'total'))
intl_prog_parts = ', '.join(f"{prog}:{pair_counts['INTL'].get(prog, 0)}"
                            for prog in sorted(k for k in pair_counts['INTL'] if k != 'total'))
pair_summary = f"{total_pairs} total campaign pairs ({pair_counts['NA']['total']} NA, {pair_counts['INTL']['total']} INTL)"
mid_test_roas = ce[(ce['change_date'] >= post_lp_start) & (ce['change_date'] <= post_lp_end) & (ce['old_roas_value'].notna())]
mid_test_campaigns = mid_test_roas['campaign_name'].nunique()
v11 = f"Campaigns with tROAS changes during post-LP: {mid_test_campaigns}"
validation['v11'] = v11; print(f"V11: {v11}")

# ── 3. Build Analysis DataFrames ──────────────────────────────────────
print("\nBuilding analysis...")

# Post-LP data only for main analysis
post = df[df['After learning period']=='YES'].copy()

# Pivot: for each (Region, Program, Campaign original, Date, Arm) get all metrics
def pivot_metrics(data):
    """Pivot metric rows into columns for easier computation."""
    pv = data.pivot_table(index=['Region','Program','Campaign original','DateParsed','Arm'],
                          columns='Metric', values='Value', aggfunc='sum').reset_index()
    pv.columns.name = None
    return pv

pv_post = pivot_metrics(post)
pv_all = pivot_metrics(df)

# ── 4. Method 1: Arm-Level Aggregate ──────────────────────────────────
print("Computing Method 1...")

def compute_aggregate(data, group_cols):
    """Aggregate metrics by group_cols + Arm, compute deltas."""
    sum_metrics = ['Costs','M1 Vfm','Orders','Clicks','Impressions','Activations','Reactivations']
    agg = data.groupby(group_cols + ['Arm'])[sum_metrics].sum().reset_index()

    ctrl = agg[agg['Arm']=='Control'].drop(columns='Arm').set_index(group_cols)
    treat = agg[agg['Arm']=='Treatment'].drop(columns='Arm').set_index(group_cols)

    result = pd.DataFrame(index=ctrl.index)
    for m in sum_metrics:
        result[f'C_{m}'] = ctrl[m]
        result[f'T_{m}'] = treat[m]
        result[f'D_{m}'] = treat[m] - ctrl[m]

    result['C_ROAS'] = result['C_M1 Vfm'] / result['C_Costs'].replace(0, np.nan)
    result['T_ROAS'] = result['T_M1 Vfm'] / result['T_Costs'].replace(0, np.nan)
    result['mROAS'] = result['D_M1 Vfm'] / result['D_Costs'].replace(0, np.nan)

    # Funnel from totals
    result['C_CPC'] = result['C_Costs'] / result['C_Clicks'].replace(0, np.nan)
    result['T_CPC'] = result['T_Costs'] / result['T_Clicks'].replace(0, np.nan)
    result['C_CTR'] = result['C_Clicks'] / result['C_Impressions'].replace(0, np.nan)
    result['T_CTR'] = result['T_Clicks'] / result['T_Impressions'].replace(0, np.nan)
    result['C_CVR'] = result['C_Orders'] / result['C_Clicks'].replace(0, np.nan)
    result['T_CVR'] = result['T_Orders'] / result['T_Clicks'].replace(0, np.nan)
    result['C_AOV'] = result['C_M1 Vfm'] / result['C_Orders'].replace(0, np.nan)
    result['T_AOV'] = result['T_M1 Vfm'] / result['T_Orders'].replace(0, np.nan)

    # Delta % for funnel
    for f in ['CPC','CTR','CVR','AOV']:
        result[f'D_pct_{f}'] = (result[f'T_{f}'] - result[f'C_{f}']) / result[f'C_{f}'].replace(0, np.nan) * 100

    # Tier
    result['Tier'] = 'Unknown'
    mask_ep = (result['D_Costs'] > 0) & (result['D_M1 Vfm'] > 0)
    mask_os = (result['D_Costs'] > 0) & (result['D_M1 Vfm'] <= 0)
    mask_ep2 = (result['D_Costs'] <= 0) & (result['D_M1 Vfm'] <= 0)
    mask_am = (result['D_Costs'] <= 0) & (result['D_M1 Vfm'] > 0)
    result.loc[mask_ep, 'Tier'] = 'Expected'
    result.loc[mask_os, 'Tier'] = 'Overspend'
    result.loc[mask_ep2, 'Tier'] = 'Efficient Pruning'
    result.loc[mask_am, 'Tier'] = 'Ambiguous'

    return result.reset_index()

# Portfolio level (per region)
portfolio = compute_aggregate(pv_post, ['Region'])
# Program level
program = compute_aggregate(pv_post, ['Region','Program'])
# Campaign level
campaign = compute_aggregate(pv_post, ['Region','Program','Campaign original'])

# Daily level (per region)
daily = compute_aggregate(pv_post, ['Region','DateParsed'])
# Sort by date
daily = daily.sort_values(['Region','DateParsed'])

# Cumulative mROAS
for region in ['NA','INTL']:
    mask = daily['Region']==region
    d = daily.loc[mask].copy()
    d['cum_D_M1VFM'] = d['D_M1 Vfm'].cumsum()
    d['cum_D_Costs'] = d['D_Costs'].cumsum()
    d['cum_mROAS'] = d['cum_D_M1VFM'] / d['cum_D_Costs'].replace(0, np.nan)
    daily.loc[mask, 'cum_mROAS'] = d['cum_mROAS'].values

# Daily program level
daily_program = compute_aggregate(pv_post, ['Region','Program','DateParsed'])
daily_program = daily_program.sort_values(['Region','Program','DateParsed'])

# ── 5. Campaign step mROAS (waterfall) ────────────────────────────────
print("Computing waterfall...")

def compute_waterfall(camp_df, region):
    """Sort Expected tier by mROAS descending, compute running cumulative."""
    rd = camp_df[camp_df['Region']==region].copy()
    expected = rd[rd['Tier']=='Expected'].sort_values('mROAS', ascending=False).copy()
    if len(expected) == 0:
        return expected
    expected['cum_D_M1VFM'] = expected['D_M1 Vfm'].cumsum()
    expected['cum_D_Costs'] = expected['D_Costs'].cumsum()
    expected['cum_mROAS'] = expected['cum_D_M1VFM'] / expected['cum_D_Costs'].replace(0, np.nan)
    return expected

waterfall_na = compute_waterfall(campaign, 'NA')
waterfall_intl = compute_waterfall(campaign, 'INTL')

# Full step table: all campaigns sorted by mROAS descending with running cumulative
def compute_step_table(camp_df, region):
    rd = camp_df[camp_df['Region']==region].copy()
    rd = rd.sort_values('mROAS', ascending=False)
    rd['cum_D_M1VFM'] = rd['D_M1 Vfm'].cumsum()
    rd['cum_D_Costs'] = rd['D_Costs'].cumsum()
    rd['cum_mROAS'] = rd['cum_D_M1VFM'] / rd['cum_D_Costs'].replace(0, np.nan)
    return rd

step_na = compute_step_table(campaign, 'NA')
step_intl = compute_step_table(campaign, 'INTL')

# ── 6. Method 2a: ROAS-Based Classification ──────────────────────────
print("Computing Method 2a...")

def method2a(camp_df, region):
    rd = camp_df[camp_df['Region']==region].copy()
    rd['C_ROAS_val'] = rd['C_ROAS'].fillna(0)
    rd['T_ROAS_val'] = rd['T_ROAS'].fillna(0)
    rd['roas_gap_pct'] = (rd['T_ROAS_val'] - rd['C_ROAS_val']) / rd['C_ROAS_val'].replace(0, np.nan) * 100

    # Classification
    rd['M2a_Class'] = 'Neutral'
    rd.loc[rd['roas_gap_pct'] < -ROAS_GAP_THRESHOLD, 'M2a_Class'] = 'Lowered'
    rd.loc[rd['roas_gap_pct'] > ROAS_GAP_THRESHOLD, 'M2a_Class'] = 'Raised'

    # Confidence: need $CONFIDENCE_MIN_SPEND/arm
    rd['high_conf'] = (rd['C_Costs'] >= CONFIDENCE_MIN_SPEND) & (rd['T_Costs'] >= CONFIDENCE_MIN_SPEND)
    rd.loc[~rd['high_conf'], 'M2a_Class'] = 'Low Confidence'

    return rd

m2a_na = method2a(campaign, 'NA')
m2a_intl = method2a(campaign, 'INTL')

def m2a_summary(m2a_df):
    """Bucket summary for Method 2a."""
    rows = []
    for bucket in ['Lowered','Neutral','Raised','Low Confidence']:
        b = m2a_df[m2a_df['M2a_Class']==bucket]
        n = len(b)
        d_cost = b['D_Costs'].sum()
        d_m1 = b['D_M1 Vfm'].sum()
        mroas = d_m1 / d_cost if d_cost != 0 else None
        rows.append({'Bucket': bucket, 'N': n, 'D_Costs': d_cost, 'D_M1VFM': d_m1, 'mROAS': mroas})
    return pd.DataFrame(rows)

m2a_sum_na = m2a_summary(m2a_na)
m2a_sum_intl = m2a_summary(m2a_intl)

# ── 7. Method 2b: Daily × Campaign ───────────────────────────────────
print("Computing Method 2b...")

def method2b(pv_data, region):
    """Each campaign×day is an observation. Exclude zero-order days."""
    rd = pv_data[(pv_data['Region']==region)].copy()
    # Separate arms
    ctrl = rd[rd['Arm']=='Control'].set_index(['Campaign original','DateParsed'])
    treat = rd[rd['Arm']=='Treatment'].set_index(['Campaign original','DateParsed'])

    common = ctrl.index.intersection(treat.index)
    if len(common) == 0:
        return pd.DataFrame()

    obs = pd.DataFrame(index=common)
    for m in ['Costs','M1 Vfm','Orders','Clicks','Impressions']:
        obs[f'C_{m}'] = ctrl.loc[common, m].values
        obs[f'T_{m}'] = treat.loc[common, m].values

    # Exclude zero-order days (either arm has 0 orders)
    obs = obs[(obs['C_Orders'] > 0) & (obs['T_Orders'] > 0)].copy()

    obs['C_ROAS'] = obs['C_M1 Vfm'] / obs['C_Costs'].replace(0, np.nan)
    obs['T_ROAS'] = obs['T_M1 Vfm'] / obs['T_Costs'].replace(0, np.nan)
    obs['roas_gap_pct'] = (obs['T_ROAS'] - obs['C_ROAS']) / obs['C_ROAS'].replace(0, np.nan) * 100
    obs['D_Costs'] = obs['T_Costs'] - obs['C_Costs']
    obs['D_M1VFM'] = obs['T_M1 Vfm'] - obs['C_M1 Vfm']

    obs['M2b_Class'] = 'Neutral'
    obs.loc[obs['roas_gap_pct'] < -ROAS_GAP_THRESHOLD, 'M2b_Class'] = 'Lowered'
    obs.loc[obs['roas_gap_pct'] > ROAS_GAP_THRESHOLD, 'M2b_Class'] = 'Raised'

    return obs.reset_index()

# Use post-LP pivoted data
pv_post_lp = pv_all[pv_all['DateParsed'] >= post_lp_start].copy()
m2b_na = method2b(pv_post_lp, 'NA')
m2b_intl = method2b(pv_post_lp, 'INTL')

def m2b_summary(m2b_df):
    rows = []
    for bucket in ['Lowered','Neutral','Raised']:
        b = m2b_df[m2b_df['M2b_Class']==bucket]
        n = len(b)
        d_cost = b['D_Costs'].sum()
        d_m1 = b['D_M1VFM'].sum()
        mroas = d_m1 / d_cost if d_cost != 0 else None
        rows.append({'Bucket': bucket, 'N_obs': n, 'D_Costs': d_cost, 'D_M1VFM': d_m1, 'mROAS': mroas})
    return pd.DataFrame(rows)

m2b_sum_na = m2b_summary(m2b_na)
m2b_sum_intl = m2b_summary(m2b_intl)

# Method 2b campaign consistency
def m2b_campaign_consistency(m2b_df):
    """For each campaign, count how many days it was Lowered/Neutral/Raised."""
    if len(m2b_df) == 0:
        return pd.DataFrame()
    cons = m2b_df.groupby(['Campaign original','M2b_Class']).size().unstack(fill_value=0)
    for c in ['Lowered','Neutral','Raised']:
        if c not in cons.columns:
            cons[c] = 0
    cons['Total'] = cons.sum(axis=1)
    cons['Dominant'] = cons[['Lowered','Neutral','Raised']].idxmax(axis=1)
    return cons.reset_index()

m2b_cons_na = m2b_campaign_consistency(m2b_na)
m2b_cons_intl = m2b_campaign_consistency(m2b_intl)

# ── 8. Change Events Processing ──────────────────────────────────────
print("Processing change events...")

# Get all test period dates
test_dates = sorted(df['DateParsed'].unique())

# Compute effective daily tROAS per campaign
def compute_effective_troas(ce_df, campaigns):
    """For each campaign and date, find the effective tROAS."""
    roas_changes = ce_df[ce_df['old_roas_value'].notna()].sort_values('change_date_time')

    results = []
    for camp in campaigns:
        camp_changes = roas_changes[roas_changes['campaign_name']==camp].copy()
        if len(camp_changes) == 0:
            continue

        for dt in test_dates:
            # Find the most recent change on or before this date
            prior = camp_changes[camp_changes['change_date'] <= dt]
            if len(prior) > 0:
                latest = prior.iloc[-1]
                effective = latest['new_roas_value']
            else:
                # Use old_roas_value of earliest change
                effective = camp_changes.iloc[0]['old_roas_value']
            results.append({'campaign_name': camp, 'date': dt, 'effective_troas': effective})

    return pd.DataFrame(results)

all_perf_campaigns = df['Campaign'].unique()
troas_daily = compute_effective_troas(ce, all_perf_campaigns)

# Map campaigns to their pairs and arms
camp_info = df[['Campaign','Campaign original','Arm','Region','Program']].drop_duplicates()

# For each campaign pair, get control and treatment tROAS
def get_pair_troas(troas_daily_df, camp_info_df):
    """Get tROAS per pair per day."""
    merged = troas_daily_df.merge(camp_info_df, left_on='campaign_name', right_on='Campaign', how='left')
    if len(merged) == 0:
        return pd.DataFrame()

    ctrl = merged[merged['Arm']=='Control'][['Campaign original','date','effective_troas']].rename(columns={'effective_troas':'ctrl_troas'})
    treat = merged[merged['Arm']=='Treatment'][['Campaign original','date','effective_troas']].rename(columns={'effective_troas':'treat_troas'})

    pairs = ctrl.merge(treat, on=['Campaign original','date'], how='outer')
    pairs['troas_spread'] = pairs['ctrl_troas'] - pairs['treat_troas']
    return pairs

pair_troas = get_pair_troas(troas_daily, camp_info)

# End-of-period tROAS per campaign pair
def get_end_troas(pair_troas_df):
    """Get end-of-period (or most common post-LP) tROAS."""
    post_lp = pair_troas_df[pair_troas_df['date'] >= post_lp_start]
    if len(post_lp) == 0:
        return {}
    last_day = post_lp['date'].max()
    end = post_lp[post_lp['date']==last_day].set_index('Campaign original')
    return end[['ctrl_troas','treat_troas']].to_dict('index')

end_troas = get_end_troas(pair_troas)

# Mid-test tROAS changes detail
mid_test_detail = mid_test_roas[['campaign_name','change_date','old_roas_value','new_roas_value']].copy()
mid_test_detail = mid_test_detail.merge(camp_info[['Campaign','Arm','Campaign original']].drop_duplicates(),
                                         left_on='campaign_name', right_on='Campaign', how='left')

# Budget changes during test period
budget_changes = ce[(ce['old_budget_amount'].notna()) &
                     (ce['change_date'] >= test_start) &
                     (ce['change_date'] <= post_lp_end)].copy()
budget_changes = budget_changes[['campaign_name','change_date','old_budget_amount','new_budget_amount']].copy()
budget_changes = budget_changes.merge(camp_info[['Campaign','Arm','Campaign original']].drop_duplicates(),
                                       left_on='campaign_name', right_on='Campaign', how='left')

# Add tROAS info to campaign table
for idx, row in campaign.iterrows():
    co = row['Campaign original']
    if co in end_troas:
        campaign.loc[idx, 'ctrl_troas'] = end_troas[co].get('ctrl_troas', np.nan)
        campaign.loc[idx, 'treat_troas'] = end_troas[co].get('treat_troas', np.nan)
    else:
        campaign.loc[idx, 'ctrl_troas'] = np.nan
        campaign.loc[idx, 'treat_troas'] = np.nan

# tROAS ranges per region for exec summary
troas_ranges = {}
for region in ['NA','INTL']:
    rc = campaign[campaign['Region']==region]
    ct = rc['ctrl_troas'].dropna()
    tt = rc['treat_troas'].dropna()
    troas_ranges[region] = {
        'ctrl_min': ct.min() if len(ct) > 0 else None,
        'ctrl_max': ct.max() if len(ct) > 0 else None,
        'treat_min': tt.min() if len(tt) > 0 else None,
        'treat_max': tt.max() if len(tt) > 0 else None,
    }

# ── 9. Serialize data for HTML ────────────────────────────────────────
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
    return v

def df_to_records(d):
    return [{k: safe_val(v) for k,v in row.items()} for _, row in d.iterrows()]

# Prepare all data payloads
data_payload = {}
for region in ['NA','INTL']:
    r = {}
    # Portfolio
    p = portfolio[portfolio['Region']==region].iloc[0] if len(portfolio[portfolio['Region']==region]) > 0 else None
    if p is not None:
        r['portfolio'] = {k: safe_val(v) for k,v in p.to_dict().items()}
    else:
        r['portfolio'] = {}

    # Program
    r['programs'] = df_to_records(program[program['Region']==region])

    # Campaign
    r['campaigns'] = df_to_records(campaign[campaign['Region']==region])

    # Daily
    r['daily'] = df_to_records(daily[daily['Region']==region])

    # Daily program
    r['daily_program'] = df_to_records(daily_program[daily_program['Region']==region])

    # Waterfall
    wf = waterfall_na if region=='NA' else waterfall_intl
    r['waterfall'] = df_to_records(wf)

    # Step table
    st = step_na if region=='NA' else step_intl
    r['step_table'] = df_to_records(st)

    # Method 2a
    m2a = m2a_na if region=='NA' else m2a_intl
    r['m2a_campaigns'] = df_to_records(m2a)
    m2as = m2a_sum_na if region=='NA' else m2a_sum_intl
    r['m2a_summary'] = df_to_records(m2as)

    # Method 2b
    m2bs = m2b_sum_na if region=='NA' else m2b_sum_intl
    r['m2b_summary'] = df_to_records(m2bs)
    m2bc = m2b_cons_na if region=='NA' else m2b_cons_intl
    r['m2b_consistency'] = df_to_records(m2bc) if len(m2bc) > 0 else []

    # tROAS ranges
    r['troas_ranges'] = troas_ranges.get(region, {})

    # Tier counts
    rc = campaign[campaign['Region']==region]
    tier_counts = {}
    for tier in ['Expected','Overspend','Efficient Pruning','Ambiguous']:
        t = rc[rc['Tier']==tier]
        tier_counts[tier] = {
            'count': int(len(t)),
            'D_Costs': float(t['D_Costs'].sum()),
            'D_M1VFM': float(t['D_M1 Vfm'].sum()),
            'mROAS': float(t['D_M1 Vfm'].sum() / t['D_Costs'].sum()) if t['D_Costs'].sum() != 0 else None
        }
    r['tier_counts'] = tier_counts

    data_payload[region] = r

# Change events for tab 6
ce_tab6 = {}
# Mid-test tROAS changes
ce_tab6['mid_test_troas'] = df_to_records(mid_test_detail[['campaign_name','change_date','old_roas_value','new_roas_value','Arm','Campaign original']].dropna(subset=['Campaign original']).head(200))
# Budget changes
ce_tab6['budget_changes'] = df_to_records(budget_changes[['campaign_name','change_date','old_budget_amount','new_budget_amount','Arm','Campaign original']].dropna(subset=['Campaign original']).head(200))

# tROAS timeline for post-LP
if len(pair_troas) > 0:
    pt_post = pair_troas[pair_troas['date'] >= post_lp_start].copy()
    pt_post['date'] = pt_post['date'].dt.strftime('%Y-%m-%d')
    ce_tab6['pair_troas_timeline'] = df_to_records(pt_post)
else:
    ce_tab6['pair_troas_timeline'] = []

# Campaigns with stable vs disrupted conditions
stable_campaigns = set(campaign['Campaign original'].unique()) - set(mid_test_detail['Campaign original'].dropna().unique())
disrupted_campaigns = set(mid_test_detail['Campaign original'].dropna().unique())
ce_tab6['stable_count'] = len(stable_campaigns)
ce_tab6['disrupted_count'] = len(disrupted_campaigns)

# Validation results for info sheet
validation_list = [
    {"check": "V1: Column detection", "result": validation['v1']},
    {"check": "V2: Region check", "result": validation['v2']},
    {"check": "V3: Date range", "result": validation['v3']},
    {"check": "V4: Pairing completeness", "result": validation['v4']},
    {"check": "V5: Arm balance", "result": validation['v5']},
    {"check": "V6: Zero-order days", "result": validation['v6']},
    {"check": "V7: Program distribution", "result": validation['v7']},
    {"check": "V8: Metric completeness", "result": validation['v8']},
    {"check": "V9: Totals sanity", "result": validation['v9']},
    {"check": "V10: Change events coverage", "result": validation['v10']},
    {"check": "V11: Mid-test tROAS changes", "result": validation['v11']},
]

# ── 10. Generate HTML ─────────────────────────────────────────────────
print("Generating HTML...")

# JSON-serialize payloads
data_json = json.dumps(data_payload, default=str)
ce_json = json.dumps(ce_tab6, default=str)
val_json = json.dumps(validation_list, default=str)

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEM Incrementality Test Report</title>
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
.nav-bar {{ display: flex; gap: 8px; padding: 16px 32px; border-bottom: 1px solid var(--border); flex-wrap: wrap; align-items: center; }}
.region-toggle {{ display: flex; gap: 4px; margin-right: 16px; }}
.region-btn {{ padding: 6px 16px; border-radius: 6px; border: 1px solid var(--border); background: var(--card);
  color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.85rem; transition: all 0.2s; }}
.region-btn.active {{ background: var(--blue); color: var(--white); border-color: var(--blue); }}
.tab-btn {{ padding: 6px 14px; border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.82rem; transition: all 0.2s; }}
.tab-btn:hover {{ color: var(--text); }}
.tab-btn.active {{ background: var(--card); color: var(--white); border-color: var(--border); }}
.content {{ padding: 24px 32px; max-width: 1600px; margin: 0 auto; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
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
.callout.red {{ background: rgba(239,68,68,0.1); border-color: var(--red); }}
.callout.green {{ background: rgba(16,185,129,0.1); border-color: var(--green); }}
.callout.orange {{ background: rgba(245,158,11,0.1); border-color: var(--orange); }}
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
.chart-container {{ position: relative; height: 320px; background: var(--card); border-radius: 10px; border: 1px solid var(--border); padding: 16px; }}
.chart-container-sm {{ position: relative; height: 200px; background: var(--card); border-radius: 10px; border: 1px solid var(--border); padding: 12px; }}
.section-title {{ font-size: 1.1rem; font-weight: 600; margin: 24px 0 12px; }}
.section-title:first-child {{ margin-top: 0; }}
.filter-bar {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
.filter-btn {{ padding: 4px 12px; border-radius: 4px; border: 1px solid var(--border); background: var(--card);
  color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.78rem; }}
.filter-btn.active {{ background: var(--blue); color: var(--white); border-color: var(--blue); }}
.methodology-box {{ background: rgba(59,130,246,0.05); border: 1px solid rgba(59,130,246,0.2); border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
.methodology-box h3 {{ color: var(--blue); margin-bottom: 8px; }}
.methodology-box p {{ color: var(--muted); font-size: 0.85rem; line-height: 1.6; }}
.program-card {{ margin-bottom: 20px; }}
.program-card h3 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: var(--white); }}
@media (max-width: 1200px) {{ .g4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 768px) {{ .g2, .g3, .g4 {{ grid-template-columns: 1fr; }} .content {{ padding: 16px; }} }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>SEM Incrementality Test Report</h1>
    <div class="subtitle">{date_subtitle}</div>
  </div>
  <div class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>

<div class="nav-bar">
  <div class="region-toggle">
    <button class="region-btn active" onclick="setRegion('NA')">NA</button>
    <button class="region-btn" onclick="setRegion('INTL')">INTL</button>
  </div>
  <button class="tab-btn active" onclick="setTab(0)">Exec Summary</button>
  <button class="tab-btn" onclick="setTab(1)">Daily KPIs</button>
  <button class="tab-btn" onclick="setTab(2)">Programs</button>
  <button class="tab-btn" onclick="setTab(3)">Campaigns</button>
  <button class="tab-btn" onclick="setTab(4)">Method 2</button>
  <button class="tab-btn" onclick="setTab(5)">tROAS &amp; Budget</button>
  <button class="tab-btn" onclick="setTab(6)">AI Commentary</button>
  <button class="tab-btn" onclick="setTab(7)">Info Sheet</button>
</div>

<div class="content" id="mainContent"></div>

<script>
// ── Data ──
const D = {data_json};
const CE = {ce_json};
const VAL = {val_json};

let currentRegion = 'NA';
let currentTab = 0;
let chartInstances = [];

function destroyCharts() {{
  chartInstances.forEach(c => {{ try {{ c.destroy(); }} catch(e) {{}} }});
  chartInstances = [];
}}

function fmt(v, type) {{
  if (v === null || v === undefined || isNaN(v)) return '—';
  if (type === '$') return (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
  if (type === '$d') return (v < 0 ? '-' : '+') + '$' + Math.abs(v).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
  if (type === 'pct') return (v > 0 ? '+' : '') + v.toFixed(1) + '%';
  if (type === 'x') return v.toFixed(2) + 'x';
  if (type === 'mroas') return v.toFixed(2);
  if (type === 'n') return Math.round(v).toLocaleString();
  if (type === '$2') return '$' + v.toFixed(2);
  if (type === 'pct2') return (v * 100).toFixed(2) + '%';
  return v.toFixed(2);
}}

function mroasClass(v) {{
  if (v === null || v === undefined || isNaN(v)) return '';
  if (v >= 0.80) return 'pos';
  if (v > 0) return 'warn';
  return 'neg';
}}

function mroasBadge(v) {{
  if (v === null || v === undefined || isNaN(v)) return '<span class="badge">—</span>';
  const cls = v >= 0.80 ? 'badge-green' : (v > 0 ? 'badge-orange' : 'badge-red');
  return `<span class="badge ${{cls}}">${{v.toFixed(2)}}</span>`;
}}

function deltaClass(v, invert) {{
  if (v === null || v === undefined || isNaN(v)) return '';
  if (invert) return v > 0 ? 'neg' : 'pos';
  return v > 0 ? 'pos' : 'neg';
}}

function tierBadge(t) {{
  const m = {{'Expected':'badge-green','Overspend':'badge-red','Efficient Pruning':'badge-blue','Ambiguous':'badge-orange'}};
  return `<span class="badge ${{m[t] || 'badge-purple'}}">${{t}}</span>`;
}}

function chartOpts(title) {{
  return {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      title: {{ display: !!title, text: title || '', color: '#e2e8f0', font: {{ family: 'Space Grotesk', size: 14 }} }},
      legend: {{ labels: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 11 }} }} }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 10 }} }}, grid: {{ color: '#1e293b' }} }}
    }}
  }};
}}

function setRegion(r) {{
  currentRegion = r;
  document.querySelectorAll('.region-btn').forEach(b => b.classList.toggle('active', b.textContent.trim() === r));
  render();
}}

function setTab(t) {{
  currentTab = t;
  document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === t));
  render();
}}

function render() {{
  destroyCharts();
  const el = document.getElementById('mainContent');
  const rd = D[currentRegion];
  if (!rd || !rd.portfolio) {{ el.innerHTML = '<div class="callout red">No data for this region.</div>'; return; }}
  const tabs = [renderExec, renderDaily, renderPrograms, renderCampaigns, renderMethod2, renderChanges, renderCommentary, renderInfo];
  el.innerHTML = tabs[currentTab](rd);
  // Post-render chart init
  if (currentTab === 0) initExecCharts(rd);
  if (currentTab === 1) initDailyCharts(rd);
  if (currentTab === 2) initProgramCharts(rd);
  if (currentTab === 3) initCampaignCharts(rd);
  if (currentTab === 4) initMethod2Charts(rd);
}}

// ── Tab 1: Exec Summary ──
function renderExec(rd) {{
  const p = rd.portfolio;
  const mroas = p.mROAS;
  const tr = rd.troas_ranges;
  const ctrlRange = tr.ctrl_min !== null ? `${{Number(tr.ctrl_min).toFixed(2)}} - ${{Number(tr.ctrl_max).toFixed(2)}}` : 'N/A';
  const treatRange = tr.treat_min !== null ? `${{Number(tr.treat_min).toFixed(2)}} - ${{Number(tr.treat_max).toFixed(2)}}` : 'N/A';

  const verdict = mroas >= 0.80 ?
    `<div class="callout green"><strong>Verdict: Incremental spend is profitable.</strong> Portfolio mROAS of ${{fmt(mroas,'mroas')}} exceeds the 0.80 breakeven threshold. The looser tROAS targets generated ${{fmt(p['D_M1 Vfm'],'$d')}} incremental M1VFM on ${{fmt(p.D_Costs,'$d')}} incremental cost.</div>` :
    mroas > 0 ?
    `<div class="callout orange"><strong>Verdict: Incremental spend is marginally positive but below breakeven.</strong> Portfolio mROAS of ${{fmt(mroas,'mroas')}} is below the 0.80 threshold. Treatment generated ${{fmt(p['D_M1 Vfm'],'$d')}} incremental M1VFM on ${{fmt(p.D_Costs,'$d')}} incremental cost.</div>` :
    `<div class="callout red"><strong>Verdict: Incremental spend is unprofitable.</strong> Portfolio mROAS of ${{fmt(mroas,'mroas')}} is negative. Looser targets cost more but returned less revenue.</div>`;

  let progTable = '<table><thead><tr><th>Program</th><th>N</th><th>Ctrl ROAS</th><th>Treat ROAS</th><th>&#916;Cost</th><th>&#916;M1VFM</th><th>mROAS</th><th>Verdict</th></tr></thead><tbody>';
  rd.programs.forEach(pr => {{
    const v = pr.mROAS >= 0.80 ? 'Profitable' : (pr.mROAS > 0 ? 'Below BE' : 'Unprofitable');
    const vc = pr.mROAS >= 0.80 ? 'pos' : (pr.mROAS > 0 ? 'warn' : 'neg');
    const n = rd.campaigns.filter(c => c.Program === pr.Program).length;
    progTable += `<tr><td>${{pr.Program}}</td><td>${{n}}</td><td>${{fmt(pr.C_ROAS,'x')}}</td><td>${{fmt(pr.T_ROAS,'x')}}</td>
      <td class="${{deltaClass(pr.D_Costs, true)}}">${{fmt(pr.D_Costs,'$d')}}</td>
      <td class="${{deltaClass(pr['D_M1 Vfm'])}}">${{fmt(pr['D_M1 Vfm'],'$d')}}</td>
      <td class="${{mroasClass(pr.mROAS)}}">${{fmt(pr.mROAS,'mroas')}}</td>
      <td class="${{vc}}">${{v}}</td></tr>`;
  }});
  progTable += '</tbody></table>';

  // Recommendations
  let recs = '<ol style="color:var(--muted);font-size:0.85rem;line-height:1.8;padding-left:20px;">';
  if (mroas >= 0.80) {{
    recs += '<li>Consider scaling the looser tROAS targets to more campaigns given positive portfolio mROAS.</li>';
    recs += '<li>Focus on "Expected" tier campaigns which are driving incremental profitable volume.</li>';
    recs += '<li>Monitor "Overspend" campaigns closely — consider tightening targets back for those pairs.</li>';
  }} else if (mroas > 0) {{
    recs += '<li>Incremental returns are positive but below breakeven — consider a more moderate tROAS reduction (e.g., 5% instead of 10%).</li>';
    recs += '<li>Identify high-performing campaign subsets where mROAS exceeds 0.80 and scale selectively.</li>';
    recs += '<li>Extend the test period to accumulate more statistical confidence.</li>';
  }} else {{
    recs += '<li>Revert treatment campaigns to control tROAS levels — the looser targets are destroying value.</li>';
    recs += '<li>Investigate program-level differences to find any pockets of positive incrementality.</li>';
    recs += '<li>Review whether the tROAS reduction was too aggressive for the current competitive landscape.</li>';
  }}
  recs += '<li>Review campaigns flagged with mid-test tROAS changes — their results may be confounded.</li>';
  recs += '<li>Consider extending the test duration beyond {post_lp_days} post-LP days for stronger statistical power.</li>';
  recs += '</ol>';

  return `
    <div class="methodology-box">
      <h3>Test Methodology</h3>
      <p>50:50 campaign-split incrementality test. Control arm targets: ${{ctrlRange}}. Treatment arm targets: ${{treatRange}}.
      {pair_summary}. Test period: {fmt_date(test_start)}-{fmt_date_full(test_end)}. Post-learning period (primary analysis): {fmt_date(post_lp_start)}-{fmt_date(post_lp_end)} ({post_lp_days} days).
      Breakeven mROAS threshold: 0.80.</p>
    </div>
    <div class="grid g4">
      <div class="card"><h3>Portfolio mROAS</h3><div class="big ${{mroasClass(mroas)}}">${{fmt(mroas,'mroas')}}</div><div class="sub">Breakeven: 0.80</div></div>
      <div class="card"><h3>&#916; Cost (T - C)</h3><div class="big ${{deltaClass(p.D_Costs, true)}}">${{fmt(p.D_Costs,'$d')}}</div><div class="sub">Incremental spend</div></div>
      <div class="card"><h3>&#916; M1VFM (T - C)</h3><div class="big ${{deltaClass(p['D_M1 Vfm'])}}">${{fmt(p['D_M1 Vfm'],'$d')}}</div><div class="sub">Incremental revenue</div></div>
      <div class="card"><h3>ROAS Shift</h3><div class="big">${{fmt(p.C_ROAS,'x')}} &rarr; ${{fmt(p.T_ROAS,'x')}}</div><div class="sub">Control &rarr; Treatment</div></div>
    </div>
    ${{verdict}}
    <div class="section-title">Program Snapshot</div>
    <div class="card" style="overflow-x:auto;">${{progTable}}</div>
    <div class="section-title">Recommendations</div>
    <div class="card">
      <p style="color:var(--orange);font-size:0.8rem;margin-bottom:10px;">Data-driven suggestions — consider business context before implementing</p>
      ${{recs}}
    </div>
  `;
}}

function initExecCharts(rd) {{}}

// ── Tab 2: Daily KPIs ──
function renderDaily(rd) {{
  const d = rd.daily;
  const last = d[d.length - 1];
  const cumMroas = last ? last.cum_mROAS : null;

  let tbl = '<table><thead><tr><th>Date</th><th>C Cost</th><th>T Cost</th><th>&#916;Cost</th><th>C M1VFM</th><th>T M1VFM</th><th>&#916;M1VFM</th><th>C ROAS</th><th>T ROAS</th><th>Day mROAS</th><th>Cum mROAS</th></tr></thead><tbody>';
  d.forEach(r => {{
    tbl += `<tr><td>${{r.DateParsed}}</td><td>${{fmt(r.C_Costs,'$')}}</td><td>${{fmt(r.T_Costs,'$')}}</td>
      <td class="${{deltaClass(r.D_Costs, true)}}">${{fmt(r.D_Costs,'$d')}}</td>
      <td>${{fmt(r['C_M1 Vfm'],'$')}}</td><td>${{fmt(r['T_M1 Vfm'],'$')}}</td>
      <td class="${{deltaClass(r['D_M1 Vfm'])}}">${{fmt(r['D_M1 Vfm'],'$d')}}</td>
      <td>${{fmt(r.C_ROAS,'x')}}</td><td>${{fmt(r.T_ROAS,'x')}}</td>
      <td class="${{mroasClass(r.mROAS)}}">${{fmt(r.mROAS,'mroas')}}</td>
      <td class="${{mroasClass(r.cum_mROAS)}}">${{fmt(r.cum_mROAS,'mroas')}}</td></tr>`;
  }});
  tbl += '</tbody></table>';

  // Daily funnel table
  let funnel = '<table><thead><tr><th>Date</th><th>C CPC</th><th>T CPC</th><th>&#916;CPC%</th><th>C CTR</th><th>T CTR</th><th>&#916;CTR%</th><th>C CVR</th><th>T CVR</th><th>&#916;CVR%</th><th>C AOV</th><th>T AOV</th><th>&#916;AOV%</th></tr></thead><tbody>';
  d.forEach(r => {{
    funnel += `<tr><td>${{r.DateParsed}}</td>
      <td>${{fmt(r.C_CPC,'$2')}}</td><td>${{fmt(r.T_CPC,'$2')}}</td><td class="${{deltaClass(r.D_pct_CPC,true)}}">${{fmt(r.D_pct_CPC,'pct')}}</td>
      <td>${{fmt(r.C_CTR,'pct2')}}</td><td>${{fmt(r.T_CTR,'pct2')}}</td><td class="${{deltaClass(r.D_pct_CTR)}}">${{fmt(r.D_pct_CTR,'pct')}}</td>
      <td>${{fmt(r.C_CVR,'pct2')}}</td><td>${{fmt(r.T_CVR,'pct2')}}</td><td class="${{deltaClass(r.D_pct_CVR)}}">${{fmt(r.D_pct_CVR,'pct')}}</td>
      <td>${{fmt(r.C_AOV,'$2')}}</td><td>${{fmt(r.T_AOV,'$2')}}</td><td class="${{deltaClass(r.D_pct_AOV)}}">${{fmt(r.D_pct_AOV,'pct')}}</td></tr>`;
  }});
  funnel += '</tbody></table>';

  return `
    <div class="grid g3">
      <div class="card"><h3>Control ROAS (Post-LP Avg)</h3><div class="big">${{fmt(d.length > 0 ? d.reduce((s,r)=>s+r['C_M1 Vfm'],0)/d.reduce((s,r)=>s+r.C_Costs,0) : null, 'x')}}</div></div>
      <div class="card"><h3>Treatment ROAS (Post-LP Avg)</h3><div class="big">${{fmt(d.length > 0 ? d.reduce((s,r)=>s+r['T_M1 Vfm'],0)/d.reduce((s,r)=>s+r.T_Costs,0) : null, 'x')}}</div></div>
      <div class="card"><h3>Cumulative mROAS</h3><div class="big ${{mroasClass(cumMroas)}}">${{fmt(cumMroas,'mroas')}}</div></div>
    </div>
    <div class="section-title">Daily ROAS & Cumulative mROAS</div>
    <div class="chart-container"><canvas id="dailyRoasChart"></canvas></div>
    <div style="height:16px"></div>
    <div class="section-title">Daily mROAS Bars + Cumulative Overlay</div>
    <div class="chart-container"><canvas id="dailyMroasChart"></canvas></div>
    <div class="section-title">Daily Performance Table</div>
    <div class="card table-wrap">${{tbl}}</div>
    <div class="section-title">Daily Funnel Metrics</div>
    <div class="card table-wrap">${{funnel}}</div>
  `;
}}

function initDailyCharts(rd) {{
  const d = rd.daily;
  const labels = d.map(r => r.DateParsed);
  const cRoas = d.map(r => r.C_ROAS);
  const tRoas = d.map(r => r.T_ROAS);
  const cumM = d.map(r => r.cum_mROAS);
  const dayM = d.map(r => r.mROAS);

  // Chart 1: ROAS lines + cum mROAS
  const ctx1 = document.getElementById('dailyRoasChart');
  if (ctx1) {{
    const c1 = new Chart(ctx1, {{
      type: 'line',
      data: {{
        labels,
        datasets: [
          {{ label: 'Control ROAS', data: cRoas, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', borderWidth: 2.5, pointRadius: 3, tension: 0.3 }},
          {{ label: 'Treatment ROAS', data: tRoas, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 2.5, pointRadius: 3, tension: 0.3 }},
          {{ label: 'Cum mROAS', data: cumM, borderColor: '#ffffff', borderWidth: 2, pointRadius: 2, tension: 0.3, borderDash: [5,3] }}
        ]
      }},
      options: chartOpts('Daily ROAS (Post-LP)')
    }});
    chartInstances.push(c1);
  }}

  // Chart 2: mROAS bars + cumulative overlay
  const ctx2 = document.getElementById('dailyMroasChart');
  if (ctx2) {{
    const barColors = dayM.map(v => v >= 0.80 ? '#10b981' : (v > 0 ? '#f59e0b' : '#ef4444'));
    const c2 = new Chart(ctx2, {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{ label: 'Daily mROAS', data: dayM, backgroundColor: barColors, borderRadius: 4, yAxisID: 'y' }},
          {{ label: 'Cum mROAS', data: cumM, type: 'line', borderColor: '#ffffff', borderWidth: 2, pointRadius: 2, tension: 0.3, yAxisID: 'y' }}
        ]
      }},
      options: {{
        ...chartOpts('Daily mROAS + Cumulative'),
        scales: {{
          x: {{ ticks: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
          y: {{ ticks: {{ color: '#94a3b8', font: {{ family: 'SF Mono, monospace', size: 10 }} }}, grid: {{ color: '#1e293b' }} }}
        }}
      }}
    }});
    chartInstances.push(c2);
  }}
}}

// ── Tab 3: Programs ──
function renderPrograms(rd) {{
  let html = '';
  rd.programs.forEach((pr, i) => {{
    const dprog = rd.daily_program.filter(d => d.Program === pr.Program);
    const n = rd.campaigns.filter(c => c.Program === pr.Program).length;
    const orders = pr.C_Orders + pr.T_Orders;

    // Get typical tROAS spread for this program
    const progCamps = rd.campaigns.filter(c => c.Program === pr.Program);
    const avgCtrlT = progCamps.filter(c => c.ctrl_troas).reduce((s,c) => s + c.ctrl_troas, 0) / (progCamps.filter(c => c.ctrl_troas).length || 1);
    const avgTreatT = progCamps.filter(c => c.treat_troas).reduce((s,c) => s + c.treat_troas, 0) / (progCamps.filter(c => c.treat_troas).length || 1);

    html += `
      <div class="card program-card">
        <h3>${{pr.Program}} <span style="color:var(--muted);font-weight:400;font-size:0.85rem;">(${{n}} pairs, ${{fmt(orders,'n')}} total orders)</span></h3>
        <div class="grid g4" style="margin:12px 0;">
          <div><span style="color:var(--muted);font-size:0.78rem;">Ctrl ROAS</span><br><strong>${{fmt(pr.C_ROAS,'x')}}</strong></div>
          <div><span style="color:var(--muted);font-size:0.78rem;">Treat ROAS</span><br><strong>${{fmt(pr.T_ROAS,'x')}}</strong></div>
          <div><span style="color:var(--muted);font-size:0.78rem;">&#916;Cost</span><br><strong class="${{deltaClass(pr.D_Costs,true)}}">${{fmt(pr.D_Costs,'$d')}}</strong></div>
          <div><span style="color:var(--muted);font-size:0.78rem;">mROAS</span><br><strong class="${{mroasClass(pr.mROAS)}}">${{fmt(pr.mROAS,'mroas')}}</strong></div>
        </div>
        <div style="color:var(--muted);font-size:0.8rem;margin-bottom:8px;">Typical tROAS: Control ${{avgCtrlT.toFixed(2)}} | Treatment ${{avgTreatT.toFixed(2)}} | Spread ${{(avgCtrlT - avgTreatT).toFixed(2)}}</div>
        <table><thead><tr><th>Metric</th><th>Control</th><th>Treatment</th><th>&#916;%</th></tr></thead><tbody>
          <tr><td>CPC</td><td>${{fmt(pr.C_CPC,'$2')}}</td><td>${{fmt(pr.T_CPC,'$2')}}</td><td class="${{deltaClass(pr.D_pct_CPC,true)}}">${{fmt(pr.D_pct_CPC,'pct')}}</td></tr>
          <tr><td>CTR</td><td>${{fmt(pr.C_CTR,'pct2')}}</td><td>${{fmt(pr.T_CTR,'pct2')}}</td><td class="${{deltaClass(pr.D_pct_CTR)}}">${{fmt(pr.D_pct_CTR,'pct')}}</td></tr>
          <tr><td>CVR</td><td>${{fmt(pr.C_CVR,'pct2')}}</td><td>${{fmt(pr.T_CVR,'pct2')}}</td><td class="${{deltaClass(pr.D_pct_CVR)}}">${{fmt(pr.D_pct_CVR,'pct')}}</td></tr>
          <tr><td>AOV</td><td>${{fmt(pr.C_AOV,'$2')}}</td><td>${{fmt(pr.T_AOV,'$2')}}</td><td class="${{deltaClass(pr.D_pct_AOV)}}">${{fmt(pr.D_pct_AOV,'pct')}}</td></tr>
        </tbody></table>
        <div class="chart-container-sm" style="margin-top:12px;"><canvas id="progChart${{i}}"></canvas></div>
      </div>`;
  }});
  return html;
}}

function initProgramCharts(rd) {{
  rd.programs.forEach((pr, i) => {{
    const dprog = rd.daily_program.filter(d => d.Program === pr.Program);
    const ctx = document.getElementById(`progChart${{i}}`);
    if (ctx && dprog.length > 0) {{
      const c = new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: dprog.map(d => d.DateParsed),
          datasets: [
            {{ label: 'Ctrl ROAS', data: dprog.map(d => d.C_ROAS), borderColor: '#3b82f6', borderWidth: 2, pointRadius: 2, tension: 0.3 }},
            {{ label: 'Treat ROAS', data: dprog.map(d => d.T_ROAS), borderColor: '#ef4444', borderWidth: 2, pointRadius: 2, tension: 0.3 }}
          ]
        }},
        options: {{ ...chartOpts(), plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }} }}
      }});
      chartInstances.push(c);
    }}
  }});
}}

// ── Tab 4: Campaigns ──
function renderCampaigns(rd) {{
  // Tier summary
  const tiers = rd.tier_counts;
  let tierCards = '<div class="grid g4">';
  ['Expected','Overspend','Efficient Pruning','Ambiguous'].forEach(t => {{
    const tc = tiers[t];
    tierCards += `<div class="card"><h3>${{t}}</h3><div class="big">${{tc.count}}</div>
      <div class="sub">&#916;Cost: ${{fmt(tc.D_Costs,'$d')}} | mROAS: ${{tc.mROAS !== null ? tc.mROAS.toFixed(2) : '—'}}</div></div>`;
  }});
  tierCards += '</div>';

  // Campaign table
  let tbl = '<table><thead><tr><th>Campaign</th><th>Program</th><th>Tier</th><th>C ROAS</th><th>T ROAS</th><th>Ctrl tROAS</th><th>Treat tROAS</th><th>CPC &#916;%</th><th>CVR &#916;%</th><th>AOV &#916;%</th><th>C Cost</th><th>&#916;Cost</th><th>&#916;M1VFM</th><th>mROAS</th></tr></thead><tbody>';
  const sortedCamps = [...rd.campaigns].sort((a,b) => (b.mROAS||0) - (a.mROAS||0));
  sortedCamps.forEach(c => {{
    const unreliable = Math.abs(c.D_Costs) < 100;
    tbl += `<tr>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{c['Campaign original']}}">${{c['Campaign original']}}</td>
      <td>${{c.Program}}</td>
      <td>${{tierBadge(c.Tier)}}</td>
      <td>${{fmt(c.C_ROAS,'x')}}</td><td>${{fmt(c.T_ROAS,'x')}}</td>
      <td>${{c.ctrl_troas ? c.ctrl_troas.toFixed(2) : '—'}}</td>
      <td>${{c.treat_troas ? c.treat_troas.toFixed(2) : '—'}}</td>
      <td class="${{deltaClass(c.D_pct_CPC,true)}}">${{fmt(c.D_pct_CPC,'pct')}}</td>
      <td class="${{deltaClass(c.D_pct_CVR)}}">${{fmt(c.D_pct_CVR,'pct')}}</td>
      <td class="${{deltaClass(c.D_pct_AOV)}}">${{fmt(c.D_pct_AOV,'pct')}}</td>
      <td>${{fmt(c.C_Costs,'$')}}</td>
      <td class="${{deltaClass(c.D_Costs,true)}}">${{fmt(c.D_Costs,'$d')}}</td>
      <td class="${{deltaClass(c['D_M1 Vfm'])}}">${{fmt(c['D_M1 Vfm'],'$d')}}</td>
      <td class="${{mroasClass(c.mROAS)}}">${{unreliable ? '<span title="|ΔCost|<$100 — unreliable">&#9888; ' + fmt(c.mROAS,'mroas') + '</span>' : fmt(c.mROAS,'mroas')}}</td>
    </tr>`;
  }});
  tbl += '</tbody></table>';

  // Step mROAS table
  let stepTbl = '<table><thead><tr><th>#</th><th>Campaign</th><th>Program</th><th>Tier</th><th>&#916;Cost</th><th>&#916;M1VFM</th><th>Step mROAS</th><th>Cum mROAS</th></tr></thead><tbody>';
  rd.step_table.forEach((s, i) => {{
    stepTbl += `<tr><td>${{i+1}}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{s['Campaign original']}}</td>
      <td>${{s.Program}}</td><td>${{tierBadge(s.Tier)}}</td>
      <td class="${{deltaClass(s.D_Costs,true)}}">${{fmt(s.D_Costs,'$d')}}</td>
      <td class="${{deltaClass(s['D_M1 Vfm'])}}">${{fmt(s['D_M1 Vfm'],'$d')}}</td>
      <td class="${{mroasClass(s.mROAS)}}">${{fmt(s.mROAS,'mroas')}}</td>
      <td class="${{mroasClass(s.cum_mROAS)}}">${{fmt(s.cum_mROAS,'mroas')}}</td></tr>`;
  }});
  stepTbl += '</tbody></table>';

  return `
    <div class="section-title">Tier Summary</div>
    ${{tierCards}}
    <div class="section-title">Cumulative mROAS Waterfall (Expected Tier)</div>
    <div class="chart-container"><canvas id="waterfallChart"></canvas></div>
    <div class="section-title">Full Campaign Table</div>
    <div class="card table-wrap" style="max-height:600px;">${{tbl}}</div>
    <div class="section-title">Step mROAS Table (All Campaigns)</div>
    <div class="card table-wrap" style="max-height:500px;">${{stepTbl}}</div>
  `;
}}

function initCampaignCharts(rd) {{
  const wf = rd.waterfall;
  if (wf.length === 0) return;
  const ctx = document.getElementById('waterfallChart');
  if (!ctx) return;
  const labels = wf.map(w => w['Campaign original'].substring(0, 30));
  const stepM = wf.map(w => w.mROAS);
  const cumM = wf.map(w => w.cum_mROAS);
  const colors = stepM.map(v => v >= 0.80 ? '#10b981' : (v > 0 ? '#f59e0b' : '#ef4444'));

  const c = new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{ label: 'Step mROAS', data: stepM, backgroundColor: colors, borderRadius: 4, yAxisID: 'y' }},
        {{ label: 'Cum mROAS', data: cumM, type: 'line', borderColor: '#ffffff', borderWidth: 2.5, pointRadius: 3, tension: 0.3, yAxisID: 'y' }}
      ]
    }},
    options: {{
      ...chartOpts('Waterfall: Expected Tier by mROAS'),
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: '#1e293b' }} }},
        y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
      }}
    }}
  }});
  chartInstances.push(c);
}}

// ── Tab 5: Method 2 ──
function renderMethod2(rd) {{
  // Method 2a
  let m2aTbl = '<table><thead><tr><th>Bucket</th><th>N</th><th>&#916;Cost</th><th>&#916;M1VFM</th><th>mROAS</th></tr></thead><tbody>';
  rd.m2a_summary.forEach(r => {{
    m2aTbl += `<tr><td>${{r.Bucket}}</td><td>${{r.N}}</td>
      <td class="${{deltaClass(r.D_Costs,true)}}">${{fmt(r.D_Costs,'$d')}}</td>
      <td class="${{deltaClass(r.D_M1VFM)}}">${{fmt(r.D_M1VFM,'$d')}}</td>
      <td class="${{mroasClass(r.mROAS)}}">${{fmt(r.mROAS,'mroas')}}</td></tr>`;
  }});
  m2aTbl += '</tbody></table>';

  // Method 2a campaign detail
  let m2aCamps = '<table><thead><tr><th>Campaign</th><th>Class</th><th>ROAS Gap%</th><th>C ROAS</th><th>T ROAS</th><th>High Conf</th><th>&#916;Cost</th><th>mROAS</th></tr></thead><tbody>';
  rd.m2a_campaigns.forEach(c => {{
    m2aCamps += `<tr>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{c['Campaign original']}}</td>
      <td><span class="badge badge-${{c.M2a_Class === 'Lowered' ? 'red' : c.M2a_Class === 'Raised' ? 'green' : c.M2a_Class === 'Neutral' ? 'blue' : 'orange'}}">${{c.M2a_Class}}</span></td>
      <td>${{c.roas_gap_pct !== null ? c.roas_gap_pct.toFixed(1) + '%' : '—'}}</td>
      <td>${{fmt(c.C_ROAS,'x')}}</td><td>${{fmt(c.T_ROAS,'x')}}</td>
      <td>${{c.high_conf ? 'Yes' : 'No'}}</td>
      <td class="${{deltaClass(c.D_Costs,true)}}">${{fmt(c.D_Costs,'$d')}}</td>
      <td class="${{mroasClass(c.mROAS)}}">${{fmt(c.mROAS,'mroas')}}</td></tr>`;
  }});
  m2aCamps += '</tbody></table>';

  // Method 2b
  let m2bTbl = '<table><thead><tr><th>Bucket</th><th>Observations</th><th>&#916;Cost</th><th>&#916;M1VFM</th><th>mROAS</th></tr></thead><tbody>';
  rd.m2b_summary.forEach(r => {{
    m2bTbl += `<tr><td>${{r.Bucket}}</td><td>${{r.N_obs}}</td>
      <td class="${{deltaClass(r.D_Costs,true)}}">${{fmt(r.D_Costs,'$d')}}</td>
      <td class="${{deltaClass(r.D_M1VFM)}}">${{fmt(r.D_M1VFM,'$d')}}</td>
      <td class="${{mroasClass(r.mROAS)}}">${{fmt(r.mROAS,'mroas')}}</td></tr>`;
  }});
  m2bTbl += '</tbody></table>';

  // Method 2b consistency
  let consTbl = '';
  if (rd.m2b_consistency.length > 0) {{
    consTbl = '<table><thead><tr><th>Campaign</th><th>Lowered</th><th>Neutral</th><th>Raised</th><th>Total</th><th>Dominant</th></tr></thead><tbody>';
    rd.m2b_consistency.forEach(c => {{
      consTbl += `<tr>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{c['Campaign original']}}</td>
        <td>${{c.Lowered || 0}}</td><td>${{c.Neutral || 0}}</td><td>${{c.Raised || 0}}</td>
        <td>${{c.Total}}</td><td>${{c.Dominant}}</td></tr>`;
    }});
    consTbl += '</tbody></table>';
  }}

  return `
    <div class="callout blue"><strong>Supplementary Analysis.</strong> Method 2 classifies campaigns by observed ROAS gap rather than arm assignment. It does not compete with Method 1 — it provides an alternative lens for interpretation.</div>
    <div class="section-title">Method 2a: ROAS-Based Campaign Classification</div>
    <div class="card">${{m2aTbl}}</div>
    <div style="height:12px"></div>
    <div class="card table-wrap" style="max-height:400px;">${{m2aCamps}}</div>
    <div class="section-title">Method 2b: Daily x Campaign Classification</div>
    <div class="card">${{m2bTbl}}</div>
    ${{consTbl ? '<div class="section-title">Campaign Consistency (Method 2b)</div><div class="card table-wrap" style="max-height:400px;">' + consTbl + '</div>' : ''}}
    <div class="section-title">Method 2b Cumulative mROAS by Bucket</div>
    <div class="chart-container"><canvas id="m2bChart"></canvas></div>
  `;
}}

function initMethod2Charts(rd) {{
  // Simple bar chart of bucket mROAS
  const ctx = document.getElementById('m2bChart');
  if (!ctx) return;
  const labels = rd.m2b_summary.map(r => r.Bucket);
  const vals = rd.m2b_summary.map(r => r.mROAS);
  const colors = vals.map(v => v >= 0.80 ? '#10b981' : (v > 0 ? '#f59e0b' : '#ef4444'));
  const c = new Chart(ctx, {{
    type: 'bar',
    data: {{ labels, datasets: [{{ label: 'mROAS', data: vals, backgroundColor: colors, borderRadius: 6 }}] }},
    options: chartOpts('Method 2b: mROAS by Classification Bucket')
  }});
  chartInstances.push(c);
}}

// ── Tab 6: tROAS & Budget Changes ──
function renderChanges(rd) {{
  // Mid-test tROAS changes
  const mt = CE.mid_test_troas.filter(r => {{
    // Filter by current region's campaigns
    return rd.campaigns.some(c => c['Campaign original'] === r['Campaign original']);
  }});

  let mtTbl = '<table><thead><tr><th>Campaign</th><th>Arm</th><th>Date</th><th>Old tROAS</th><th>New tROAS</th><th>Change</th></tr></thead><tbody>';
  mt.forEach(r => {{
    const delta = r.new_roas_value - r.old_roas_value;
    mtTbl += `<tr>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{r.campaign_name}}</td>
      <td>${{r.Arm || '—'}}</td><td>${{r.change_date}}</td>
      <td>${{Number(r.old_roas_value).toFixed(2)}}</td><td>${{Number(r.new_roas_value).toFixed(2)}}</td>
      <td class="${{delta > 0 ? 'pos' : 'neg'}}">${{delta > 0 ? '+' : ''}}${{delta.toFixed(2)}}</td></tr>`;
  }});
  mtTbl += '</tbody></table>';

  // Budget changes
  const bc = CE.budget_changes.filter(r => {{
    return rd.campaigns.some(c => c['Campaign original'] === r['Campaign original']);
  }});
  let bcTbl = '';
  if (bc.length > 0) {{
    bcTbl = '<table><thead><tr><th>Campaign</th><th>Arm</th><th>Date</th><th>Old Budget</th><th>New Budget</th><th>Change</th></tr></thead><tbody>';
    bc.forEach(r => {{
      const delta = r.new_budget_amount - r.old_budget_amount;
      bcTbl += `<tr>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{r.campaign_name}}</td>
        <td>${{r.Arm || '—'}}</td><td>${{r.change_date}}</td>
        <td>${{fmt(r.old_budget_amount,'$')}}</td><td>${{fmt(r.new_budget_amount,'$')}}</td>
        <td class="${{delta > 0 ? 'pos' : 'neg'}}">${{fmt(delta,'$d')}}</td></tr>`;
    }});
    bcTbl += '</tbody></table>';
  }}

  // Effective tROAS timeline
  const timeline = CE.pair_troas_timeline.filter(r => {{
    return rd.campaigns.some(c => c['Campaign original'] === r['Campaign original']);
  }});

  let tlTbl = '';
  if (timeline.length > 0) {{
    // Group by campaign original
    const camps = [...new Set(timeline.map(r => r['Campaign original']))].sort();
    tlTbl = '<table><thead><tr><th>Campaign</th><th>Date</th><th>Ctrl tROAS</th><th>Treat tROAS</th><th>Spread</th></tr></thead><tbody>';
    camps.slice(0, 20).forEach(camp => {{
      const rows = timeline.filter(r => r['Campaign original'] === camp);
      rows.forEach((r, i) => {{
        const spread = (r.ctrl_troas || 0) - (r.treat_troas || 0);
        tlTbl += `<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{i === 0 ? camp : ''}}</td>
          <td>${{r.date}}</td>
          <td>${{r.ctrl_troas ? Number(r.ctrl_troas).toFixed(2) : '—'}}</td>
          <td>${{r.treat_troas ? Number(r.treat_troas).toFixed(2) : '—'}}</td>
          <td>${{spread.toFixed(2)}}</td></tr>`;
      }});
    }});
    tlTbl += '</tbody></table>';
  }}

  return `
    <div class="callout ${{mt.length > 0 ? 'red' : 'green'}}">
      <strong>${{mt.length > 0 ? 'Warning: ' + mt.length + ' tROAS changes detected during post-LP period.' : 'No mid-test tROAS disruptions for this region.'}}</strong>
      ${{mt.length > 0 ? ' These changes alter the test conditions and may confound results.' : ''}}
      Stable campaigns: ${{CE.stable_count}} | Disrupted: ${{CE.disrupted_count}}
    </div>
    <div class="section-title">Mid-Test tROAS Changes (Post-LP)</div>
    <div class="card table-wrap" style="max-height:400px;">${{mtTbl}}</div>
    ${{bcTbl ? '<div class="section-title">Budget Changes During Test</div><div class="card table-wrap" style="max-height:300px;">' + bcTbl + '</div>' : '<div class="callout blue">No budget changes detected for this region during the test period.</div>'}}
    ${{tlTbl ? '<div class="section-title">Effective tROAS Timeline (Post-LP, first 20 campaigns)</div><div class="card table-wrap" style="max-height:500px;">' + tlTbl + '</div>' : ''}}
  `;
}}

// ── Tab 7: AI Commentary ──
function renderCommentary(rd) {{
  const p = rd.portfolio;
  const mroas = p.mROAS;
  const dCost = p.D_Costs;
  const dM1 = p['D_M1 Vfm'];
  const region = currentRegion;
  const nCamps = rd.campaigns.length;
  const tr = rd.troas_ranges;

  // Program breakdown
  let progInsights = '';
  rd.programs.forEach(pr => {{
    const label = pr.mROAS >= 0.80 ? 'profitable' : (pr.mROAS > 0 ? 'marginally positive' : 'unprofitable');
    progInsights += `<li><strong>${{pr.Program}}</strong>: mROAS of ${{fmt(pr.mROAS,'mroas')}} (${{label}}). &#916;Cost ${{fmt(pr.D_Costs,'$d')}}, &#916;M1VFM ${{fmt(pr['D_M1 Vfm'],'$d')}}. ROAS shifted from ${{fmt(pr.C_ROAS,'x')}} to ${{fmt(pr.T_ROAS,'x')}}.</li>`;
  }});

  // Tier breakdown
  const tiers = rd.tier_counts;
  let tierText = '';
  ['Expected','Overspend','Efficient Pruning','Ambiguous'].forEach(t => {{
    const tc = tiers[t];
    if (tc.count > 0) {{
      tierText += `<li><strong>${{t}}</strong> (${{tc.count}} campaigns): &#916;Cost ${{fmt(tc.D_Costs,'$d')}}, aggregate mROAS ${{tc.mROAS !== null ? tc.mROAS.toFixed(2) : 'N/A'}}.</li>`;
    }}
  }});

  const verdictText = mroas >= 0.80 ?
    `The ${{region}} portfolio shows a positive mROAS of ${{fmt(mroas,'mroas')}}, exceeding the 0.80 breakeven threshold. This suggests that lowering tROAS targets for the treatment arm successfully generated profitable incremental volume. The treatment arm spent ${{fmt(dCost,'$d')}} more than control while generating ${{fmt(dM1,'$d')}} in additional M1VFM revenue.` :
    mroas > 0 ?
    `The ${{region}} portfolio mROAS of ${{fmt(mroas,'mroas')}} is positive but falls below the 0.80 breakeven threshold. While the looser tROAS targets did generate some incremental revenue (${{fmt(dM1,'$d')}}), the incremental cost (${{fmt(dCost,'$d')}}) was disproportionately high. The investment is technically positive but not meeting minimum profitability standards.` :
    `The ${{region}} portfolio mROAS of ${{fmt(mroas,'mroas')}} is negative, indicating that the looser tROAS targets destroyed value. Treatment campaigns spent ${{fmt(dCost,'$d')}} more but returned ${{fmt(dM1,'$d')}} in M1VFM — meaning the incremental spend generated negative returns.`;

  return `
    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Executive Narrative (${{region}})</div>
      <p style="line-height:1.8;color:var(--muted);font-size:0.9rem;margin-bottom:12px;">
        ${{verdictText}}
      </p>
      <p style="line-height:1.8;color:var(--muted);font-size:0.9rem;margin-bottom:12px;">
        The test covered ${{nCamps}} campaign pairs across ${{rd.programs.length}} programs over a {post_lp_days}-day post-learning period ({fmt_date(post_lp_start)}-{fmt_date_full(post_lp_end)}). Control tROAS targets ranged from ${{tr.ctrl_min ? Number(tr.ctrl_min).toFixed(2) : 'N/A'}} to ${{tr.ctrl_max ? Number(tr.ctrl_max).toFixed(2) : 'N/A'}}, while treatment targets ranged from ${{tr.treat_min ? Number(tr.treat_min).toFixed(2) : 'N/A'}} to ${{tr.treat_max ? Number(tr.treat_max).toFixed(2) : 'N/A'}}. The tROAS spread varied across campaigns, making per-campaign analysis essential.
      </p>
      <p style="line-height:1.8;color:var(--muted);font-size:0.9rem;">
        It is important to note that ${{CE.disrupted_count}} campaigns had their tROAS changed during the post-learning period, potentially confounding their results. Additionally, with only {post_lp_days} days of post-LP data, statistical power is limited — especially for low-volume campaigns.
      </p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Key Findings</div>
      <ol style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        <li>Portfolio mROAS for ${{region}} is <strong class="${{mroasClass(mroas)}}">${{fmt(mroas,'mroas')}}</strong> — ${{mroas >= 0.80 ? 'above' : 'below'}} the 0.80 breakeven threshold.</li>
        <li>Treatment arm ROAS (${{fmt(p.T_ROAS,'x')}}) vs Control (${{fmt(p.C_ROAS,'x')}}) — a ${{((p.T_ROAS - p.C_ROAS) / p.C_ROAS * 100).toFixed(1)}}% shift.</li>
        <li>Incremental cost: ${{fmt(dCost,'$d')}}. Incremental revenue: ${{fmt(dM1,'$d')}}.</li>
        <li>Program breakdown:<ul>${{progInsights}}</ul></li>
        <li>Tier distribution:<ul>${{tierText}}</ul></li>
        <li>${{CE.disrupted_count}} campaigns had mid-test tROAS changes — their results should be interpreted with caution.</li>
        <li>The {post_lp_days}-day post-LP window provides limited statistical power; extending to 14+ days would strengthen confidence.</li>
        <li>Method 2 (ROAS-based classification) provides a complementary view; check Tab 5 for where it agrees/disagrees with Method 1.</li>
      </ol>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Cross-Method Comparison</div>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;">
        <strong>Method 1 (Arm-Level Aggregate)</strong> directly compares Treatment vs Control at portfolio, program, and campaign levels. This is the primary method and most statistically robust as it uses the randomized arm assignment.<br><br>
        <strong>Method 2a (ROAS Classification)</strong> classifies campaigns by their observed ROAS gap, regardless of arm assignment. This captures whether Google's bidding algorithm actually produced different outcomes.<br><br>
        <strong>Method 2b (Daily x Campaign)</strong> decomposes into daily observations. It excludes zero-order days and can reveal whether the mROAS signal is consistent or driven by a few outlier days.
      </p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Risk Factors & Caveats</div>
      <ul style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        <li>Short test window ({post_lp_days} post-LP days) limits statistical confidence.</li>
        <li>Mid-test tROAS changes on ${{CE.disrupted_count}} campaigns may confound arm-level comparisons.</li>
        <li>Campaigns with |&#916;Cost| < $100 have unreliable mROAS estimates (flagged in campaign table).</li>
        <li>Weekend/weekday mix effects not controlled for.</li>
        <li>Seasonality and competitive dynamics not isolated.</li>
        <li>The test measures tROAS sensitivity, not a pure incrementality lift (no holdout arm).</li>
      </ul>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Recommendations</div>
      <ol style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        ${{mroas >= 0.80 ? `
        <li><strong>Scale selectively:</strong> Apply looser tROAS to "Expected" tier campaigns where mROAS > 0.80. Keep or tighten "Overspend" campaigns.</li>
        <li><strong>Extend the test:</strong> Run 7-14 more days for stronger statistical evidence before permanent changes.</li>
        <li><strong>Monitor closely:</strong> Set up daily mROAS tracking dashboards during the scaling phase.</li>
        ` : mroas > 0 ? `
        <li><strong>Moderate the approach:</strong> Consider a smaller tROAS reduction (e.g., 5% instead of 10%) to improve mROAS toward breakeven.</li>
        <li><strong>Focus on winners:</strong> Identify campaign subsets where mROAS exceeds 0.80 and scale those only.</li>
        <li><strong>Extend the test:</strong> {post_lp_days} days is insufficient — run 14+ days before making decisions.</li>
        ` : `
        <li><strong>Revert treatment targets:</strong> The negative mROAS suggests reverting to control tROAS levels immediately.</li>
        <li><strong>Investigate root causes:</strong> Determine why looser targets destroyed value — auction dynamics, audience quality, etc.</li>
        <li><strong>Consider smaller reductions:</strong> If retesting, try 3-5% tROAS reductions instead of 10%.</li>
        `}}
        <li><strong>Clean test conditions:</strong> For future tests, lock tROAS targets during the test period to avoid mid-test changes.</li>
        <li><strong>Segment analysis:</strong> Investigate by device, audience, geography if data available.</li>
      </ol>
    </div>

    <div class="card">
      <div class="section-title" style="margin-top:0;">Open Questions</div>
      <ul style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        <li>What is the long-term customer value beyond M1VFM? Would LTV-based mROAS change the verdict?</li>
        <li>Are there audience-level differences in response to tROAS changes?</li>
        <li>How do competitive auction dynamics (share of voice, CPC trends) affect the treatment response?</li>
        <li>Would a geo-based incrementality test provide more robust causal evidence?</li>
        <li>Can the "Ambiguous" tier campaigns be explained by external factors (promotions, seasonality)?</li>
      </ul>
    </div>
  `;
}}

// ── Tab 8: Info Sheet ──
function renderInfo(rd) {{
  let valTbl = '<table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>';
  VAL.forEach(v => {{
    valTbl += `<tr><td>${{v.check}}</td><td style="font-size:0.8rem;">${{v.result}}</td></tr>`;
  }});
  valTbl += '</tbody></table>';

  return `
    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Test Design</div>
      <table>
        <tr><td style="color:var(--muted);">Test Type</td><td>50:50 Campaign-Split Incrementality Test</td></tr>
        <tr><td style="color:var(--muted);">Control tROAS</td><td>BAU tROAS (varies by campaign, see change events)</td></tr>
        <tr><td style="color:var(--muted);">Treatment tROAS</td><td>~0.9x BAU (10% lower, varies by campaign)</td></tr>
        <tr><td style="color:var(--muted);">Full Test Period</td><td>{fmt_date(test_start)} - {fmt_date_full(test_end)} ({test_days} days)</td></tr>
        <tr><td style="color:var(--muted);">Learning Period</td><td>{fmt_date(test_start)} - {fmt_date(lp_end)} ({lp_days} days)</td></tr>
        <tr><td style="color:var(--muted);">Post-Learning Period</td><td>{fmt_date(post_lp_start)} - {fmt_date(post_lp_end)} ({post_lp_days} days) — primary analysis window</td></tr>
        <tr><td style="color:var(--muted);">NA Pairs</td><td>{pair_counts['NA']['total']} ({na_prog_parts})</td></tr>
        <tr><td style="color:var(--muted);">INTL Pairs</td><td>{pair_counts['INTL']['total']} ({intl_prog_parts})</td></tr>
        <tr><td style="color:var(--muted);">Breakeven mROAS</td><td>0.80</td></tr>
      </table>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Methodology</div>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;margin-bottom:12px;">
        <strong>Method 1 (Primary): Arm-Level Aggregate.</strong> Compare Control vs Treatment at portfolio, program, and campaign levels using post-LP data only. mROAS = &#916;M1VFM / &#916;Cost, where &#916; = Treatment minus Control. Campaigns classified into tiers based on &#916;Cost and &#916;M1VFM signs.
      </p>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;margin-bottom:12px;">
        <strong>Method 2a (Supplementary): ROAS-Based Classification.</strong> Classify each campaign by aggregate ROAS gap: >+3% = Raised, -3% to +3% = Neutral, <-3% = Lowered. Campaigns with <$3,000/arm are Low Confidence.
      </p>
      <p style="color:var(--muted);font-size:0.88rem;line-height:1.8;">
        <strong>Method 2b (Supplementary): Daily x Campaign.</strong> Each campaign-day is a separate observation. Same 3% ROAS gap threshold. Zero-order days excluded. Decomposes portfolio mROAS into daily components.
      </p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Tier Definitions</div>
      <table>
        <thead><tr><th>&#916;Cost</th><th>&#916;M1VFM</th><th>Tier</th><th>Interpretation</th></tr></thead>
        <tbody>
          <tr><td class="neg">+</td><td class="pos">+</td><td>${{tierBadge('Expected')}}</td><td>Spend more, earn more — the intended outcome</td></tr>
          <tr><td class="neg">+</td><td class="neg">-</td><td>${{tierBadge('Overspend')}}</td><td>Spend more but earn less — value destruction</td></tr>
          <tr><td class="pos">-</td><td class="neg">-</td><td>${{tierBadge('Efficient Pruning')}}</td><td>Spend less and earn less — efficient cutback</td></tr>
          <tr><td class="pos">-</td><td class="pos">+</td><td>${{tierBadge('Ambiguous')}}</td><td>Spend less but earn more — unexpected</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Metric Definitions</div>
      <table>
        <tr><td style="color:var(--muted);">mROAS</td><td>Marginal ROAS = &#916;M1VFM / &#916;Cost. Measures return on incremental spend.</td></tr>
        <tr><td style="color:var(--muted);">ROAS</td><td>Return on Ad Spend = M1VFM / Costs.</td></tr>
        <tr><td style="color:var(--muted);">M1VFM</td><td>Month 1 Value for Money — the primary revenue metric.</td></tr>
        <tr><td style="color:var(--muted);">CPC</td><td>Cost Per Click = Costs / Clicks.</td></tr>
        <tr><td style="color:var(--muted);">CTR</td><td>Click-Through Rate = Clicks / Impressions.</td></tr>
        <tr><td style="color:var(--muted);">CVR</td><td>Conversion Rate = Orders / Clicks.</td></tr>
        <tr><td style="color:var(--muted);">AOV</td><td>Average Order Value = M1VFM / Orders.</td></tr>
        <tr><td style="color:var(--muted);">Cumulative mROAS</td><td>Running &#931; &#916;M1VFM / Running &#931; &#916;Cost (not average of daily mROAS).</td></tr>
      </table>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Method 2 Parameters</div>
      <table>
        <tr><td style="color:var(--muted);">ROAS Gap Threshold</td><td>3% relative — campaigns with ROAS gap within +/-3% classified as Neutral</td></tr>
        <tr><td style="color:var(--muted);">Confidence Minimum</td><td>$3,000/arm over post-LP — campaigns below this are Low Confidence</td></tr>
        <tr><td style="color:var(--muted);">Breakeven mROAS</td><td>0.80 — minimum mROAS for incremental spend to be considered profitable</td></tr>
        <tr><td style="color:var(--muted);">Zero-Order Exclusion</td><td>Campaign-days with 0 orders in either arm excluded from Method 2b</td></tr>
      </table>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="section-title" style="margin-top:0;">Data Validation Results</div>
      ${{valTbl}}
    </div>

    <div class="card">
      <div class="section-title" style="margin-top:0;">Limitations & Caveats</div>
      <ul style="color:var(--muted);font-size:0.88rem;line-height:2;padding-left:20px;">
        <li>{post_lp_days}-day post-LP window provides limited statistical power, especially for low-volume campaigns.</li>
        <li>Mid-test tROAS changes on some campaigns may confound results.</li>
        <li>This is a tROAS sensitivity test, not a pure incrementality test (no holdout arm).</li>
        <li>NA and INTL are never combined — different markets may have fundamentally different dynamics.</li>
        <li>Campaigns with |&#916;Cost| < $100 have unreliable mROAS (flagged with &#9888;).</li>
        <li>Weekend/weekday effects and seasonality not controlled.</li>
        <li>Funnel metrics (CPC, CTR, CVR, AOV) computed from totals, not averaged across days.</li>
      </ul>
    </div>
  `;
}}

// Initial render
setRegion('NA');
</script>
</body>
</html>'''

# Write HTML
with open(HTML_OUT, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nHTML report saved to: {HTML_OUT}")
print(f"File size: {len(html)/1024:.0f} KB")
print("Done!")
