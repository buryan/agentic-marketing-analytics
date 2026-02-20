#!/usr/bin/env python3
"""Generate self-contained HTML dashboard for Groupon Organic SEO Performance Analysis."""

import csv
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'input', 'seo')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'seo-content-report.html')


def parse_num(s):
    """Parse a numeric string, removing commas and handling percentages."""
    if s is None or s == '' or s == 'N/A':
        return None
    s = str(s).strip()
    is_pct = s.endswith('%')
    s = s.replace('%', '').replace(',', '').replace('$', '')
    try:
        v = float(s)
        return v
    except ValueError:
        return None


def read_csv(filename):
    """Read a CSV file and return list of dicts."""
    path = os.path.join(DATA_DIR, filename)
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        all_rows = list(reader)
    return all_rows


def fmt_num(n, decimals=0):
    """Format number with commas."""
    if n is None:
        return 'N/A'
    if decimals == 0:
        return f"{int(round(n)):,}"
    return f"{n:,.{decimals}f}"


def fmt_pct(n, decimals=2):
    """Format as percentage."""
    if n is None:
        return 'N/A'
    return f"{n:+.{decimals}f}%" if n >= 0 else f"{n:.{decimals}f}%"


def fmt_pct_plain(n, decimals=2):
    """Format as percentage without sign."""
    if n is None:
        return 'N/A'
    return f"{n:.{decimals}f}%"


def delta_class(val, invert=False):
    """Return CSS class for delta value."""
    if val is None:
        return ''
    if invert:
        val = -val
    if val > 5:
        return 'pos'
    elif val < -5:
        return 'neg'
    else:
        return 'warn'


def badge_class(val, invert=False):
    """Return badge class for delta."""
    if val is None:
        return 'badge-blue'
    if invert:
        val = -val
    if val > 5:
        return 'badge-green'
    elif val < -5:
        return 'badge-red'
    else:
        return 'badge-orange'


# ============================================================
# LOAD AND PROCESS DATA
# ============================================================

# 1. Daily Overview
daily_raw = read_csv('Organic Daily Overview - Summary.csv')
daily_data = []
summary_28d = {}

for i, row in enumerate(daily_raw):
    if i == 0:
        # Row 0 is header + summary data
        # Parse summary: Last 28 days, Previous 28 days
        if len(row) > 7:
            summary_28d = {
                'last28_clicks': parse_num(row[7]) if len(row) > 7 else None,
                'last28_impressions': parse_num(row[8]) if len(row) > 8 else None,
                'last28_delta_pct': parse_num(row[9]) if len(row) > 9 else None,
                'prev28_clicks': parse_num(row[11]) if len(row) > 11 else None,
                'prev28_impressions': parse_num(row[12]) if len(row) > 12 else None,
            }
        continue
    if i == 1 and len(row) > 7:
        # First data row also has summary
        summary_28d = {
            'last28_clicks': parse_num(row[7]) if len(row) > 7 else None,
            'last28_impressions': parse_num(row[8]) if len(row) > 8 else None,
            'last28_delta_pct': parse_num(row[9]) if len(row) > 9 else None,
            'prev28_clicks': parse_num(row[11]) if len(row) > 11 else None,
            'prev28_impressions': parse_num(row[12]) if len(row) > 12 else None,
        }
    date_str = row[0].strip() if row[0] else ''
    if not date_str:
        continue
    try:
        dt = datetime.strptime(date_str, '%m/%d/%Y')
    except ValueError:
        continue
    clicks = parse_num(row[1])
    impressions = parse_num(row[2])
    ctr_str = row[3].strip() if len(row) > 3 else ''
    ctr = parse_num(ctr_str)
    position = parse_num(row[4]) if len(row) > 4 else None
    if clicks is not None:
        daily_data.append({
            'date': dt.strftime('%Y-%m-%d'),
            'clicks': clicks,
            'impressions': impressions,
            'ctr': ctr,
            'position': position,
        })

daily_data.sort(key=lambda x: x['date'])

# Compute weekly aggregates
weekly_data = []
if daily_data:
    # Group by ISO week
    weeks = defaultdict(list)
    for d in daily_data:
        dt = datetime.strptime(d['date'], '%Y-%m-%d')
        week_key = dt.strftime('%G-W%V')
        weeks[week_key].append(d)
    for wk in sorted(weeks.keys()):
        days = weeks[wk]
        if len(days) < 3:  # skip incomplete weeks
            continue
        avg_clicks = sum(d['clicks'] for d in days) / len(days)
        avg_impressions = sum(d['impressions'] for d in days if d['impressions']) / max(1, len([d for d in days if d['impressions']]))
        avg_ctr = sum(d['ctr'] for d in days if d['ctr']) / max(1, len([d for d in days if d['ctr']]))
        avg_pos = sum(d['position'] for d in days if d['position']) / max(1, len([d for d in days if d['position']]))
        weekly_data.append({
            'week': wk,
            'start_date': days[0]['date'],
            'end_date': days[-1]['date'],
            'days': len(days),
            'avg_clicks': round(avg_clicks),
            'total_clicks': sum(d['clicks'] for d in days),
            'avg_impressions': round(avg_impressions),
            'total_impressions': sum(d['impressions'] for d in days if d['impressions']),
            'avg_ctr': round(avg_ctr, 2),
            'avg_position': round(avg_pos, 1),
        })

# Monthly aggregates
monthly_data = []
months = defaultdict(list)
for d in daily_data:
    month_key = d['date'][:7]
    months[month_key].append(d)
for mk in sorted(months.keys()):
    days = months[mk]
    avg_clicks = sum(d['clicks'] for d in days) / len(days)
    total_clicks = sum(d['clicks'] for d in days)
    avg_imp = sum(d['impressions'] for d in days if d['impressions']) / max(1, len([d for d in days if d['impressions']]))
    total_imp = sum(d['impressions'] for d in days if d['impressions'])
    avg_ctr = sum(d['ctr'] for d in days if d['ctr']) / max(1, len([d for d in days if d['ctr']]))
    avg_pos = sum(d['position'] for d in days if d['position']) / max(1, len([d for d in days if d['position']]))
    monthly_data.append({
        'month': mk,
        'days': len(days),
        'avg_clicks': round(avg_clicks),
        'total_clicks': total_clicks,
        'avg_impressions': round(avg_imp),
        'total_impressions': total_imp,
        'avg_ctr': round(avg_ctr, 2),
        'avg_position': round(avg_pos, 1),
    })

# Compute MoM deltas
for i in range(1, len(monthly_data)):
    prev = monthly_data[i - 1]
    curr = monthly_data[i]
    if prev['total_clicks'] > 0:
        curr['clicks_mom_pct'] = round((curr['total_clicks'] - prev['total_clicks']) / prev['total_clicks'] * 100, 1)
    else:
        curr['clicks_mom_pct'] = None
    if prev['total_impressions'] > 0:
        curr['imp_mom_pct'] = round((curr['total_impressions'] - prev['total_impressions']) / prev['total_impressions'] * 100, 1)
    else:
        curr['imp_mom_pct'] = None
if monthly_data:
    monthly_data[0]['clicks_mom_pct'] = None
    monthly_data[0]['imp_mom_pct'] = None


# 2. Category Performance
cat_raw = read_csv('Category performance - YoY Sub Page Type KPI Summary (2).csv')
cat_data = []
for i, row in enumerate(cat_raw):
    if i < 3:  # Skip header rows
        continue
    if len(row) < 20:
        continue
    page_type = row[0].strip() if row[0] else ''
    sub_type = row[1].strip() if row[1] else ''
    if not page_type:
        continue
    cat_data.append({
        'page_type': page_type,
        'sub_type': sub_type,
        'uv_2026': parse_num(row[2]),
        'uv_yoy_2026': parse_num(row[3]),
        'orders_2026': parse_num(row[4]),
        'orders_yoy_2026': parse_num(row[5]),
        'margin_2026': parse_num(row[6]),
        'margin_yoy_2026': parse_num(row[7]),
        'uv_2025': parse_num(row[8]),
        'uv_yoy_2025': parse_num(row[9]),
        'orders_2025': parse_num(row[10]),
        'orders_yoy_2025': parse_num(row[11]),
        'margin_2025': parse_num(row[12]),
        'margin_yoy_2025': parse_num(row[13]),

        'uv_total': parse_num(row[20]) if len(row) > 20 else None,
        'orders_total': parse_num(row[22]) if len(row) > 22 else None,
        'margin_total': parse_num(row[24]) if len(row) > 24 else None,
    })


# 3. Pages
pages_raw = read_csv('Pages.csv')
pages_data = []
for i, row in enumerate(pages_raw):
    if i == 0:
        continue
    if len(row) < 9:
        continue
    url = row[0].strip()
    clicks_curr = parse_num(row[1])
    clicks_prev = parse_num(row[2])
    imp_curr = parse_num(row[3])
    imp_prev = parse_num(row[4])
    ctr_curr = parse_num(row[5])
    ctr_prev = parse_num(row[6])
    pos_curr = parse_num(row[7])
    pos_prev = parse_num(row[8])

    # Classify page type from URL
    page_type = 'other'
    if '/deals/' in url:
        page_type = 'deals'
    elif '/local/' in url:
        page_type = 'local'
    elif '/coupons/' in url:
        page_type = 'coupons'
    elif '/biz/' in url:
        page_type = 'biz'
    elif '/articles/' in url:
        page_type = 'articles'
    elif url.rstrip('/').endswith('groupon.com'):
        page_type = 'home'

    click_delta = None
    click_delta_pct = None
    if clicks_curr is not None and clicks_prev is not None:
        click_delta = clicks_curr - clicks_prev
        if clicks_prev > 0:
            click_delta_pct = round((click_delta / clicks_prev) * 100, 1)

    pages_data.append({
        'url': url,
        'page_type': page_type,
        'clicks_curr': clicks_curr,
        'clicks_prev': clicks_prev,
        'click_delta': click_delta,
        'click_delta_pct': click_delta_pct,
        'imp_curr': imp_curr,
        'imp_prev': imp_prev,
        'ctr_curr': ctr_curr,
        'ctr_prev': ctr_prev,
        'pos_curr': pos_curr,
        'pos_prev': pos_prev,
    })


# 4. Queries
queries_raw = read_csv('Queries.csv')
queries_data = []
for i, row in enumerate(queries_raw):
    if i == 0:
        continue
    if len(row) < 9:
        continue
    query = row[0].strip()
    clicks_curr = parse_num(row[1])
    clicks_prev = parse_num(row[2])
    imp_curr = parse_num(row[3])
    imp_prev = parse_num(row[4])
    ctr_curr = parse_num(row[5])
    ctr_prev = parse_num(row[6])
    pos_curr = parse_num(row[7])
    pos_prev = parse_num(row[8])

    is_brand = 'groupon' in query.lower()

    click_delta = None
    click_delta_pct = None
    if clicks_curr is not None and clicks_prev is not None:
        click_delta = clicks_curr - clicks_prev
        if clicks_prev > 0:
            click_delta_pct = round((click_delta / clicks_prev) * 100, 1)

    # Determine if new (was 0, now has clicks)
    is_new = (clicks_prev is not None and clicks_prev == 0 and
              clicks_curr is not None and clicks_curr > 0)

    # Query category clustering
    q_lower = query.lower()
    category = 'other'
    if 'costco' in q_lower:
        category = 'costco'
    elif 'valvoline' in q_lower:
        category = 'valvoline'
    elif 'great wolf' in q_lower:
        category = 'great_wolf_lodge'
    elif 'chuck e cheese' in q_lower:
        category = 'chuck_e_cheese'
    elif 'slick city' in q_lower:
        category = 'slick_city'
    elif 'urban air' in q_lower:
        category = 'urban_air'
    elif 'king spa' in q_lower:
        category = 'king_spa'
    elif 'sam' in q_lower and 'club' in q_lower:
        category = 'sams_club'
    elif 'disney' in q_lower:
        category = 'disney'
    elif 'legoland' in q_lower:
        category = 'legoland'
    elif 'microsoft' in q_lower:
        category = 'microsoft'

    queries_data.append({
        'query': query,
        'is_brand': is_brand,
        'clicks_curr': clicks_curr,
        'clicks_prev': clicks_prev,
        'click_delta': click_delta,
        'click_delta_pct': click_delta_pct,
        'imp_curr': imp_curr,
        'imp_prev': imp_prev,
        'ctr_curr': ctr_curr,
        'ctr_prev': ctr_prev,
        'pos_curr': pos_curr,
        'pos_prev': pos_prev,
        'is_new': is_new,
        'category': category,
    })


# 5. Deal WoW Performance
deal_wow_raw = read_csv('Deal performance WoW 21_01 analysis - results-20260202-110335.csv')
deal_wow = []
for i, row in enumerate(deal_wow_raw):
    if i == 0:
        continue
    if len(row) < 10:
        continue
    deal_wow.append({
        'url': row[0].strip(),
        'query_segment': row[1].strip(),
        'avg_pos_w1': parse_num(row[2]),
        'avg_pos_w2': parse_num(row[3]),
        'position_delta': parse_num(row[4]),
        'clicks_w1': parse_num(row[5]),
        'clicks_w2': parse_num(row[6]),
        'clicks_delta': parse_num(row[7]),
        'impressions_w2': parse_num(row[8]),
        'rank_bucket': row[9].strip() if len(row) > 9 else '',
    })


# 6. Impressions Delta
imp_delta_raw = read_csv('impressions delta - results-20260202-114238.csv')
imp_delta = []
for i, row in enumerate(imp_delta_raw):
    if i == 0:
        continue
    if len(row) < 9:
        continue
    imp_delta.append({
        'url': row[0].strip(),
        'query_segment': row[1].strip(),
        'queries_w1': parse_num(row[2]),
        'queries_w2': parse_num(row[3]),
        'query_delta': parse_num(row[4]),
        'impressions_w1': parse_num(row[5]),
        'impressions_w2': parse_num(row[6]),
        'impression_delta': parse_num(row[7]),
        'query_delta_pct': parse_num(row[8]),
    })


# ============================================================
# COMPUTE DERIVED METRICS
# ============================================================

# Latest 28-day KPIs
last_28 = daily_data[:28] if len(daily_data) >= 28 else daily_data
last28_total_clicks = sum(d['clicks'] for d in last_28)
last28_total_impressions = sum(d['impressions'] for d in last_28 if d['impressions'])
last28_avg_ctr = sum(d['ctr'] for d in last_28 if d['ctr']) / max(1, len([d for d in last_28 if d['ctr']]))
last28_avg_position = sum(d['position'] for d in last_28 if d['position']) / max(1, len([d for d in last_28 if d['position']]))

# Use summary data from CSV if available
if summary_28d.get('last28_clicks'):
    last28_total_clicks = int(summary_28d['last28_clicks'])
if summary_28d.get('last28_impressions'):
    last28_total_impressions = int(summary_28d['last28_impressions'])
clicks_28d_delta_pct = summary_28d.get('last28_delta_pct', -12.87)

# Previous 28 days
prev28_total_clicks = int(summary_28d.get('prev28_clicks', 0)) if summary_28d.get('prev28_clicks') else None
prev28_total_impressions = int(summary_28d.get('prev28_impressions', 0)) if summary_28d.get('prev28_impressions') else None

impressions_28d_delta_pct = None
if prev28_total_impressions and prev28_total_impressions > 0:
    impressions_28d_delta_pct = round((last28_total_impressions - prev28_total_impressions) / prev28_total_impressions * 100, 2)

# Page type click share from Pages data
page_type_clicks = defaultdict(float)
total_page_clicks = 0
for p in pages_data:
    if p['clicks_curr'] is not None:
        page_type_clicks[p['page_type']] += p['clicks_curr']
        total_page_clicks += p['clicks_curr']

# Top pages by clicks
pages_sorted = sorted([p for p in pages_data if p['clicks_curr'] is not None],
                       key=lambda x: x['clicks_curr'], reverse=True)

# Biggest gainers and losers
pages_with_delta = [p for p in pages_data if p['click_delta'] is not None]
top_gainers = sorted(pages_with_delta, key=lambda x: x['click_delta'], reverse=True)[:20]
top_losers = sorted(pages_with_delta, key=lambda x: x['click_delta'])[:20]

# Brand vs Non-Brand queries
brand_queries = [q for q in queries_data if q['is_brand']]
nonbrand_queries = [q for q in queries_data if not q['is_brand']]
brand_clicks = sum(q['clicks_curr'] for q in brand_queries if q['clicks_curr'])
nonbrand_clicks = sum(q['clicks_curr'] for q in nonbrand_queries if q['clicks_curr'])
total_query_clicks = brand_clicks + nonbrand_clicks

# New queries (clicks > 100 in current, 0 in prior)
new_queries = [q for q in queries_data if q['is_new'] and q['clicks_curr'] and q['clicks_curr'] > 100]
new_queries.sort(key=lambda x: x['clicks_curr'], reverse=True)

# Lost queries (significant period-over-period decline)
lost_queries = sorted([q for q in queries_data if q['click_delta'] is not None and q['click_delta'] < -50],
                      key=lambda x: x['click_delta'])[:20]

# Deal WoW rank movement distribution
rank_buckets = defaultdict(int)
for d in deal_wow:
    bucket = d['rank_bucket']
    if bucket:
        rank_buckets[bucket] += 1

# Query category aggregation
query_cats = defaultdict(lambda: {'clicks_curr': 0, 'clicks_prev': 0, 'count': 0})
for q in queries_data:
    cat = q['category']
    if q['clicks_curr']:
        query_cats[cat]['clicks_curr'] += q['clicks_curr']
    if q['clicks_prev']:
        query_cats[cat]['clicks_prev'] += q['clicks_prev']
    query_cats[cat]['count'] += 1

# Category totals for page type performance
cat_totals = [c for c in cat_data if c['sub_type'] == 'Total' or c['sub_type'] == c['page_type']]
cat_subtypes = [c for c in cat_data if c['sub_type'] != 'Total' and c['sub_type'] != c['page_type']]

# First and last dates
first_date = daily_data[-1]['date'] if daily_data else 'N/A'
last_date = daily_data[0]['date'] if daily_data else 'N/A'

# ============================================================
# ZOOMED JAN-FEB 2026 ANALYSIS
# ============================================================
# Filter daily data to Dec 1 2025 - Feb 16 2026 for zoomed view
zoom_data = [d for d in daily_data if '2025-12-01' <= d['date'] <= '2026-02-16']

# Define analysis phases with event annotations
phases = [
    {'name': 'Pre-Core Update', 'start': '2025-12-01', 'end': '2025-12-10',
     'event': None, 'color': '#94a3b8'},
    {'name': 'Core Update Rolling', 'start': '2025-12-11', 'end': '2025-12-29',
     'event': 'Google Dec 2025 Core Update (Dec 11-29)', 'color': '#f59e0b'},
    {'name': 'Holiday / Core Settles', 'start': '2025-12-30', 'end': '2026-01-04',
     'event': 'New Year deal-seeking spike', 'color': '#06b6d4'},
    {'name': 'Post-Holiday + Algo Signals', 'start': '2026-01-05', 'end': '2026-01-11',
     'event': 'Unconfirmed ranking volatility ~Jan 6', 'color': '#a78bfa'},
    {'name': 'Stabilized Post-Algo', 'start': '2026-01-12', 'end': '2026-01-19',
     'event': 'MLK Day weekend (Jan 18-19)', 'color': '#3b82f6'},
    {'name': 'Pre-Storm Step-Down', 'start': '2026-01-20', 'end': '2026-01-22',
     'event': 'Step-down BEFORE storm — algo settling?', 'color': '#ec4899'},
    {'name': 'Winter Storm Fern', 'start': '2026-01-23', 'end': '2026-01-27',
     'event': 'Major winter storm across S/NE US', 'color': '#ef4444'},
    {'name': 'Post-Storm Recovery', 'start': '2026-01-28', 'end': '2026-02-01',
     'event': 'Gradual recovery begins', 'color': '#10b981'},
    {'name': 'February Baseline', 'start': '2026-02-02', 'end': '2026-02-16',
     'event': 'New structural baseline', 'color': '#3b82f6'},
]

# Compute phase averages
phase_stats = []
for phase in phases:
    phase_days = [d for d in zoom_data if phase['start'] <= d['date'] <= phase['end']]
    if not phase_days:
        continue
    # Exclude Christmas (Dec 24-25) from Pre-Core and Core Update averages
    filtered = [d for d in phase_days if d['date'] not in ('2025-12-24', '2025-12-25')]
    if not filtered:
        filtered = phase_days
    avg_clicks = sum(d['clicks'] for d in filtered) / len(filtered)
    avg_imp = sum(d['impressions'] for d in filtered if d['impressions']) / max(1, len([d for d in filtered if d['impressions']]))
    avg_ctr = sum(d['ctr'] for d in filtered if d['ctr']) / max(1, len([d for d in filtered if d['ctr']]))
    avg_pos = sum(d['position'] for d in filtered if d['position']) / max(1, len([d for d in filtered if d['position']]))
    phase_stats.append({
        'name': phase['name'],
        'start': phase['start'],
        'end': phase['end'],
        'event': phase['event'],
        'color': phase['color'],
        'days': len(filtered),
        'avg_clicks': round(avg_clicks),
        'avg_impressions': round(avg_imp),
        'avg_ctr': round(avg_ctr, 2),
        'avg_position': round(avg_pos, 1),
    })

# Compute deltas vs pre-core-update baseline
baseline_phase = phase_stats[0] if phase_stats else None
for ps in phase_stats:
    if baseline_phase and baseline_phase['avg_clicks'] > 0:
        ps['click_delta_vs_baseline'] = round((ps['avg_clicks'] - baseline_phase['avg_clicks']) / baseline_phase['avg_clicks'] * 100, 1)
    else:
        ps['click_delta_vs_baseline'] = None


# ============================================================
# GENERATE HTML
# ============================================================

def generate_html():
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Zoomed chart data (Dec 2025 - Feb 2026) — primary charts for this report
    zoom_dates = json.dumps([d['date'] for d in zoom_data])
    zoom_clicks = json.dumps([d['clicks'] for d in zoom_data])
    zoom_impressions = json.dumps([d['impressions'] for d in zoom_data])
    zoom_ctr = json.dumps([d['ctr'] for d in zoom_data])
    zoom_position = json.dumps([d['position'] for d in zoom_data])

    # Phase background annotations for chart
    zoom_annotations = {}
    for i, ps in enumerate(phase_stats):
        zoom_annotations[f'phase{i}'] = {
            'type': 'box',
            'xMin': ps['start'],
            'xMax': ps['end'],
            'backgroundColor': ps['color'] + '15',
            'borderColor': ps['color'] + '40',
            'borderWidth': 1,
            'label': {
                'display': True,
                'content': ps['name'],
                'position': 'start',
                'font': {'size': 9},
                'color': ps['color'],
            }
        }
    zoom_annotations_json = json.dumps(zoom_annotations)

    # Event line annotations
    event_lines = {
        'coreUpdateStart': {
            'type': 'line', 'xMin': '2025-12-11', 'xMax': '2025-12-11',
            'borderColor': '#f59e0b', 'borderWidth': 2, 'borderDash': [6, 3],
            'label': {'display': True, 'content': 'Core Update Starts', 'position': 'start',
                      'backgroundColor': '#f59e0b', 'font': {'size': 10}}
        },
        'coreUpdateEnd': {
            'type': 'line', 'xMin': '2025-12-29', 'xMax': '2025-12-29',
            'borderColor': '#f59e0b', 'borderWidth': 2, 'borderDash': [6, 3],
            'label': {'display': True, 'content': 'Core Update Ends', 'position': 'start',
                      'backgroundColor': '#f59e0b', 'font': {'size': 10}}
        },
        'algoSignals': {
            'type': 'line', 'xMin': '2026-01-06', 'xMax': '2026-01-06',
            'borderColor': '#a78bfa', 'borderWidth': 2, 'borderDash': [6, 3],
            'label': {'display': True, 'content': 'Ranking Volatility', 'position': 'start',
                      'backgroundColor': '#a78bfa', 'font': {'size': 10}}
        },
        'stormStart': {
            'type': 'line', 'xMin': '2026-01-23', 'xMax': '2026-01-23',
            'borderColor': '#ef4444', 'borderWidth': 2, 'borderDash': [6, 3],
            'label': {'display': True, 'content': 'Storm Starts', 'position': 'start',
                      'backgroundColor': '#ef4444', 'font': {'size': 10}}
        },
        'stormEnd': {
            'type': 'line', 'xMin': '2026-01-27', 'xMax': '2026-01-27',
            'borderColor': '#ef4444', 'borderWidth': 2, 'borderDash': [6, 3],
            'label': {'display': True, 'content': 'Storm Ends', 'position': 'start',
                      'backgroundColor': '#ef4444', 'font': {'size': 10}}
        },
    }
    event_lines_json = json.dumps(event_lines)

    # Scatter data for pages (top 200)
    scatter_data = []
    for p in pages_sorted[:200]:
        if p['pos_curr'] and p['ctr_curr'] and p['clicks_curr']:
            scatter_data.append({
                'x': round(p['pos_curr'], 1),
                'y': round(p['ctr_curr'], 2),
                'r': max(3, min(20, p['clicks_curr'] / 200)),
                'label': p['url'].replace('https://www.groupon.com', ''),
                'type': p['page_type'],
            })
    scatter_json = json.dumps(scatter_data)

    # Monthly chart data (filtered to Dec 2025 - Feb 2026)
    monthly_dec_feb_chart = [m for m in monthly_data if m['month'] in ('2025-12', '2026-01', '2026-02')]
    monthly_labels = json.dumps([m['month'] for m in monthly_dec_feb_chart])
    monthly_clicks = json.dumps([m['total_clicks'] for m in monthly_dec_feb_chart])
    monthly_impressions = json.dumps([m['total_impressions'] for m in monthly_dec_feb_chart])

    # Category UV data for chart
    cat_total_rows = [c for c in cat_data if c['sub_type'] == 'Total' or (c['page_type'] == c['sub_type'])]
    cat_chart_labels = json.dumps([c['page_type'] for c in cat_total_rows if c['page_type'] not in ('Total',)])
    cat_chart_uv_2025 = json.dumps([c['uv_2025'] for c in cat_total_rows if c['page_type'] not in ('Total',)])
    cat_chart_uv_2026 = json.dumps([c['uv_2026'] for c in cat_total_rows if c['page_type'] not in ('Total',)])

    # Page type click share
    pt_labels = json.dumps(list(page_type_clicks.keys()))
    pt_values = json.dumps(list(page_type_clicks.values()))

    # Brand vs Non-Brand pie
    brand_pie = json.dumps([brand_clicks, nonbrand_clicks])

    # Rank bucket chart
    rb_labels = json.dumps(list(rank_buckets.keys()))
    rb_values = json.dumps(list(rank_buckets.values()))

    # WoW comparison table (most recent complete week vs prior)
    recent_weeks = weekly_data[-2:] if len(weekly_data) >= 2 else weekly_data

    # ============================================================
    # HTML TEMPLATE
    # ============================================================

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEO Content Performance Report — Groupon</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
:root {{
  --bg: #0b0f19; --card: #111827; --border: #1e293b;
  --blue: #3b82f6; --green: #10b981; --red: #ef4444; --orange: #f59e0b;
  --purple: #a78bfa; --cyan: #06b6d4; --pink: #ec4899;
  --text: #e2e8f0; --muted: #94a3b8; --white: #fff;
}}
body {{ font-family: 'Space Grotesk', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
.header {{ padding: 20px 32px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 1.5rem; font-weight: 700; }}
.header .subtitle {{ color: var(--muted); font-size: 0.85rem; }}
.nav-bar {{ display: flex; gap: 8px; padding: 16px 32px; border-bottom: 1px solid var(--border); flex-wrap: wrap; align-items: center; }}
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
.g5 {{ grid-template-columns: repeat(5, 1fr); }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }}
.card h3 {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 8px; font-weight: 500; }}
.card .big {{ font-size: 1.8rem; font-weight: 700; font-family: 'SF Mono', 'Fira Code', monospace; }}
.card .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
.callout {{ padding: 16px 20px; border-radius: 8px; margin: 16px 0; border-left: 4px solid; }}
.callout.blue {{ background: rgba(59,130,246,0.1); border-color: var(--blue); }}
.callout.red {{ background: rgba(239,68,68,0.1); border-color: var(--red); }}
.callout.green {{ background: rgba(16,185,129,0.1); border-color: var(--green); }}
.callout.orange {{ background: rgba(245,158,11,0.1); border-color: var(--orange); }}
.callout.purple {{ background: rgba(167,139,250,0.1); border-color: var(--purple); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; font-family: 'SF Mono', 'Fira Code', monospace; }}
th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--muted);
  font-weight: 500; position: sticky; top: 0; background: var(--card); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.5px; z-index: 1; }}
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
.chart-container-lg {{ position: relative; height: 400px; background: var(--card); border-radius: 10px; border: 1px solid var(--border); padding: 16px; }}
.chart-container-sm {{ position: relative; height: 250px; background: var(--card); border-radius: 10px; border: 1px solid var(--border); padding: 16px; }}
.section-title {{ font-size: 1.1rem; font-weight: 600; margin: 24px 0 12px; }}
.section-title:first-child {{ margin-top: 0; }}
.finding-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; border-left: 4px solid; }}
.finding-card h4 {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 8px; }}
.finding-card p {{ font-size: 0.85rem; color: var(--muted); line-height: 1.6; }}
.status-indicator {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }}
.status-red {{ background: rgba(239,68,68,0.15); color: var(--red); }}
.status-green {{ background: rgba(16,185,129,0.15); color: var(--green); }}
.status-orange {{ background: rgba(245,158,11,0.15); color: var(--orange); }}
.url-cell {{ max-width: 350px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.78rem; }}
.insight-block {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 24px; margin-bottom: 16px; }}
.insight-block h3 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: var(--white); }}
.insight-block p, .insight-block li {{ font-size: 0.88rem; color: var(--muted); line-height: 1.7; }}
.insight-block ul {{ padding-left: 20px; }}
.insight-block li {{ margin-bottom: 6px; }}
.ice-table td:first-child {{ font-weight: 600; color: var(--white); }}
@media (max-width: 1200px) {{ .g4, .g5 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 768px) {{ .g2, .g3, .g4, .g5 {{ grid-template-columns: 1fr; }} .content {{ padding: 16px; }} }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Organic SEO Performance Report</h1>
    <div class="subtitle">Groupon | Dec 2025 – Feb 2026 | Algorithm Update & Weather Impact Analysis | Global</div>
  </div>
  <div class="subtitle">Generated {now}</div>
</div>

<div class="nav-bar">
  <button class="tab-btn active" onclick="setTab(0)">Exec Summary</button>
  <button class="tab-btn" onclick="setTab(1)">Daily Trends</button>
  <button class="tab-btn" onclick="setTab(2)">Page Types</button>
  <button class="tab-btn" onclick="setTab(3)">Top Pages</button>
  <button class="tab-btn" onclick="setTab(4)">Queries</button>
  <button class="tab-btn" onclick="setTab(5)">Deal Deep Dive</button>
  <button class="tab-btn" onclick="setTab(6)">AI Commentary</button>
  <button class="tab-btn" onclick="setTab(7)">Data Quality</button>
</div>

<div class="content">
"""

    # ============================================================
    # TAB 0: EXECUTIVE SUMMARY
    # ============================================================

    # Compute Dec-Feb scoped KPIs from phase_stats
    dec_baseline = phase_stats[0]['avg_clicks'] if phase_stats else 0
    feb_baseline = phase_stats[-1]['avg_clicks'] if phase_stats else 0
    dec_feb_decline_pct = round((feb_baseline - dec_baseline) / dec_baseline * 100, 1) if dec_baseline else 0
    storm_phase = next((ps for ps in phase_stats if ps['name'] == 'Winter Storm Fern'), None)
    prestorm_phase = next((ps for ps in phase_stats if ps['name'] == 'Pre-Storm Step-Down'), None)
    storm_vs_prestorm = round((storm_phase['avg_clicks'] - prestorm_phase['avg_clicks']) / prestorm_phase['avg_clicks'] * 100, 1) if storm_phase and prestorm_phase and prestorm_phase['avg_clicks'] else None

    # Dec avg CTR/Position
    dec_days = [d for d in zoom_data if d['date'] <= '2025-12-10']
    feb_days = [d for d in zoom_data if d['date'] >= '2026-02-02']
    dec_avg_ctr = sum(d['ctr'] for d in dec_days if d['ctr']) / max(1, len([d for d in dec_days if d['ctr']])) if dec_days else 0
    feb_avg_ctr = sum(d['ctr'] for d in feb_days if d['ctr']) / max(1, len([d for d in feb_days if d['ctr']])) if feb_days else 0
    dec_avg_pos = sum(d['position'] for d in dec_days if d['position']) / max(1, len([d for d in dec_days if d['position']])) if dec_days else 0
    feb_avg_pos = sum(d['position'] for d in feb_days if d['position']) / max(1, len([d for d in feb_days if d['position']])) if feb_days else 0

    html += f"""
<div class="tab-content active" id="tab0">
  <div class="section-title" style="margin-top:0;">Period Health: Dec 2025 – Feb 2026</div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
    <span class="status-indicator status-red">DECLINING — Algorithm update drove ~12-15% structural drop</span>
  </div>

  <div class="grid g4" style="margin-bottom:20px;">
    <div class="card">
      <h3>Pre-Update Baseline (Dec 1-10)</h3>
      <div class="big">{fmt_num(dec_baseline)}</div>
      <div class="sub">avg daily clicks</div>
    </div>
    <div class="card">
      <h3>Feb Baseline (Feb 2-16)</h3>
      <div class="big neg">{fmt_num(feb_baseline)}</div>
      <div class="sub"><span class="neg">{fmt_pct(dec_feb_decline_pct)}</span> vs pre-update</div>
    </div>
    <div class="card">
      <h3>CTR Shift</h3>
      <div class="big">{fmt_pct_plain(dec_avg_ctr)} → {fmt_pct_plain(feb_avg_ctr)}</div>
      <div class="sub">Dec early → Feb avg</div>
    </div>
    <div class="card">
      <h3>Position Shift</h3>
      <div class="big">{dec_avg_pos:.1f} → {feb_avg_pos:.1f}</div>
      <div class="sub">Improved (lower = better)</div>
    </div>
  </div>

  <div class="grid g3" style="margin-bottom:20px;">
    <div class="card">
      <h3>28-Day Clicks (Latest)</h3>
      <div class="big">{fmt_num(last28_total_clicks)}</div>
      <div class="sub"><span class="neg">{fmt_pct(clicks_28d_delta_pct) if clicks_28d_delta_pct else 'N/A'}</span> vs prior 28 days</div>
    </div>
    <div class="card">
      <h3>28-Day Impressions</h3>
      <div class="big">{fmt_num(last28_total_impressions)}</div>
      <div class="sub"><span class="{'pos' if impressions_28d_delta_pct and impressions_28d_delta_pct > 0 else 'neg'}">{fmt_pct(impressions_28d_delta_pct) if impressions_28d_delta_pct else 'N/A'}</span> vs prior 28 days</div>
    </div>
    <div class="card">
      <h3>Storm Impact (Jan 23-27)</h3>
      <div class="big warn">{fmt_pct(storm_vs_prestorm) if storm_vs_prestorm is not None else 'N/A'}</div>
      <div class="sub">vs pre-storm week — minimal</div>
    </div>
  </div>

  <div class="section-title">Key Events & Findings</div>
  <div class="grid g2" style="margin-bottom:20px;">
    <div class="finding-card" style="border-color: var(--orange);">
      <h4 style="color: var(--orange);">Google Dec 2025 Core Update (Dec 11-29)</h4>
      <p>Google's third core update of 2025 rolled out over 18 days. It emphasized topical authority, E-E-A-T, and first-hand experience — directly targeting deal/coupon aggregator content. Groupon's daily clicks dropped from a ~182K baseline to ~167K by February, a <strong>~12-15% structural decline</strong>. Position improved while CTR dropped — consistent with index pruning of weaker pages.</p>
    </div>
    <div class="finding-card" style="border-color: var(--red);">
      <h4 style="color: var(--red);">Winter Storm Fern (Jan 23-27)</h4>
      <p>Massive storm across Southern and Northeastern US caused -30% retail foot traffic and shifted consumers to essentials. However, organic search for deals/coupons proved <strong>weather-resilient</strong>: only ~2-3% temporary dip vs the already-depressed post-algo level. Traffic was already at ~158K before the storm started — the step-down on Jan 20-22 was algorithmic, not weather-driven.</p>
    </div>
    <div class="finding-card" style="border-color: var(--purple);">
      <h4 style="color: var(--purple);">January Ranking Volatility (~Jan 6)</h4>
      <p>Unconfirmed ranking shifts observed around Jan 6, possibly continued settling from the December core update. Increased weighting of place-based signals and topical authority. This coincided with the post-holiday normalization, making it difficult to isolate the exact algorithmic contribution.</p>
    </div>
    <div class="finding-card" style="border-color: var(--blue);">
      <h4 style="color: var(--blue);">Costco Deal Page Volatility</h4>
      <p>"Costco membership deal" surged to 5,552 clicks (+32,553% period-over-period), but the deal page lost 2,425 clicks WoW in the Jan 21-27 period. This pattern suggests event-driven demand spikes (Costco promotions) rather than sustainable organic growth — a risk if used as a baseline for planning.</p>
    </div>
  </div>

  <div class="callout blue">
    <strong>TL;DR — Dec 2025 to Feb 2026</strong>
    <ul style="margin-top:8px;padding-left:20px;color:var(--muted);line-height:1.8;">
      <li><strong>Google Dec 2025 Core Update</strong> is the primary driver: ~12-15% structural decline in daily organic clicks (182K → 167K)</li>
      <li><strong>Winter Storm Fern</strong> had minimal isolated impact (~2-3% dip) — organic deal search is not weather-sensitive</li>
      <li>The sharp step-down happened Jan 20-22, <strong>before</strong> the storm (Jan 23), confirming the algorithmic cause</li>
      <li>New February baseline: ~167K clicks/day — this is the structural level until the next algo shift or SEO intervention</li>
      <li>28-day totals: {fmt_num(last28_total_clicks)} clicks ({fmt_pct(clicks_28d_delta_pct)}), {fmt_num(last28_total_impressions)} impressions ({fmt_pct(impressions_28d_delta_pct)})</li>
    </ul>
  </div>
</div>
"""

    # ============================================================
    # TAB 1: DAILY TRENDS
    # ============================================================
    # Filter monthly data to Dec 2025 - Feb 2026
    monthly_dec_feb = [m for m in monthly_data if m['month'] in ('2025-12', '2026-01', '2026-02')]

    html += f"""
<div class="tab-content" id="tab1">
  <div class="section-title" style="margin-top:0;">Daily Clicks — Dec 2025 to Feb 2026 (with event annotations)</div>

  <div class="callout purple" style="margin-bottom:16px;">
    <strong>Key events in this period:</strong>
    <ul style="margin-top:8px;padding-left:20px;color:var(--muted);line-height:1.8;">
      <li><strong style="color:#f59e0b;">Google Dec 2025 Core Update</strong> — Rolled out Dec 11-29. Emphasized topical authority, E-E-A-T, and first-hand experience over generic content. Coupon/deal aggregator sites particularly vulnerable.</li>
      <li><strong style="color:#a78bfa;">January 2026 Ranking Volatility</strong> — Unconfirmed ranking shifts ~Jan 6. Increased weighting of place-based signals and topical authority.</li>
      <li><strong style="color:#ef4444;">Winter Storm Fern (Jan 23-27)</strong> — Massive storm across Southern and Northeastern US. Foot traffic down ~30%, consumers shifted to essentials.</li>
    </ul>
  </div>

  <div class="chart-container-lg" style="margin-bottom:20px;">
    <canvas id="zoomClicksChart"></canvas>
  </div>

  <div class="section-title">Daily Impressions — Dec 2025 to Feb 2026</div>
  <div class="chart-container-lg" style="margin-bottom:20px;">
    <canvas id="zoomImpChart"></canvas>
  </div>

  <div class="section-title">CTR & Position — Dec 2025 to Feb 2026</div>
  <div class="chart-container-lg" style="margin-bottom:20px;">
    <canvas id="zoomCtrPosChart"></canvas>
  </div>

  <div class="section-title">Phase-by-Phase Impact Analysis</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>Phase</th>
          <th>Period</th>
          <th>Event</th>
          <th>Days</th>
          <th>Avg Daily Clicks</th>
          <th>vs Baseline</th>
          <th>Avg Impressions</th>
          <th>Avg CTR</th>
          <th>Avg Position</th>
        </tr>
      </thead>
      <tbody>
"""
    for ps in phase_stats:
        delta_cls = delta_class(ps['click_delta_vs_baseline']) if ps['click_delta_vs_baseline'] is not None else ''
        html += f"""        <tr>
          <td style="font-weight:600;color:{ps['color']};">{ps['name']}</td>
          <td>{ps['start']} to {ps['end']}</td>
          <td style="font-size:0.75rem;max-width:200px;">{ps['event'] or '—'}</td>
          <td>{ps['days']}</td>
          <td>{fmt_num(ps['avg_clicks'])}</td>
          <td class="{delta_cls}">{fmt_pct(ps['click_delta_vs_baseline']) if ps['click_delta_vs_baseline'] is not None else '—'}</td>
          <td>{fmt_num(ps['avg_impressions'])}</td>
          <td>{fmt_pct_plain(ps['avg_ctr'])}</td>
          <td>{ps['avg_position']}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>

  <div class="grid g2" style="margin-bottom:20px;">
    <div class="finding-card" style="border-color: var(--orange);">
      <h4 style="color: var(--orange);">Google Algorithm Impact: ~12-15% Structural Decline</h4>
      <p>The December 2025 core update completed Dec 29, but its ranking effects propagated through January. Pre-update baseline was ~182K clicks/day. By mid-January, clicks stabilized at ~180K (-1%). Then a sharp step-down to ~158K occurred Jan 20-22 — <strong>before</strong> the winter storm — suggesting a delayed algorithmic impact or post-MLK normalization compounded by algo settling. February stabilized at ~167K, representing a <strong>~12-15% structural decline</strong> from the pre-update baseline.</p>
      <p style="margin-top:8px;">The update's emphasis on topical authority and first-hand experience particularly impacts deal aggregator sites like Groupon, which rely on breadth rather than depth of content. Position improved (10→9) while CTR dropped (2.0%→1.8%), consistent with index pruning of weaker pages.</p>
    </div>
    <div class="finding-card" style="border-color: var(--red);">
      <h4 style="color: var(--red);">Winter Storm Impact: Minimal (~2-3% temporary)</h4>
      <p>Winter Storm Fern (Jan 23-27) hit when organic traffic was <strong>already depressed</strong> from the algorithm update. Storm-period clicks averaged ~158K/day vs ~163K/day in the pre-storm step-down (Jan 20-22) — only a ~3% additional dip. The storm did not cause a dramatic drop in organic search behavior for deal/coupon queries.</p>
      <p style="margin-top:8px;">This is consistent with research showing winter storms primarily impact <strong>physical retail foot traffic (-30%)</strong> and shift consumers to essentials — but organic search for deals/coupons is less weather-sensitive since it's inherently an online/mobile activity. The post-storm recovery to ~166K by late January confirms the storm was a minor overlay, not the primary cause of the decline.</p>
    </div>
  </div>

  <div class="callout blue" style="margin-bottom:20px;">
    <strong>Attribution Summary</strong>
    <ul style="margin-top:8px;padding-left:20px;color:var(--muted);line-height:1.8;">
      <li><strong>Seasonal normalization (Jan 1-4 → Jan 5-11):</strong> ~20% decline from New Year's deal-seeking peak — expected and normal</li>
      <li><strong>Google Dec 2025 Core Update + Jan signals:</strong> ~12-15% structural decline from pre-update baseline (~182K → ~158-167K). Primary driver of the sustained drop.</li>
      <li><strong>Winter Storm Fern (Jan 23-27):</strong> ~2-3% temporary dip, overlapping with and masked by the larger algorithmic impact. Minimal isolated effect on organic search.</li>
      <li><strong>Net new baseline (Feb 2026):</strong> ~167K clicks/day — this is the new structural level until the next algorithm shift or significant SEO intervention</li>
    </ul>
  </div>

  <div class="section-title">Monthly Summary</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>Month</th>
          <th>Days</th>
          <th>Total Clicks</th>
          <th>MoM %</th>
          <th>Avg Daily Clicks</th>
          <th>Total Impressions</th>
          <th>MoM %</th>
          <th>Avg CTR</th>
          <th>Avg Position</th>
        </tr>
      </thead>
      <tbody>
"""
    for m in monthly_dec_feb:
        mom_class = delta_class(m.get('clicks_mom_pct'))
        imp_mom_class = delta_class(m.get('imp_mom_pct'))
        html += f"""        <tr>
          <td>{m['month']}</td>
          <td>{m['days']}</td>
          <td>{fmt_num(m['total_clicks'])}</td>
          <td class="{mom_class}">{fmt_pct(m.get('clicks_mom_pct')) if m.get('clicks_mom_pct') is not None else '—'}</td>
          <td>{fmt_num(m['avg_clicks'])}</td>
          <td>{fmt_num(m['total_impressions'])}</td>
          <td class="{imp_mom_class}">{fmt_pct(m.get('imp_mom_pct')) if m.get('imp_mom_pct') is not None else '—'}</td>
          <td>{fmt_pct_plain(m['avg_ctr'])}</td>
          <td>{m['avg_position']}</td>
        </tr>
"""
    html += """      </tbody>
    </table>
  </div>

  <div class="section-title">Monthly Clicks Bar Chart</div>
  <div class="chart-container" style="margin-bottom:20px;">
    <canvas id="monthlyClicksChart"></canvas>
  </div>
</div>
"""

    # ============================================================
    # TAB 2: PAGE TYPE PERFORMANCE
    # ============================================================
    html += """
<div class="tab-content" id="tab2">
  <div class="section-title" style="margin-top:0;">Page Type Performance — Jan-Feb 2026 (Partial Period)</div>
  <div class="grid g2" style="margin-bottom:20px;">
    <div class="chart-container-sm">
      <canvas id="pageTypeClickShare"></canvas>
    </div>
    <div class="chart-container-sm">
      <canvas id="catUvChart"></canvas>
    </div>
  </div>

  <div class="callout orange" style="margin-bottom:16px;">
    <strong>Note:</strong> Category data covers Jan-Feb 2026 (~7 weeks). The period-over-period % change compares this partial window against the same partial window in the prior year, so large swings may reflect seasonality or partial-period bias. Use directionally, not as precise annual benchmarks.
  </div>

  <div class="section-title">Page Type Totals — UV, Orders, Margin (Jan-Feb 2026)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>Page Type</th>
          <th>UVs</th>
          <th>Period %</th>
          <th>Orders</th>
          <th>Order %</th>
          <th>Margin</th>
          <th>Margin %</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
"""
    # Filter to total rows only
    for c in cat_data:
        if c['sub_type'] != 'Total' and c['sub_type'] != c['page_type']:
            continue
        if c['page_type'] == 'Total':
            continue

        uv_yoy_class = delta_class(c['uv_yoy_2026'])
        ord_yoy_class = delta_class(c['orders_yoy_2026'])
        margin_yoy_class = delta_class(c['margin_yoy_2026'])

        # Status traffic light based on 2026 period change
        status = 'badge-red'
        status_text = 'DECLINING'
        if c['uv_yoy_2026'] is not None:
            if c['uv_yoy_2026'] > 5:
                status = 'badge-green'
                status_text = 'GROWING'
            elif c['uv_yoy_2026'] > -5:
                status = 'badge-orange'
                status_text = 'FLAT'

        html += f"""        <tr>
          <td style="font-weight:600;color:var(--white);">{c['page_type']}</td>
          <td>{fmt_num(c['uv_2026'])}</td>
          <td class="{uv_yoy_class}">{fmt_pct(c['uv_yoy_2026']) if c['uv_yoy_2026'] else '—'}</td>
          <td>{fmt_num(c['orders_2026'])}</td>
          <td class="{ord_yoy_class}">{fmt_pct(c['orders_yoy_2026']) if c['orders_yoy_2026'] else '—'}</td>
          <td>{fmt_num(c['margin_2026'])}</td>
          <td class="{margin_yoy_class}">{fmt_pct(c['margin_yoy_2026']) if c['margin_yoy_2026'] else '—'}</td>
          <td><span class="badge {status}">{status_text}</span></td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>

  <div class="section-title">Sub-Type Breakdown (Jan-Feb 2026)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>Page Type</th>
          <th>Sub-Type</th>
          <th>UVs</th>
          <th>Period %</th>
          <th>Orders</th>
          <th>Order %</th>
          <th>Margin</th>
          <th>Margin %</th>
        </tr>
      </thead>
      <tbody>
"""
    for c in cat_data:
        if c['sub_type'] == 'Total':
            continue
        if c['page_type'] == c['sub_type']:
            continue
        uv_class = delta_class(c['uv_yoy_2026'])
        ord_class = delta_class(c['orders_yoy_2026'])
        html += f"""        <tr>
          <td>{c['page_type']}</td>
          <td>{c['sub_type']}</td>
          <td>{fmt_num(c['uv_2026'])}</td>
          <td class="{uv_class}">{fmt_pct(c['uv_yoy_2026']) if c['uv_yoy_2026'] else '—'}</td>
          <td>{fmt_num(c['orders_2026'])}</td>
          <td class="{ord_class}">{fmt_pct(c['orders_yoy_2026']) if c['orders_yoy_2026'] else '—'}</td>
          <td>{fmt_num(c['margin_2026'])}</td>
          <td class="{delta_class(c['margin_yoy_2026'])}">{fmt_pct(c['margin_yoy_2026']) if c['margin_yoy_2026'] else '—'}</td>
        </tr>
"""
    html += """      </tbody>
    </table>
  </div>
</div>
"""

    # ============================================================
    # TAB 3: TOP PAGES ANALYSIS
    # ============================================================
    html += """
<div class="tab-content" id="tab3">
  <div class="section-title" style="margin-top:0;">Top 50 Pages by Clicks (Last 28 Days vs Same Period Last Year)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>URL</th>
          <th>Type</th>
          <th>Clicks (Curr)</th>
          <th>Clicks (Prev)</th>
          <th>Delta</th>
          <th>Delta %</th>
          <th>CTR Curr</th>
          <th>Pos Curr</th>
          <th>Pos Prev</th>
        </tr>
      </thead>
      <tbody>
"""
    for idx, p in enumerate(pages_sorted[:50]):
        delta_cls = delta_class(p['click_delta_pct'])
        page_badge = 'badge-blue'
        if p['page_type'] == 'deals':
            page_badge = 'badge-purple'
        elif p['page_type'] == 'coupons':
            page_badge = 'badge-green'
        elif p['page_type'] == 'local':
            page_badge = 'badge-orange'

        short_url = p['url'].replace('https://www.groupon.com', '')
        html += f"""        <tr>
          <td>{idx + 1}</td>
          <td class="url-cell" title="{p['url']}">{short_url}</td>
          <td><span class="badge {page_badge}">{p['page_type']}</span></td>
          <td>{fmt_num(p['clicks_curr'])}</td>
          <td>{fmt_num(p['clicks_prev'])}</td>
          <td class="{delta_cls}">{fmt_num(p['click_delta']) if p['click_delta'] is not None else '—'}</td>
          <td class="{delta_cls}">{fmt_pct(p['click_delta_pct']) if p['click_delta_pct'] is not None else '—'}</td>
          <td>{fmt_pct_plain(p['ctr_curr']) if p['ctr_curr'] else '—'}</td>
          <td>{p['pos_curr'] if p['pos_curr'] else '—'}</td>
          <td>{p['pos_prev'] if p['pos_prev'] else '—'}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>

  <div class="section-title">Position vs CTR — Top 200 Pages</div>
  <div class="chart-container-lg" style="margin-bottom:20px;">
    <canvas id="positionCtrScatter"></canvas>
  </div>

  <div class="grid g2" style="margin-bottom:20px;">
    <div>
      <div class="section-title">Top 20 Click Gainers (28-Day Period Comparison)</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>URL</th><th>Type</th><th>Curr</th><th>Prev</th><th>Delta</th></tr></thead>
          <tbody>
"""
    for p in top_gainers:
        short_url = p['url'].replace('https://www.groupon.com', '')
        html += f"""            <tr>
              <td class="url-cell" title="{p['url']}">{short_url}</td>
              <td><span class="badge badge-blue">{p['page_type']}</span></td>
              <td>{fmt_num(p['clicks_curr'])}</td>
              <td>{fmt_num(p['clicks_prev'])}</td>
              <td class="pos">+{fmt_num(p['click_delta'])}</td>
            </tr>
"""

    html += """          </tbody>
        </table>
      </div>
    </div>
    <div>
      <div class="section-title">Top 20 Click Losers (28-Day Period Comparison)</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>URL</th><th>Type</th><th>Curr</th><th>Prev</th><th>Delta</th></tr></thead>
          <tbody>
"""
    for p in top_losers:
        short_url = p['url'].replace('https://www.groupon.com', '')
        html += f"""            <tr>
              <td class="url-cell" title="{p['url']}">{short_url}</td>
              <td><span class="badge badge-blue">{p['page_type']}</span></td>
              <td>{fmt_num(p['clicks_curr'])}</td>
              <td>{fmt_num(p['clicks_prev'])}</td>
              <td class="neg">{fmt_num(p['click_delta'])}</td>
            </tr>
"""

    html += """          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="section-title">Page Type Distribution (from GSC Pages data)</div>
  <div class="grid g5" style="margin-bottom:20px;">
"""
    for pt, clicks in sorted(page_type_clicks.items(), key=lambda x: x[1], reverse=True):
        share = round(clicks / total_page_clicks * 100, 1) if total_page_clicks else 0
        html += f"""    <div class="card">
      <h3>{pt}</h3>
      <div class="big">{share}%</div>
      <div class="sub">{fmt_num(clicks)} clicks</div>
    </div>
"""
    html += """  </div>
</div>
"""

    # ============================================================
    # TAB 4: QUERY ANALYSIS
    # ============================================================
    html += f"""
<div class="tab-content" id="tab4">
  <div class="section-title" style="margin-top:0;">Brand vs Non-Brand Split</div>
  <div class="grid g3" style="margin-bottom:20px;">
    <div class="card">
      <h3>Brand Clicks (28d)</h3>
      <div class="big">{fmt_num(brand_clicks)}</div>
      <div class="sub">{round(brand_clicks / total_query_clicks * 100, 1) if total_query_clicks else 0}% of total</div>
    </div>
    <div class="card">
      <h3>Non-Brand Clicks (28d)</h3>
      <div class="big">{fmt_num(nonbrand_clicks)}</div>
      <div class="sub">{round(nonbrand_clicks / total_query_clicks * 100, 1) if total_query_clicks else 0}% of total</div>
    </div>
    <div class="chart-container-sm">
      <canvas id="brandPieChart"></canvas>
    </div>
  </div>

  <div class="section-title">Top 50 Queries by Clicks</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Query</th>
          <th>Brand</th>
          <th>Category</th>
          <th>Clicks (Curr)</th>
          <th>Clicks (Prev)</th>
          <th>Delta</th>
          <th>Delta %</th>
          <th>CTR Curr</th>
          <th>Pos Curr</th>
        </tr>
      </thead>
      <tbody>
"""
    queries_sorted = sorted([q for q in queries_data if q['clicks_curr'] is not None],
                            key=lambda x: x['clicks_curr'], reverse=True)
    for idx, q in enumerate(queries_sorted[:50]):
        delta_cls = delta_class(q['click_delta_pct'])
        brand_badge = 'badge-purple' if q['is_brand'] else 'badge-blue'
        brand_label = 'Brand' if q['is_brand'] else 'Non-Brand'
        html += f"""        <tr>
          <td>{idx + 1}</td>
          <td style="font-weight:500;">{q['query']}</td>
          <td><span class="badge {brand_badge}">{brand_label}</span></td>
          <td><span class="badge badge-orange">{q['category']}</span></td>
          <td>{fmt_num(q['clicks_curr'])}</td>
          <td>{fmt_num(q['clicks_prev'])}</td>
          <td class="{delta_cls}">{fmt_num(q['click_delta']) if q['click_delta'] is not None else '—'}</td>
          <td class="{delta_cls}">{fmt_pct(q['click_delta_pct']) if q['click_delta_pct'] is not None else '—'}</td>
          <td>{fmt_pct_plain(q['ctr_curr']) if q['ctr_curr'] else '—'}</td>
          <td>{q['pos_curr'] if q['pos_curr'] else '—'}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
"""

    # New queries
    html += """
  <div class="section-title">New Query Entrants (>100 clicks, 0 in prior period)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr><th>Query</th><th>Brand</th><th>Clicks</th><th>Impressions</th><th>CTR</th><th>Position</th></tr>
      </thead>
      <tbody>
"""
    for q in new_queries[:30]:
        brand_label = 'Brand' if q['is_brand'] else 'Non-Brand'
        html += f"""        <tr>
          <td>{q['query']}</td>
          <td><span class="badge {'badge-purple' if q['is_brand'] else 'badge-blue'}">{brand_label}</span></td>
          <td>{fmt_num(q['clicks_curr'])}</td>
          <td>{fmt_num(q['imp_curr'])}</td>
          <td>{fmt_pct_plain(q['ctr_curr']) if q['ctr_curr'] else '—'}</td>
          <td>{q['pos_curr'] if q['pos_curr'] else '—'}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
"""

    # Lost queries
    html += """
  <div class="section-title">Biggest Click Losers — Queries (28-Day Period Comparison)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr><th>Query</th><th>Brand</th><th>Clicks Curr</th><th>Clicks Prev</th><th>Delta</th><th>Delta %</th></tr>
      </thead>
      <tbody>
"""
    for q in lost_queries:
        html += f"""        <tr>
          <td>{q['query']}</td>
          <td><span class="badge {'badge-purple' if q['is_brand'] else 'badge-blue'}">{'Brand' if q['is_brand'] else 'Non-Brand'}</span></td>
          <td>{fmt_num(q['clicks_curr'])}</td>
          <td>{fmt_num(q['clicks_prev'])}</td>
          <td class="neg">{fmt_num(q['click_delta'])}</td>
          <td class="neg">{fmt_pct(q['click_delta_pct']) if q['click_delta_pct'] is not None else '—'}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
"""

    # Query category aggregation
    html += """
  <div class="section-title">Query Category Clusters</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr><th>Category</th><th>Queries</th><th>Clicks (Curr)</th><th>Clicks (Prev)</th><th>Delta</th><th>Delta %</th></tr>
      </thead>
      <tbody>
"""
    for cat_name, cat_vals in sorted(query_cats.items(), key=lambda x: x[1]['clicks_curr'], reverse=True):
        if cat_name == 'other':
            continue
        delta = cat_vals['clicks_curr'] - cat_vals['clicks_prev']
        delta_pct = round(delta / cat_vals['clicks_prev'] * 100, 1) if cat_vals['clicks_prev'] > 0 else None
        html += f"""        <tr>
          <td style="font-weight:600;color:var(--white);">{cat_name}</td>
          <td>{cat_vals['count']}</td>
          <td>{fmt_num(cat_vals['clicks_curr'])}</td>
          <td>{fmt_num(cat_vals['clicks_prev'])}</td>
          <td class="{delta_class(delta_pct)}">{fmt_num(delta)}</td>
          <td class="{delta_class(delta_pct)}">{fmt_pct(delta_pct) if delta_pct is not None else '—'}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
</div>
"""

    # ============================================================
    # TAB 5: DEAL PAGE DEEP DIVE
    # ============================================================
    html += """
<div class="tab-content" id="tab5">
  <div class="section-title" style="margin-top:0;">Deal Page Week-over-Week Performance (Jan 14-20 vs Jan 21-27, 2026)</div>
  <div class="grid g3" style="margin-bottom:20px;">
    <div class="chart-container-sm">
      <canvas id="rankBucketChart"></canvas>
    </div>
"""
    # Summary stats
    total_wow_deals = len(deal_wow)
    wow_declining = sum(1 for d in deal_wow if d['clicks_delta'] and d['clicks_delta'] < 0)
    wow_improving = sum(1 for d in deal_wow if d['clicks_delta'] and d['clicks_delta'] > 0)
    wow_total_click_delta = sum(d['clicks_delta'] for d in deal_wow if d['clicks_delta'])

    html += f"""
    <div class="card">
      <h3>Deal Pages Tracked</h3>
      <div class="big">{total_wow_deals}</div>
      <div class="sub">{wow_declining} declining, {wow_improving} improving</div>
    </div>
    <div class="card">
      <h3>Net Click Delta (WoW)</h3>
      <div class="big neg">{fmt_num(wow_total_click_delta)}</div>
      <div class="sub">Aggregate across all tracked deal pages</div>
    </div>
  </div>
"""

    # Top losing deal pages
    html += """
  <div class="section-title">Top 30 Deal Pages — Biggest WoW Click Declines</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>URL</th>
          <th>Segment</th>
          <th>Pos W1</th>
          <th>Pos W2</th>
          <th>Pos Delta</th>
          <th>Clicks W1</th>
          <th>Clicks W2</th>
          <th>Click Delta</th>
          <th>Imp W2</th>
          <th>Rank Bucket</th>
        </tr>
      </thead>
      <tbody>
"""
    deal_losers = sorted([d for d in deal_wow if d['clicks_delta'] is not None],
                         key=lambda x: x['clicks_delta'])[:30]
    for d in deal_losers:
        short_url = d['url'].replace('https://www.groupon.com', '')
        seg_badge = 'badge-purple' if d['query_segment'] == 'Brand' else 'badge-blue'
        pos_cls = 'neg' if d['position_delta'] and d['position_delta'] > 0.5 else ('pos' if d['position_delta'] and d['position_delta'] < -0.5 else '')
        html += f"""        <tr>
          <td class="url-cell" title="{d['url']}">{short_url}</td>
          <td><span class="badge {seg_badge}">{d['query_segment']}</span></td>
          <td>{f"{d['avg_pos_w1']:.1f}" if d['avg_pos_w1'] else '—'}</td>
          <td>{f"{d['avg_pos_w2']:.1f}" if d['avg_pos_w2'] else '—'}</td>
          <td class="{pos_cls}">{f"{d['position_delta']:+.2f}" if d['position_delta'] else '—'}</td>
          <td>{fmt_num(d['clicks_w1'])}</td>
          <td>{fmt_num(d['clicks_w2'])}</td>
          <td class="neg">{fmt_num(d['clicks_delta'])}</td>
          <td>{fmt_num(d['impressions_w2'])}</td>
          <td>{d['rank_bucket']}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
"""

    # Top gaining deal pages
    deal_gainers = sorted([d for d in deal_wow if d['clicks_delta'] is not None and d['clicks_delta'] > 0],
                          key=lambda x: x['clicks_delta'], reverse=True)[:20]
    html += """
  <div class="section-title">Top Deal Pages — WoW Click Gains</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>URL</th>
          <th>Segment</th>
          <th>Pos W1</th>
          <th>Pos W2</th>
          <th>Clicks W1</th>
          <th>Clicks W2</th>
          <th>Click Delta</th>
          <th>Rank Bucket</th>
        </tr>
      </thead>
      <tbody>
"""
    for d in deal_gainers:
        short_url = d['url'].replace('https://www.groupon.com', '')
        seg_badge = 'badge-purple' if d['query_segment'] == 'Brand' else 'badge-blue'
        html += f"""        <tr>
          <td class="url-cell" title="{d['url']}">{short_url}</td>
          <td><span class="badge {seg_badge}">{d['query_segment']}</span></td>
          <td>{f"{d['avg_pos_w1']:.1f}" if d['avg_pos_w1'] else '—'}</td>
          <td>{f"{d['avg_pos_w2']:.1f}" if d['avg_pos_w2'] else '—'}</td>
          <td>{fmt_num(d['clicks_w1'])}</td>
          <td>{fmt_num(d['clicks_w2'])}</td>
          <td class="pos">+{fmt_num(d['clicks_delta'])}</td>
          <td>{d['rank_bucket']}</td>
        </tr>
"""
    html += """      </tbody>
    </table>
  </div>
"""

    # Impression delta analysis
    html += """
  <div class="section-title">Query Volume & Impression Deltas (WoW)</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr>
          <th>URL</th>
          <th>Segment</th>
          <th>Queries W1</th>
          <th>Queries W2</th>
          <th>Query Delta</th>
          <th>Query %</th>
          <th>Imp W1</th>
          <th>Imp W2</th>
          <th>Imp Delta</th>
        </tr>
      </thead>
      <tbody>
"""
    for d in imp_delta[:30]:
        short_url = d['url'].replace('https://www.groupon.com', '')
        seg_badge = 'badge-purple' if d['query_segment'] == 'Brand' else 'badge-blue'
        q_cls = 'neg' if d['query_delta'] and d['query_delta'] < 0 else 'pos' if d['query_delta'] and d['query_delta'] > 0 else ''
        html += f"""        <tr>
          <td class="url-cell" title="{d['url']}">{short_url}</td>
          <td><span class="badge {seg_badge}">{d['query_segment']}</span></td>
          <td>{fmt_num(d['queries_w1'])}</td>
          <td>{fmt_num(d['queries_w2'])}</td>
          <td class="{q_cls}">{fmt_num(d['query_delta'])}</td>
          <td class="{q_cls}">{fmt_pct(d['query_delta_pct']) if d['query_delta_pct'] else '—'}</td>
          <td>{fmt_num(d['impressions_w1'])}</td>
          <td>{fmt_num(d['impressions_w2'])}</td>
          <td class="{'neg' if d['impression_delta'] and d['impression_delta'] < 0 else 'pos'}">{fmt_num(d['impression_delta'])}</td>
        </tr>
"""
    html += """      </tbody>
    </table>
  </div>
</div>
"""

    # ============================================================
    # TAB 6: AI COMMENTARY
    # ============================================================
    html += f"""
<div class="tab-content" id="tab6">
  <div class="insight-block" style="border-left:4px solid var(--orange);">
    <h3 style="color:var(--orange);">1. The Position Paradox — Dec 2025 to Feb 2026</h3>
    <p>Within this 11-week window, Groupon's average position improved from {dec_avg_pos:.1f} (early Dec) to {feb_avg_pos:.1f} (Feb), yet daily clicks fell {abs(dec_feb_decline_pct):.0f}% from ~{fmt_num(dec_baseline)} to ~{fmt_num(feb_baseline)}. Two primary factors explain this disconnect in the Dec-Feb period:</p>
    <ul>
      <li><strong>Google Dec 2025 Core Update (Dec 11-29):</strong> The update emphasized topical authority, E-E-A-T, and first-hand experience — directly penalizing deal aggregator content that lacks original reviews or unique value. Google likely pruned weaker Groupon pages from the index, leaving higher-ranking pages intact but reducing total impressions and clicks. Position improved as a mathematical artifact: surviving pages rank better on average.</li>
      <li><strong>Google AI Overviews Expansion:</strong> Throughout Dec-Feb, AI Overviews continued absorbing deal and coupon queries that previously drove clicks to Groupon. CTR dropped from {fmt_pct_plain(dec_avg_ctr)} to {fmt_pct_plain(feb_avg_ctr)} even as position improved, consistent with SERP features intercepting clicks.</li>
      <li><strong>Impression Base Contraction:</strong> Impressions were volatile through Dec-Feb. Fewer keyword queries triggering Groupon listings means higher average position on fewer, more competitive queries — but fewer total clicks.</li>
    </ul>
    <p style="margin-top:12px;"><strong>Net Result:</strong> The core update + AI Overviews created a ~12-15% structural step-down in daily clicks. The new February baseline (~{fmt_num(feb_baseline)}/day) reflects the post-update equilibrium.</p>
  </div>

  <div class="insight-block" style="border-left:4px solid var(--red);">
    <h3 style="color:var(--red);">2. Category-Level Observations (Jan-Feb 2026)</h3>
    <p>The Dec-Feb algorithm impact is not uniform across page types. Within this period:</p>
    <p style="margin-top:8px;"><strong>Most Impacted:</strong></p>
    <ul>
      <li><strong>Deals:</strong> The largest revenue contributor, with deal pages facing the full force of the Dec core update's emphasis on first-hand experience and topical authority. Aggregated deal content is exactly what the update targeted.</li>
      <li><strong>Articles:</strong> Content pages further deprioritized by the core update's E-E-A-T emphasis. Thin informational content continues to lose ranking signals.</li>
      <li><strong>Beauty & Spas:</strong> Historically strong vertical showing continued erosion — competitor sites with richer review content are gaining.</li>
    </ul>
    <p style="margin-top:12px;"><strong>Relative Resilience:</strong></p>
    <ul>
      <li><strong>Coupons:</strong> Previously a growth area, now declining in Jan-Feb 2026 — suggesting the Dec core update's impact caught up to this category as well.</li>
      <li><strong>Category pages (Things To Do, Travel):</strong> More defensible content with local and experiential focus — less vulnerable to the aggregator-targeting update.</li>
      <li><strong>Search pages:</strong> An established traffic stream, but sensitive to algorithm changes given thin content depth.</li>
    </ul>
  </div>

  <div class="insight-block" style="border-left:4px solid var(--blue);">
    <h3 style="color:var(--blue);">3. Query Landscape Shift (28-Day Period Comparison)</h3>
    <p><strong>Emerging Opportunities:</strong></p>
    <ul>
      <li><strong>Costco Membership Deals:</strong> "costco membership deal" surged from 17 to 5,552 clicks (+32,553%). Massive new query cluster — but volatile (deal page lost 2,425 clicks WoW in late Jan). Event-driven demand, not a stable baseline.</li>
      <li><strong>Valvoline:</strong> "valvoline coupon" went from 23 to 746 clicks. Growing non-brand category with high commercial intent.</li>
      <li><strong>Aquarium of the Pacific:</strong> 627 clicks from 0 — entirely new query. Local experience queries are a growth vector.</li>
    </ul>
    <p style="margin-top:12px;"><strong>Declining Queries:</strong></p>
    <ul>
      <li><strong>Great Wolf Lodge:</strong> "groupon great wolf lodge" down -706 clicks (-13%). Still #2 query but weakening.</li>
      <li><strong>Costco (generic):</strong> "costco membership" down -4,645 (-50.4%). Shift from generic to deal-specific variants.</li>
      <li><strong>King Spa:</strong> Down -777 clicks (-43.8%). Branded query erosion.</li>
      <li><strong>Sam's Club:</strong> Down -657 clicks (-49.9%). Club membership category losing ground.</li>
    </ul>
  </div>

  <div class="insight-block" style="border-left:4px solid var(--green);">
    <h3 style="color:var(--green);">4. Recommendations (ICE-Scored)</h3>
    <div class="table-wrap" style="margin-top:12px;">
      <table class="ice-table">
        <thead>
          <tr><th>Action</th><th>Impact</th><th>Confidence</th><th>Ease</th><th>ICE</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Optimize top deal pages for AI Overview inclusion (structured data, FAQ schema, featured snippet markup)</td>
            <td>9</td><td>7</td><td>6</td><td style="color:var(--green);font-weight:700;">22</td>
          </tr>
          <tr>
            <td>Double down on Costco/Valvoline content — create dedicated landing pages with comparison content</td>
            <td>8</td><td>8</td><td>7</td><td style="color:var(--green);font-weight:700;">23</td>
          </tr>
          <tr>
            <td>Audit and prune expired/thin deal pages to prevent index bloat and improve crawl efficiency</td>
            <td>7</td><td>7</td><td>5</td><td style="color:var(--green);font-weight:700;">19</td>
          </tr>
          <tr>
            <td>Investigate coupons page decline — identify specific algorithm changes or competitor gains in coupons SERP</td>
            <td>8</td><td>6</td><td>8</td><td style="color:var(--green);font-weight:700;">22</td>
          </tr>
          <tr>
            <td>Build local experience content (aquariums, zoos, theme parks) — emerging query cluster with less competition</td>
            <td>7</td><td>7</td><td>6</td><td style="color:var(--green);font-weight:700;">20</td>
          </tr>
          <tr>
            <td>Implement click-through optimization on high-impression, low-CTR pages (meta titles, descriptions A/B testing)</td>
            <td>6</td><td>8</td><td>7</td><td style="color:var(--green);font-weight:700;">21</td>
          </tr>
          <tr>
            <td>Monitor Google AI Overview coverage for top 50 queries — track where Groupon is/isn't cited</td>
            <td>5</td><td>9</td><td>9</td><td style="color:var(--green);font-weight:700;">23</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
"""

    # ============================================================
    # TAB 7: DATA QUALITY & METHODOLOGY
    # ============================================================
    html += f"""
<div class="tab-content" id="tab7">
  <div class="section-title" style="margin-top:0;">Data Sources</div>
  <div class="table-wrap" style="margin-bottom:20px;">
    <table>
      <thead>
        <tr><th>#</th><th>File</th><th>Rows</th><th>Date Range</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr><td>1</td><td>Organic Daily Overview - Summary.csv</td><td>{len(daily_data)}</td><td>{first_date} to {last_date} (analysis filtered to Dec 2025 – Feb 2026)</td><td>Daily clicks, impressions, CTR, position</td></tr>
        <tr><td>2</td><td>Category performance - YoY Sub Page Type KPI Summary (2).csv</td><td>{len(cat_data)}</td><td>Jan-Feb 2026 partial period (used in report)</td><td>UV, Orders, M1VFM by page type & sub-type</td></tr>
        <tr><td>3</td><td>Pages.csv</td><td>{len(pages_data)}</td><td>Last 28 days vs same period last year</td><td>Top pages with GSC metrics</td></tr>
        <tr><td>4</td><td>Queries.csv</td><td>{len(queries_data)}</td><td>Last 28 days vs same period last year</td><td>Top queries with GSC metrics</td></tr>
        <tr><td>5</td><td>Deal performance WoW 21_01 analysis.csv</td><td>{len(deal_wow)}</td><td>Jan 14-20 vs Jan 21-27, 2026</td><td>Deal page WoW position/clicks by segment</td></tr>
        <tr><td>6</td><td>impressions delta.csv</td><td>{len(imp_delta)}</td><td>Jan 14-20 vs Jan 21-27, 2026</td><td>Deal page query volume & impression deltas</td></tr>
        <tr><td>7</td><td>results-20260202-110142.csv</td><td>121</td><td>Jan 14-20 vs Jan 21-27, 2026</td><td>Same as #5 with more decimal precision (used for verification)</td></tr>
      </tbody>
    </table>
  </div>

  <div class="callout red" style="margin-bottom:20px;">
    <strong>Empty Files (not used in analysis):</strong>
    <ul style="margin-top:8px;padding-left:20px;">
      <li>Rest of the deals - Sheet1.csv (0 bytes)</li>
      <li>Top 500 deals query performance - Sheet1.csv (0 bytes)</li>
    </ul>
  </div>

  <div class="section-title">Limitations</div>
  <div class="callout orange" style="margin-bottom:20px;">
    <ul style="padding-left:20px;">
      <li><strong>No NA/INTL split:</strong> All data appears to be global/combined. Cannot isolate North America (~80% of business) from International (~20%).</li>
      <li><strong>No device breakdown:</strong> Cannot distinguish mobile vs desktop performance, which is critical given mobile SERP changes.</li>
      <li><strong>No raw GSC data:</strong> Data is pre-aggregated, limiting ability to slice by custom dimensions.</li>
      <li><strong>2026 partial year:</strong> Category performance covers only ~7 weeks (Jan-Feb 2026). Period-over-period % compares against the same partial window in the prior year — large swings may reflect seasonality. Use directionally.</li>
      <li><strong>No landing page revenue data:</strong> Cannot directly tie organic traffic changes to revenue impact beyond the category-level margin data.</li>
      <li><strong>WoW data covers one week transition only:</strong> Deal performance data only covers Jan 14-20 vs Jan 21-27 — a single week's movement may not represent trends.</li>
    </ul>
  </div>

  <div class="section-title">Methodology Notes</div>
  <div class="insight-block">
    <h3>Page Type Classification</h3>
    <p>Pages from the GSC data (Pages.csv) were classified by URL pattern:</p>
    <ul>
      <li><code>/deals/</code> → deals</li>
      <li><code>/local/</code> → local</li>
      <li><code>/coupons/</code> → coupons</li>
      <li><code>/biz/</code> → biz</li>
      <li><code>/articles/</code> → articles</li>
      <li>Root domain → home</li>
      <li>Everything else → other</li>
    </ul>
  </div>

  <div class="insight-block">
    <h3>Brand vs Non-Brand Classification</h3>
    <p>Queries containing "groupon" (case-insensitive) are classified as Brand. All others are Non-Brand. This is a simple heuristic — some brand-adjacent queries (e.g., misspellings, "gropon") may be missed.</p>
  </div>

  <div class="insight-block">
    <h3>Week-over-Week Computation</h3>
    <p>Weekly aggregates are computed from ISO week groupings of the daily overview data. Incomplete weeks (fewer than 3 days of data) are excluded. The WoW deal performance data compares Jan 14-20 vs Jan 21-27, 2026 as provided in the source files.</p>
  </div>

  <div class="insight-block">
    <h3>Traffic Light System</h3>
    <ul>
      <li><span class="badge badge-green">GREEN</span> — Improving (>+5%)</li>
      <li><span class="badge badge-orange">YELLOW</span> — Within +/- 5%</li>
      <li><span class="badge badge-red">RED</span> — Declining (>-5%)</li>
    </ul>
  </div>
</div>
"""

    # ============================================================
    # JAVASCRIPT
    # ============================================================
    html += f"""
</div>

<script>
// Tab switching
function setTab(idx) {{
  document.querySelectorAll('.tab-content').forEach((el, i) => {{
    el.classList.toggle('active', i === idx);
  }});
  document.querySelectorAll('.tab-btn').forEach((el, i) => {{
    el.classList.toggle('active', i === idx);
  }});
  // Trigger chart resize
  setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
}}

// Chart defaults
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#1e293b';
Chart.defaults.font.family = "'Space Grotesk', sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.boxWidth = 12;

// Monthly Clicks Bar Chart
new Chart(document.getElementById('monthlyClicksChart'), {{
  type: 'bar',
  data: {{
    labels: {monthly_labels},
    datasets: [{{
      label: 'Total Monthly Clicks',
      data: {monthly_clicks},
      backgroundColor: 'rgba(59,130,246,0.6)',
      borderColor: '#3b82f6',
      borderWidth: 1,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      y: {{ title: {{ display: true, text: 'Clicks' }} }}
    }}
  }}
}});

// Page Type Click Share (Doughnut)
new Chart(document.getElementById('pageTypeClickShare'), {{
  type: 'doughnut',
  data: {{
    labels: {pt_labels},
    datasets: [{{
      data: {pt_values},
      backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#a78bfa', '#ec4899', '#06b6d4', '#ef4444'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'right', labels: {{ font: {{ size: 10 }} }} }},
      title: {{ display: true, text: 'Click Share by Page Type (GSC 28d)' }}
    }}
  }}
}});

// Category UV Bar Chart
new Chart(document.getElementById('catUvChart'), {{
  type: 'bar',
  data: {{
    labels: {cat_chart_labels},
    datasets: [
      {{
        label: 'Jan-Feb 2026',
        data: {cat_chart_uv_2026},
        backgroundColor: 'rgba(59,130,246,0.6)',
        borderColor: '#3b82f6',
        borderWidth: 1,
      }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      title: {{ display: true, text: 'UVs by Page Type (Jan-Feb 2026)' }}
    }},
    scales: {{
      y: {{ title: {{ display: true, text: 'Unique Visitors' }} }}
    }}
  }}
}});

// Position vs CTR Scatter
const scatterData = {scatter_json};
const typeColors = {{
  'local': '#3b82f6',
  'deals': '#a78bfa',
  'coupons': '#10b981',
  'biz': '#f59e0b',
  'articles': '#ec4899',
  'other': '#94a3b8',
  'home': '#06b6d4',
}};

// Group scatter by type
const scatterByType = {{}};
scatterData.forEach(d => {{
  if (!scatterByType[d.type]) scatterByType[d.type] = [];
  scatterByType[d.type].push(d);
}});

new Chart(document.getElementById('positionCtrScatter'), {{
  type: 'bubble',
  data: {{
    datasets: Object.entries(scatterByType).map(([type, points]) => ({{
      label: type,
      data: points,
      backgroundColor: (typeColors[type] || '#94a3b8') + '80',
      borderColor: typeColors[type] || '#94a3b8',
      borderWidth: 1,
    }}))
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ title: {{ display: true, text: 'Average Position' }}, reverse: false }},
      y: {{ title: {{ display: true, text: 'CTR (%)' }} }}
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            const d = ctx.raw;
            return d.label + ' | Pos: ' + d.x + ' | CTR: ' + d.y + '%';
          }}
        }}
      }}
    }}
  }}
}});

// Brand vs Non-Brand Pie
new Chart(document.getElementById('brandPieChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Brand', 'Non-Brand'],
    datasets: [{{
      data: {brand_pie},
      backgroundColor: ['#a78bfa', '#3b82f6'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'bottom' }},
      title: {{ display: true, text: 'Brand vs Non-Brand Clicks' }}
    }}
  }}
}});

// Rank Bucket Chart
new Chart(document.getElementById('rankBucketChart'), {{
  type: 'bar',
  data: {{
    labels: {rb_labels},
    datasets: [{{
      label: 'Deal Pages',
      data: {rb_values},
      backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#a78bfa'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {{
      title: {{ display: true, text: 'Rank Movement Distribution (WoW)' }},
      legend: {{ display: false }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Number of Deal Pages' }} }}
    }}
  }}
}});

// ============================================================
// ZOOMED JAN-FEB 2026 CHARTS
// ============================================================
const zoomDates = {zoom_dates};
const zoomClicks = {zoom_clicks};
const zoomImpressions = {zoom_impressions};
const zoomCtr = {zoom_ctr};
const zoomPositions = {zoom_position};
const eventLines = {event_lines_json};

new Chart(document.getElementById('zoomClicksChart'), {{
  type: 'line',
  data: {{
    labels: zoomDates,
    datasets: [{{
      label: 'Daily Clicks',
      data: zoomClicks,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      fill: true,
      pointRadius: 3,
      pointHoverRadius: 6,
      borderWidth: 2,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ display: true, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
      y: {{ display: true, title: {{ display: true, text: 'Clicks' }},
            min: 120000, suggestedMax: 260000 }}
    }},
    plugins: {{
      annotation: {{
        annotations: {{
          ...eventLines,
          preUpdate: {{
            type: 'box', xMin: zoomDates[0], xMax: '2025-12-10',
            backgroundColor: 'rgba(148,163,184,0.08)', borderWidth: 0,
          }},
          coreUpdateBox: {{
            type: 'box', xMin: '2025-12-11', xMax: '2025-12-29',
            backgroundColor: 'rgba(245,158,11,0.08)', borderWidth: 0,
          }},
          stormBox: {{
            type: 'box', xMin: '2026-01-23', xMax: '2026-01-27',
            backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 0,
            label: {{ display: true, content: 'Winter Storm Fern', position: 'center',
                     font: {{ size: 11, weight: 'bold' }}, color: '#ef4444' }}
          }},
        }}
      }},
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            return 'Clicks: ' + ctx.parsed.y.toLocaleString();
          }}
        }}
      }}
    }}
  }}
}});

// Zoomed Impressions Chart
new Chart(document.getElementById('zoomImpChart'), {{
  type: 'line',
  data: {{
    labels: zoomDates,
    datasets: [{{
      label: 'Daily Impressions',
      data: zoomImpressions,
      borderColor: '#a78bfa',
      backgroundColor: 'rgba(167,139,250,0.08)',
      fill: true,
      pointRadius: 3,
      pointHoverRadius: 6,
      borderWidth: 2,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ display: true, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
      y: {{ display: true, title: {{ display: true, text: 'Impressions' }} }}
    }},
    plugins: {{
      annotation: {{
        annotations: {{
          ...eventLines,
          coreUpdateBox: {{
            type: 'box', xMin: '2025-12-11', xMax: '2025-12-29',
            backgroundColor: 'rgba(245,158,11,0.08)', borderWidth: 0,
          }},
          stormBox: {{
            type: 'box', xMin: '2026-01-23', xMax: '2026-01-27',
            backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 0,
          }},
        }}
      }},
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            return 'Impressions: ' + ctx.parsed.y.toLocaleString();
          }}
        }}
      }}
    }}
  }}
}});

new Chart(document.getElementById('zoomCtrPosChart'), {{
  type: 'line',
  data: {{
    labels: zoomDates,
    datasets: [
      {{
        label: 'CTR (%)',
        data: zoomCtr,
        borderColor: '#10b981',
        fill: false,
        pointRadius: 2,
        borderWidth: 2,
        tension: 0.3,
        yAxisID: 'y',
      }},
      {{
        label: 'Avg Position',
        data: zoomPositions,
        borderColor: '#f59e0b',
        fill: false,
        pointRadius: 2,
        borderWidth: 2,
        tension: 0.3,
        yAxisID: 'y1',
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ display: true, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
      y: {{ type: 'linear', display: true, position: 'left', title: {{ display: true, text: 'CTR (%)' }} }},
      y1: {{ type: 'linear', display: true, position: 'right', reverse: true,
             title: {{ display: true, text: 'Avg Position' }}, grid: {{ drawOnChartArea: false }} }}
    }},
    plugins: {{
      annotation: {{
        annotations: {{
          ...eventLines,
          stormBox: {{
            type: 'box', xMin: '2026-01-23', xMax: '2026-01-27',
            backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 0,
          }},
        }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""

    return html


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    html = generate_html()
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Report generated: {OUTPUT_FILE}")
    print(f"Daily data points: {len(daily_data)}")
    print(f"Pages analyzed: {len(pages_data)}")
    print(f"Queries analyzed: {len(queries_data)}")
    print(f"Deal WoW records: {len(deal_wow)}")
    print(f"Impression delta records: {len(imp_delta)}")
    print(f"Category records: {len(cat_data)}")
    print(f"Monthly periods: {len(monthly_data)}")
    print(f"Weekly periods: {len(weekly_data)}")
