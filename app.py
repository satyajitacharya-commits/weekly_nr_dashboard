import streamlit as st
import pandas as pd
import datetime
import calendar
import numpy as np
import os
import warnings
import plotly.express as px
import pytz
import plotly.graph_objects as go

warnings.filterwarnings('ignore', category=UserWarning)
st.set_page_config(layout="wide", page_title="Weekly Revenue Dashboard")

# ── Global CSS: force center-alignment in ALL st.dataframe tables ──
st.markdown("""
<style>
[data-testid="stDataFrame"] table thead tr th {
    text-align: center !important; font-weight: bold !important; }
[data-testid="stDataFrame"] table tbody tr td {
    text-align: center !important; }
[data-testid="stDataFrame"] th { text-align: center !important; }
[data-testid="stDataFrame"] td { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# FILE PATHS
# ============================================================
_HERE       = os.path.dirname(os.path.abspath(__file__))
MANUAL_FILE = os.path.join(_HERE, 'data_manual_adj.csv')
FILE_MM     = os.path.join(_HERE, 'Data_MM_Connect_Gross_Net.csv')
FILE_ISS    = os.path.join(_HERE, 'Data_Issuing_Gross_Net.csv')
FILE_BR_NET = os.path.join(_HERE, 'Data_Bridge_Other_Net.csv')
FILE_BR_GRS = os.path.join(_HERE, 'Data_Bridge_Other_Gross.csv')

# ============================================================
# COLOUR CONSTANTS
# ============================================================
CLR_GREEN = "#00b050"
CLR_RED   = "#ff0000"

# ============================================================
# FORECAST VERSION MAPPING
# ============================================================
FCST_DISPLAY_TO_KEY = {
    "Budget": "bud", "2+10": "2_10", "5+7": "5_7", "8+4": "8_4",
}
FCST_OPTIONS = list(FCST_DISPLAY_TO_KEY.keys())

# ============================================================
# PRODUCT CONSTANTS
# ============================================================
product_order = [
    "Connect", "Instant Payouts", "MCS & ICC", "Capital",
    "Issuing", "Bridge", "Faster Payouts", "Global Payouts",
    "Treasury", "Other BaaS Products", "Stretch", "Total Money Management"
]
prorate_prods = [
    "Bridge", "Faster Payouts", "Global Payouts",
    "Treasury", "Other BaaS Products", "Stretch"
]
prod_norm    = {k.lower(): k for k in product_order}
PROD_ALIASES = {
    "mass payouts":             "Global Payouts",
    "financial accounts":       "Treasury",
    "multicurrency settlement": "MCS & ICC",
}
FOOTER_PRODS = ['Total Money Management', 'Implied End of Month']

def normalise_product(raw_series):
    lower = raw_series.astype(str).str.strip().str.lower()
    return lower.map(PROD_ALIASES).fillna(lower.map(prod_norm)).fillna(
        raw_series.astype(str).str.strip())

PFMAP_NR = {
    "Connect": FILE_MM, "Instant Payouts": FILE_MM,
    "MCS & ICC": FILE_MM, "Capital": FILE_MM, "Issuing": FILE_ISS,
    "Bridge": FILE_BR_NET, "Faster Payouts": FILE_BR_NET,
    "Global Payouts": FILE_BR_NET, "Treasury": FILE_BR_NET,
    "Other BaaS Products": FILE_BR_NET,
}
PFMAP_GR = {
    "Connect": FILE_MM, "Instant Payouts": FILE_MM,
    "MCS & ICC": FILE_MM, "Capital": FILE_MM, "Issuing": FILE_ISS,
    "Bridge": FILE_BR_GRS, "Faster Payouts": FILE_BR_GRS,
    "Global Payouts": FILE_BR_GRS, "Treasury": FILE_BR_GRS,
    "Other BaaS Products": FILE_BR_GRS,
}

# ============================================================
# COLUMN HELPERS
# ============================================================
def _norm_cols(df):
    df.columns = (
        df.columns.astype(str)
          .str.strip()
          .str.lower()
          .str.replace(r'[^a-z0-9]+', '_', regex=True)
          .str.strip('_')
    )
    return df


def _getcol(df, *candidates):
    for name in candidates:
        if name in df.columns:
            return clean_money(df[name])
    stripped = {c.replace('_', '').replace(' ', ''): c for c in df.columns}
    for name in candidates:
        key = name.replace('_', '').replace(' ', '').lower()
        if key in stripped:
            return clean_money(df[stripped[key]])
    return pd.Series(0.0, index=df.index)


# ============================================================
# AUTO-DETECT LAST ACTUAL DATE
# ============================================================
def parse_dates_simple(col):
    raw   = col.astype(str)
    clean = raw.apply(lambda x: x.split(' GMT')[0].strip() if ' GMT' in x else x)
    return pd.to_datetime(clean, errors='coerce').dt.normalize()


def detect_last_actual_date():
    today = datetime.date.today()
    if not os.path.exists(FILE_MM):
        return today, False
    try:
        df = pd.read_csv(FILE_MM)
        _norm_cols(df)
        act_col, dat_col = 'daily_actual_net_revenue', 'reporting_date'
        if act_col not in df.columns or dat_col not in df.columns:
            return today, False
        df['_date'] = parse_dates_simple(df[dat_col])
        df['_act']  = pd.to_numeric(
            df[act_col].astype(str)
              .str.replace(r'[\$,()]', '', regex=True).str.strip(),
            errors='coerce').fillna(0).abs()
        has_data = df[(df['_act'] > 0) & (df['_date'].dt.date <= today)]
        if has_data.empty:
            return today, False
        return has_data['_date'].max().date(), True
    except Exception:
        return today, False


# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.header("Dashboard Settings")

forecast_display = st.sidebar.selectbox("Forecast Version", FCST_OPTIONS)
forecast_csv_key = FCST_DISPLAY_TO_KEY[forecast_display]
forecast_version = forecast_csv_key

_last_act_date, _csv_found_early = detect_last_actual_date()

as_of_date = st.sidebar.date_input(
    "As-Of Date",
    value=_last_act_date,
    help="Auto-set to the last date with actual data in Data_MM_Connect_Gross_Net.csv."
)

pt           = pytz.timezone('America/Los_Angeles')
refresh_time = datetime.datetime.now(pt).strftime("%Y-%m-%d %I:%M %p")
st.sidebar.markdown(f"**Last Sync:** `{refresh_time} PT`")

start_of_month = as_of_date.replace(day=1)
days_in_month  = calendar.monthrange(as_of_date.year, as_of_date.month)[1]
end_of_month   = as_of_date.replace(day=days_in_month)
prorate_factor = as_of_date.day / days_in_month

# ============================================================
# FORMATTING HELPERS
# ============================================================
def clean_money(series):
    if series.dtype == 'object':
        s   = series.astype(str).str.replace('$', '', regex=False)\
                                 .str.replace(',', '', regex=False).str.strip()
        neg = s.str.startswith('(') & s.str.endswith(')')
        s   = s.str.replace('(', '', regex=False).str.replace(')', '', regex=False)
        num = pd.to_numeric(s, errors='coerce').fillna(0)
        return np.where(neg, -num, num)
    return pd.to_numeric(series, errors='coerce').fillna(0)


def parse_dates(col):
    raw   = col.astype(str)
    clean = raw.apply(lambda x: x.split(' GMT')[0].strip() if ' GMT' in x else x)
    return pd.to_datetime(clean, errors='coerce').dt.normalize()


def fmt_m(v):
    try:
        f = float(v)
        return "$0.0M" if np.isnan(f) else f"${f:.1f}M"
    except: return "$0.0M"

def fmt_p(v):
    try:
        f = float(v)
        return "0.0%" if np.isnan(f) else f"{f*100:.1f}%"
    except: return "0.0%"

def fmt_p_na(v):
    try:
        f = float(v)
        if np.isnan(f): return "N/A"
        return f"{f*100:.1f}%"
    except: return "N/A"

def fmt_pct_complete(v):
    try:
        f = float(v) * 100
        return "0%" if np.isnan(f) else f"{f:.0f}%"
    except: return "0%"

def color_pct_var(val):
    try:
        if pd.isna(val) or val in ("", "N/A"): return ''
        s = str(val).replace('%', '').strip()
        v = float(s)
        if '%' not in str(val): v = v * 100
        if v < 0: return f'color:{CLR_RED}; font-weight:bold;'
        if v > 0: return f'color:{CLR_GREEN}; font-weight:bold;'
        return ''
    except: return ''

def color_dollar_var(val):
    try:
        if pd.isna(val) or val == "": return ''
        s = str(val).replace('$', '').replace('M', '').strip()
        v = float(s)
        if v < 0: return f'color:{CLR_RED}; font-weight:bold;'
        if v > 0: return f'color:{CLR_GREEN}; font-weight:bold;'
        return ''
    except: return ''

def hl_totals(row):
    if row.get('Product', '') in FOOTER_PRODS:
        return ['font-weight:bold; background-color:#f1f3f4;'] * len(row)
    return [''] * len(row)


TBL_STYLE = [
    dict(selector="th",
         props=[("text-align",       "center !important"),
                ("font-weight",      "bold"),
                ("font-size",        "13px"),
                ("white-space",      "nowrap"),
                ("background-color", "#f8f9fa")]),
    dict(selector="td",
         props=[("text-align",       "center !important"),
                ("font-size",        "12px"),
                ("min-width",        "75px"),
                ("padding",          "4px 8px")]),
    dict(selector="th.col_heading",
         props=[("text-align", "center !important")]),
    dict(selector="td.data",
         props=[("text-align", "center !important")]),
]

FMT_S1 = {'Actual': fmt_m, 'Budget': fmt_m, 'Forecast': fmt_m,
           '%VtB': fmt_p, '%VtF': fmt_p}
FMT_S3 = {'Actual': fmt_m, 'Budget': fmt_m, 'Forecast': fmt_m,
           '%VtB': fmt_p_na, '%VtF': fmt_p_na, '$VtB': fmt_m, '$VtF': fmt_m}
FMT_S2 = {'1-Times': fmt_m, 'Budget': fmt_m,
           '2+10': fmt_m, '5+7': fmt_m, '8+4': fmt_m, 'Rolling': fmt_m}

# ============================================================
# SVG SPARKLINE
# ============================================================
def make_svg_sparkline(values, width=110, height=38):
    try:
        vals = [float(v) if not (isinstance(v, float) and np.isnan(v)) else 0.0
                for v in values]
    except Exception:
        return "<span>→</span>"
    if len(vals) < 2:
        return "<span>→</span>"
    mn, mx = min(vals), max(vals)
    rng    = mx - mn if mx != mn else max(abs(mx), 0.001)
    pad    = 5
    w, h   = width - 2*pad, height - 2*pad
    def sx(i): return pad + int(i * w / (len(vals) - 1))
    def sy(v): return pad + int((1 - (v - mn) / rng) * h)
    pts    = " ".join(f"{sx(i)},{sy(v)}" for i, v in enumerate(vals))
    color  = CLR_GREEN if vals[-1] >= vals[0] else CLR_RED
    lx, ly = sx(len(vals) - 1), sy(vals[-1])
    return (f'<svg width="{width}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round"/>'
            f'<circle cx="{lx}" cy="{ly}" r="3" fill="{color}"/>'
            f'</svg>')

# ============================================================
# WoW HTML TABLE
# ============================================================
def render_wow_html(wow_tbl, wow_lbls, wow_piv):
    if wow_tbl.empty or not wow_lbls:
        st.info("No weekly data available for this month.")
        return

    TH   = ("background:#f8f9fa;text-align:center !important;padding:6px 10px;"
            "font-weight:bold;border:1px solid #dee2e6;font-size:13px;white-space:nowrap")
    TD   = "text-align:center !important;padding:4px 8px;border:1px solid #dee2e6;font-size:12px"
    TD_L = "text-align:left !important;padding:4px 10px;border:1px solid #dee2e6;font-size:12px"

    all_cols = ['Product'] + wow_lbls + ['Δ (CW vs PW)', 'Trend']

    html = '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%">'
    html += '<thead><tr>'
    for c in all_cols:
        html += f'<th style="{TH}">{c}</th>'
    html += '</tr></thead><tbody>'

    for _, row in wow_tbl.iterrows():
        is_total = row['Product'] == 'Total Money Management'
        extra    = 'font-weight:bold;background-color:#f1f3f4;' if is_total else ''

        html += '<tr>'
        html += f'<td style="{TD_L};{extra}">{row["Product"]}</td>'

        for lbl in wow_lbls:
            v = row.get(lbl, 0)
            try: vf = float(v)
            except: vf = 0.0
            html += f'<td style="{TD};{extra}">{fmt_m(vf)}</td>'

        dv = 0.0
        try: dv = float(row.get('Δ (CW vs PW)', 0))
        except: pass
        dc = CLR_GREEN if dv > 0 else (CLR_RED if dv < 0 else '#000000')
        html += (f'<td style="{TD};color:{dc};font-weight:bold;{extra}">'
                 f'{fmt_m(dv)}</td>')

        wom_week_lbls = [l for l in wow_lbls if l.startswith('W') and 'Actual' in l
                         and l not in ('Prev Week', 'Current Week')]
        svg = '<span style="color:#888">—</span>'
        if not wow_piv.empty and row['Product'] in wow_piv.index and wom_week_lbls:
            wom_keys = sorted(wow_piv.columns)
            vals     = [wow_piv.loc[row['Product'], w] for w in wom_keys]
            if any(abs(v) > 0 for v in vals):
                svg = make_svg_sparkline(vals)
        html += f'<td style="{TD};{extra}">{svg}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'
    st.markdown(html, unsafe_allow_html=True)

# ============================================================
# MANUAL INPUTS
# ============================================================
def load_manual():
    if os.path.exists(MANUAL_FILE):
        df = pd.read_csv(MANUAL_FILE)
        df['month'] = df['month'].astype(str).str.strip()
        df['year']  = df['year'].astype(str).str.strip()
        if 'is_gross_revenue' not in df.columns:
            df['is_gross_revenue'] = False
        df['is_gross_revenue'] = df['is_gross_revenue'].fillna(False).astype(bool)
        return df
    return pd.DataFrame(columns=["month","year","category","product",
                                  "adjustment_amount","comment","is_gross_revenue"])

# ============================================================
# DATA LOADER
# ============================================================
def load_data(target_date, fcst_ver, rev_type='NR'):
    all_data  = []
    target_ts = pd.to_datetime(target_date).normalize()
    start_ts  = target_ts.replace(day=1)
    end_ts    = pd.to_datetime(end_of_month).normalize()
    pfmap     = PFMAP_NR if rev_type == 'NR' else PFMAP_GR
    IS_GR     = (rev_type == 'GR')

    def _base(df, prod_c, src):
        t = pd.DataFrame()
        t['reporting_date'] = parse_dates(df['reporting_date'])
        t['Product']        = normalise_product(df[prod_c])
        t['source_file']    = src
        return t

    if os.path.exists(FILE_MM):
        df = pd.read_csv(FILE_MM)
        _norm_cols(df)
        pc = 'product_grouping' if 'product_grouping' in df.columns else 'product_pillar'
        t  = _base(df, pc, FILE_MM)
        if not IS_GR:
            t['act']  = _getcol(df, 'daily_actual_net_revenue')
            t['bud']  = _getcol(df, 'estimated_fy26_budget_net_revenue')
            t['2_10'] = _getcol(df, 'estimated_2_10_forecast_net_revenue')
            t['5_7']  = _getcol(df, 'estimated_5_7_forecast_net_revenue')
            t['8_4']  = _getcol(df, 'estimated_8_4_forecast_net_revenue')
        else:
            t['act']  = _getcol(df, 'daily_actual_gross_revenue')
            t['bud']  = _getcol(df, 'estimated_fy26_budget_gross_revenue')
            t['2_10'] = _getcol(df, 'estimated_2_10_forecast_gross_revenue')
            t['5_7']  = _getcol(df, 'estimated_5_7_forecast_gross_revenue')
            t['8_4']  = _getcol(df, 'estimated_8_4_forecast_gross_revenue')
        all_data.append(t)

    if os.path.exists(FILE_ISS):
        df = pd.read_csv(FILE_ISS)
        _norm_cols(df)
        pc = 'product_group' if 'product_group' in df.columns else 'product_pillar'
        t  = _base(df, pc, FILE_ISS)
        if not IS_GR:
            t['act']  = _getcol(df, 'net_revenue_actual')
            t['bud']  = _getcol(df, 'net_revenue_budget')
            t['2_10'] = _getcol(df, 'net_revenue_2_10_forecast')
            t['5_7']  = _getcol(df, 'net_revenue_5_7_forecast')
            t['8_4']  = _getcol(df, 'net_revenue_8_4_forecast')
        else:
            t['act']  = _getcol(df, 'gross_revenue_actual')
            t['bud']  = _getcol(df, 'gross_revenue_budget')
            t['2_10'] = _getcol(df, 'gross_revenue_2_10_forecast')
            t['5_7']  = _getcol(df, 'gross_revenue_5_7_forecast')
            t['8_4']  = _getcol(df, 'gross_revenue_8_4_forecast')
        all_data.append(t)

    bf        = FILE_BR_NET if not IS_GR else FILE_BR_GRS
    act_col_b = 'daily_actual_gross_revenue' if IS_GR else 'daily_actual_net_revenue'
    if os.path.exists(bf):
        df = pd.read_csv(bf)
        _norm_cols(df)
        pc = 'product_grouping' if 'product_grouping' in df.columns else 'product_pillar'
        t  = _base(df, pc, bf)
        t['act']  = _getcol(df, act_col_b,
                            'daily_actual_net_revenue',
                            'daily_actual_gross_revenue')
        t['bud']  = _getcol(df, 'estimated_fy26_budget')
        t['2_10'] = _getcol(df, 'estimated_fy26_2_10_forecast')
        t['5_7']  = _getcol(df, 'estimated_fy26_5_7_forecast')
        t['8_4']  = _getcol(df, 'estimated_fy26_8_4_forecast')
        all_data.append(t)

    if not all_data:
        empty = pd.DataFrame()
        return empty, empty, False, empty

    master = pd.concat(all_data, ignore_index=True)
    master['reporting_date'] = pd.to_datetime(master['reporting_date'],
                                              errors='coerce').dt.normalize()

    master['_ok'] = False
    for prod, f in pfmap.items():
        master.loc[(master['Product'] == prod) & (master['source_file'] == f),
                   '_ok'] = True
    master = master[master['_ok']].drop(columns='_ok')

    has_act = abs(master[master['reporting_date'] == target_ts]['act'].sum()) > 0

    mtd_raw = master[(master['reporting_date'] >= start_ts) &
                     (master['reporting_date'] <= target_ts)].copy()
    mtd_agg = mtd_raw.groupby('Product').sum(numeric_only=True).reset_index()

    if fcst_ver in mtd_agg.columns:
        mtd_agg['Forecast'] = mtd_agg[fcst_ver]
    elif fcst_ver == 'bud':
        mtd_agg['Forecast'] = mtd_agg.get('bud', 0)
    else:
        mtd_agg['Forecast'] = 0.0

    mtd_agg.rename(columns={'bud': 'Budget', 'act': 'Actual',
                             '2_10': '2+10', '5_7': '5+7', '8_4': '8+4'},
                   inplace=True)

    fm_raw = master[(master['reporting_date'] >= start_ts) &
                    (master['reporting_date'] <= end_ts)]
    fm_agg = fm_raw.groupby('Product').sum(numeric_only=True).reset_index()
    fm_agg.rename(columns={'bud': 'Budget', 'act': 'Actual',
                            '2_10': '2+10', '5_7': '5+7', '8_4': '8+4'},
                  inplace=True)

    return (mtd_agg.set_index('Product'),
            fm_agg.set_index('Product'),
            has_act,
            master[(master['reporting_date'] >= start_ts) &
                   (master['reporting_date'] <= end_ts)].copy())

# ============================================================
# DATA PROCESSING
# ============================================================
def process(df_mtd, df_full, fcst_ver, ones_dict, stretch_bud, bridge_roll, ovr_key):
    KEY_TO_DISPLAY = {'2_10': '2+10', '5_7': '5+7', '8_4': '8+4', 'bud': 'Budget'}
    fcst_display   = KEY_TO_DISPLAY.get(fcst_ver, fcst_ver)

    s1 = df_mtd.copy().reindex(product_order).fillna(0)
    if 'Forecast' not in s1.columns: s1['Forecast'] = s1.get(fcst_display, 0)
    if 'Budget'   not in s1.columns: s1['Budget']   = 0.0
    if 'Actual'   not in s1.columns: s1['Actual']   = 0.0
    s1['%VtB'] = np.where(s1['Budget']   != 0, s1['Actual']/s1['Budget']   - 1, 0)
    s1['%VtF'] = np.where(s1['Forecast'] != 0, s1['Actual']/s1['Forecast'] - 1, 0)

    df_f = df_full.copy().reindex(product_order).fillna(0)
    s2 = pd.DataFrame(index=product_order)
    s2['1-Times'] = pd.Series({p: ones_dict.get(p, 0) for p in product_order})
    s2['Budget']  = df_f.get('Budget', pd.Series(0, index=product_order))
    s2['2+10']    = df_f.get('2+10',   pd.Series(0, index=product_order))
    s2['5+7']     = df_f.get('5+7',    pd.Series(0, index=product_order))
    s2['8+4']     = df_f.get('8+4',    pd.Series(0, index=product_order))
    s2['Rolling'] = 0.0
    s2.loc['Stretch', 'Budget']  = stretch_bud
    s2.loc['Bridge',  'Rolling'] = bridge_roll
    if bridge_roll != 0:
        fc_s2 = fcst_display if fcst_display in s2.columns else 'Budget'
        s2.loc['Bridge', '1-Times'] += bridge_roll - s2.loc['Bridge', fc_s2]

    if ovr_key not in st.session_state:
        st.session_state[ovr_key] = {p: False for p in product_order}
    ovr     = st.session_state[ovr_key]
    fc_full = s2[fcst_display] if fcst_display in s2.columns else s2['Budget']

    s3 = pd.DataFrame(index=product_order)
    s3['Budget']   = np.where(
        s1.index.isin(prorate_prods) & (s1['Budget'] == 0),
        s2['Budget'] * prorate_factor, s1['Budget'])
    s3['Forecast'] = np.where(
        s1.index.isin(prorate_prods) & (s1['Forecast'] == 0),
        fc_full * prorate_factor, s1['Forecast'])
    omask        = [ovr.get(p, False) for p in s3.index]
    s3['Actual'] = np.where(omask,
                            s3['Forecast'] + s2['1-Times'],
                            s1['Actual']   + s2['1-Times'] * prorate_factor)
    s3['%VtB'] = np.where(s3['Budget']   != 0, s3['Actual']/s3['Budget']   - 1, 0)
    s3['%VtF'] = np.where(s3['Forecast'] != 0, s3['Actual']/s3['Forecast'] - 1, 0)
    s3['$VtB'] = s3['Actual'] - s3['Budget']
    s3['$VtF'] = s3['Actual'] - s3['Forecast']

    for df_t in [s1, s2, s3]:
        nc = df_t.select_dtypes(include=np.number).columns
        df_t.loc['Total Money Management', nc] = (
            df_t.drop('Total Money Management', errors='ignore')[nc].sum())

    for df_t in [s1, s3]:
        ta = df_t.loc['Total Money Management', 'Actual']
        tb = df_t.loc['Total Money Management', 'Budget']
        tf = df_t.loc['Total Money Management', 'Forecast']
        df_t.loc['Total Money Management', '%VtB'] = (ta/tb - 1) if tb != 0 else 0
        df_t.loc['Total Money Management', '%VtF'] = (ta/tf - 1) if tf != 0 else 0

    s3.loc['Total Money Management', '$VtB'] = (
        s3.loc['Total Money Management', 'Actual'] -
        s3.loc['Total Money Management', 'Budget'])
    s3.loc['Total Money Management', '$VtF'] = (
        s3.loc['Total Money Management', 'Actual'] -
        s3.loc['Total Money Management', 'Forecast'])

    i_bud = s2.loc['Total Money Management', 'Budget']
    i_vtb = s3.loc['Total Money Management', '%VtB']
    i_act = i_bud * (1 + i_vtb)
    i_fc  = (s2.loc['Total Money Management', fcst_display]
             if fcst_display in s2.columns else i_bud)
    impl = pd.DataFrame([{
        'Actual': i_act, 'Budget': i_bud, 'Forecast': i_fc,
        '%VtB': np.nan,  '%VtF': np.nan,
        '$VtB': i_act - i_bud, '$VtF': i_act - i_fc,
    }], index=['Implied End of Month'])
    s3 = pd.concat([s3, impl])

    for c in ['Actual', 'Budget', 'Forecast']:
        s1[c] /= 1e6
    for c in ['1-Times', 'Budget', '2+10', '5+7', '8+4', 'Rolling']:
        if c in s2.columns: s2[c] /= 1e6
    for c in ['Actual', 'Budget', 'Forecast', '$VtB', '$VtF']:
        s3[c] /= 1e6

    return (s1.reset_index(names='Product'),
            s2.reset_index(names='Product'),
            s3.reset_index(names='Product'))

# ============================================================
# WoW ENGINE
# ============================================================
def compute_wow(df_full_daily, target_date):
    dummy_idx = product_order + ['Total Money Management']
    dummy_df  = pd.DataFrame({'Product': dummy_idx})

    if df_full_daily is None or df_full_daily.empty:
        return dummy_df, [], pd.DataFrame()

    d = df_full_daily.copy()
    d['reporting_date'] = pd.to_datetime(d['reporting_date'])
    target_ts = pd.to_datetime(target_date).normalize()

    tgt_d    = target_ts.date()
    m_days   = calendar.monthrange(tgt_d.year, tgt_d.month)[1]
    max_wom  = (m_days - 1) // 7 + 1
    all_wom  = list(range(1, max_wom + 1))

    d_act = d[(d['reporting_date'] <= target_ts) & (d['act'].abs() > 0)].copy()
    if d_act.empty:
        return dummy_df, [], pd.DataFrame()

    d_act['WOM'] = d_act['reporting_date'].apply(lambda x: (x.day - 1) // 7 + 1)

    piv_act = (d_act.pivot_table(index='Product', columns='WOM',
                                  values='act', aggfunc='sum')
               .reindex(product_order).fillna(0))
    piv_act.loc['Total Money Management'] = piv_act.sum()
    piv_act /= 1e6

    weeks_with_data = sorted(d_act['WOM'].unique())
    curr_wom = weeks_with_data[-1]                             if weeks_with_data        else None
    prev_wom = weeks_with_data[-2] if len(weeks_with_data) >= 2 else None

    tbl    = pd.DataFrame(index=piv_act.index)
    labels = []

    for i, w in enumerate(all_wom):
        lbl = f'W{i+1} Actual'
        tbl[lbl] = piv_act[w] if w in piv_act.columns else 0.0
        labels.append(lbl)

    tbl['Prev Week'] = (piv_act[prev_wom]
                        if prev_wom is not None and prev_wom in piv_act.columns
                        else 0.0)
    labels.append('Prev Week')

    tbl['Current Week'] = (piv_act[curr_wom]
                           if curr_wom is not None and curr_wom in piv_act.columns
                           else 0.0)
    labels.append('Current Week')

    tbl['Δ (CW vs PW)'] = tbl['Current Week'] - tbl['Prev Week']
    tbl['Trend']        = ''

    return tbl.reset_index(names='Product'), labels, piv_act

# ============================================================
# WEEKLY PROGRESSION
# ============================================================
def compute_weekly_progression(df_full_daily, fcst_ver, s2_overlays,
                                forecast_display='Budget'):
    """
    Returns (tbl, col_meta, week_cols, fm_col_name).

    fm_col_name:
      'Full Month Budget'   when fcst_ver == 'bud'
      'Full Month Forecast' for 2+10 / 5+7 / 8+4

    Full-month reference values come directly from s2_overlays — the
    "Overlays — Full Month" table already built by process() — so the
    column is IDENTICAL to what the NR View "Overlays" section shows
    for the selected Budget / 2+10 / 5+7 / 8+4 column.

    s2_overlays values are already in $M (divided by 1e6 inside
    process()), so we do NOT divide the fm column again.
    Week columns (actuals / estimates) come from raw daily data and
    are divided by 1e6 here.
    """
    KEY_TO_COL  = {'bud': 'Budget', '2_10': '2+10', '5_7': '5+7', '8_4': '8+4'}
    fm_src_col  = KEY_TO_COL.get(fcst_ver, 'Budget')
    fm_col_name = 'Full Month Budget' if fcst_ver == 'bud' else 'Full Month Forecast'

    if df_full_daily is None or df_full_daily.empty:
        return pd.DataFrame(), [], [], fm_col_name

    # ── Full-month reference: pull directly from s2_overlays ($M) ──
    s2_idx = s2_overlays.set_index('Product')
    if fm_src_col in s2_idx.columns:
        fm_series_m = s2_idx[fm_src_col].reindex(product_order).fillna(0)
    else:
        fm_series_m = (s2_idx.get('Budget', pd.Series(0.0, index=product_order))
                             .reindex(product_order).fillna(0))

    d = df_full_daily.copy()
    d['reporting_date'] = pd.to_datetime(d['reporting_date'])
    d['WOM']      = d['reporting_date'].apply(lambda x: (x.day-1)//7+1)
    all_weeks     = sorted(d['WOM'].unique())
    result        = pd.DataFrame(index=product_order)
    col_meta      = []
    est_col       = fcst_ver if fcst_ver in d.columns else 'bud'

    for w in all_weeks:
        wk          = d[d['WOM'] == w]
        act_by_prod = wk.groupby('Product')['act'].sum().reindex(product_order).fillna(0)
        has_act     = act_by_prod.abs().sum() > 0
        if has_act:
            cname           = f"W{w} Actual"
            result[cname]   = act_by_prod / 1e6      # raw → $M
        else:
            est             = (wk.groupby('Product')[est_col].sum()
                                 .reindex(product_order).fillna(0)
                               if est_col in wk.columns
                               else pd.Series(0.0, index=product_order))
            cname           = f"W{w} Est."
            result[cname]   = est / 1e6              # raw → $M
        col_meta.append((cname, has_act))

    # Full-month column already in $M — assign directly
    result[fm_col_name] = fm_series_m

    week_cols     = [c for c, _ in col_meta]
    actual_cols   = [c for c, a in col_meta if a]
    result['MTD Actual'] = result[actual_cols].sum(axis=1) if actual_cols else 0.0
    result['$ To Go']    = result[fm_col_name] - result['MTD Actual']
    result['% Complete'] = np.where(result[fm_col_name] != 0,
                                    result['MTD Actual'] / result[fm_col_name], 0.0)

    # Total Money Management — sum all product rows (excluding itself)
    for c in week_cols + [fm_col_name, 'MTD Actual', '$ To Go']:
        result.loc['Total Money Management', c] = (
            result.drop('Total Money Management', errors='ignore')[c].sum())
    tm_a = result.loc['Total Money Management', 'MTD Actual']
    tm_b = result.loc['Total Money Management', fm_col_name]
    result.loc['Total Money Management', '% Complete'] = (
        tm_a / tm_b if tm_b != 0 else 0.0)

    # All columns already in $M — no further /1e6 needed
    return result.reset_index(names='Product'), col_meta, week_cols, fm_col_name

# ============================================================
# FINANCIAL VIEW  (shared by NR tab and GR tab)
# ============================================================
def render_view(s1, s2, s3, ovr_key, label):
    C1     = ['Product','Actual','Budget','Forecast','%VtB','%VtF']
    C2     = ['Product','1-Times','Budget','2+10','5+7','8+4','Rolling']
    C3_NUM = ['Product','Actual','Budget','Forecast','%VtB','%VtF','$VtB','$VtF']

    def _ens(df, cols):
        for c in cols:
            if c not in df.columns: df[c] = 0.0
        return df[cols]

    s1 = _ens(s1.copy(), C1)
    s2 = _ens(s2.copy(), C2)
    s3 = _ens(s3.copy(), C3_NUM)

    st.markdown("### MTD Raw Data")
    st.dataframe(
        s1.style.format(FMT_S1)
          .map(color_pct_var, subset=['%VtB','%VtF'])
          .apply(hl_totals, axis=1)
          .set_table_styles(TBL_STYLE),
        hide_index=True, use_container_width=True)

    st.markdown("### Overlays — Full Month")
    st.dataframe(
        s2.style.format(FMT_S2)
          .apply(hl_totals, axis=1)
          .set_table_styles(TBL_STYLE),
        hide_index=True, use_container_width=True)

    st.markdown("### MTD with 1-Times Overlay")

    PROD_ROWS   = [p for p in product_order if p not in FOOTER_PRODS]
    ALL_S3_ROWS = PROD_ROWS + [p for p in FOOTER_PRODS if p in s3['Product'].values]
    C3_FULL     = C3_NUM + ['ACT=FCST OVERRIDE']

    s3_ordered = (s3.set_index('Product')
                    .reindex(ALL_S3_ROWS)
                    .reset_index())

    impl_mask = s3_ordered['Product'] == 'Implied End of Month'
    s3_ordered.loc[impl_mask, '%VtB'] = np.nan
    s3_ordered.loc[impl_mask, '%VtF'] = np.nan

    s3_ordered['ACT=FCST OVERRIDE'] = [
        (st.session_state[ovr_key].get(p, False) if p in PROD_ROWS else False)
        for p in s3_ordered['Product']
    ]

    def hl_all_rows(row):
        if row.get('Product', '') in FOOTER_PRODS:
            return ['font-weight:bold;background-color:#f1f3f4;'] * len(row)
        return [''] * len(row)

    styled_s3 = (
        s3_ordered[C3_FULL].style
          .format(FMT_S3, na_rep='N/A',
                  subset=['Actual','Budget','Forecast','%VtB','%VtF','$VtB','$VtF'])
          .map(color_pct_var,    subset=['%VtB','%VtF'])
          .map(color_dollar_var, subset=['$VtB','$VtF'])
          .apply(hl_all_rows, axis=1)
          .set_table_styles(TBL_STYLE)
    )

    edited = st.data_editor(
        styled_s3,
        column_order=C3_FULL,
        column_config={
            "ACT=FCST OVERRIDE": st.column_config.CheckboxColumn(
                "ACT=FCST OVERRIDE", default=False,
                help="Product rows only — sets Actual = Forecast + 1-Times.\n"
                     "Has no effect on Total Money Management or Implied End of Month.")
        },
        disabled=['Product','Actual','Budget','Forecast','%VtB','%VtF','$VtB','$VtF'],
        hide_index=True, use_container_width=True,
        key=f"editor_{label.lower().replace(' ','_').replace('/','_')}"
    )

    new_chk   = edited['ACT=FCST OVERRIDE'].tolist()
    prod_list = edited['Product'].tolist()
    changed   = False
    for i, prod in enumerate(prod_list):
        nv = bool(new_chk[i]) if i < len(new_chk) else False
        if prod in PROD_ROWS:
            if nv != st.session_state[ovr_key].get(prod, False):
                st.session_state[ovr_key][prod] = nv
                changed = True
        else:
            if nv:
                changed = True
    if changed:
        st.rerun()

# ============================================================
# LOAD DATA
# ============================================================
df_manual = load_manual()
mask_m    = ((df_manual['month'] == str(as_of_date.month)) &
             (df_manual['year']  == str(as_of_date.year)))
cur_m     = df_manual[mask_m]

nr_ones = (cur_m[(cur_m['category'] == '1-Times') &
                 (~cur_m['is_gross_revenue'].astype(bool))]
           .groupby('product')['adjustment_amount'].sum().to_dict())
gr_ones = (cur_m[(cur_m['category'] == '1-Times') &
                 (cur_m['is_gross_revenue'].astype(bool))]
           .groupby('product')['adjustment_amount'].sum().to_dict())
stretch_bud = cur_m[(cur_m['category'] == 'Stretch Budget') &
                    (cur_m['product']  == 'Stretch')]['adjustment_amount'].sum()
bridge_roll = cur_m[(cur_m['category'] == 'Bridge Rolling') &
                    (cur_m['product']  == 'Bridge')]['adjustment_amount'].sum()

mtd_nr, full_nr, has_act_nr, daily_nr = load_data(as_of_date, forecast_version, 'NR')
mtd_gr, full_gr, has_act_gr, daily_gr = load_data(as_of_date, forecast_version, 'GR')

_detected_last, _csv_found = detect_last_actual_date()

def _badge(ok, lbl):
    clr = CLR_GREEN if ok else CLR_RED
    bg  = '#d4edda'  if ok else '#ffd5d5'
    txt = 'TRUE'     if ok else 'FALSE'
    st.sidebar.markdown(
        f"**{lbl}:** <span style='color:{clr};background-color:{bg};"
        f"padding:2px 6px;border-radius:3px;font-weight:bold;'>{txt}</span>",
        unsafe_allow_html=True)

_badge(has_act_nr, "NR Date Has Actuals")
_badge(has_act_gr, "GR Date Has Actuals")

if _csv_found:
    st.sidebar.markdown(
        f"<small>Last actual in data: "
        f"<b>{_detected_last.strftime('%d %b %Y')}</b></small>",
        unsafe_allow_html=True)
else:
    st.sidebar.markdown("<small>⚠️ CSV not found</small>", unsafe_allow_html=True)

if not has_act_nr:
    st.sidebar.markdown(
        f"*No actuals for {as_of_date}. "
        f"Try {_detected_last.strftime('%d %b %Y')} or earlier.*")

for k in ['overrides_nr', 'overrides_gr']:
    if k not in st.session_state:
        st.session_state[k] = {p: False for p in product_order}

s1_nr, s2_nr, s3_nr = process(mtd_nr, full_nr, forecast_version,
                               nr_ones, stretch_bud, bridge_roll, 'overrides_nr')
s1_gr, s2_gr, s3_gr = process(mtd_gr, full_gr, forecast_version,
                               gr_ones, stretch_bud, bridge_roll, 'overrides_gr')

wow_tbl, wow_lbls, wow_piv = compute_wow(daily_nr, as_of_date)

# ── Progression: s2_nr is passed so the Full Month column is IDENTICAL
#    to "Overlays — Full Month" Budget / 2+10 / 5+7 / 8+4 in NR View ──
prog_tbl, prog_meta, prog_week_cols, fm_col_name = compute_weekly_progression(
    daily_nr, forecast_version, s2_nr, forecast_display)

# ============================================================
# TABS
# ============================================================
tab_nr, tab_gr, tab_ins, tab_man = st.tabs([
    "📊 NR View", "💰 GR View", "📈 Insights & WoW Trends", "⚙️ Manual Data Inputs"
])

with tab_nr:
    render_view(s1_nr, s2_nr, s3_nr, 'overrides_nr', 'Net Revenue')

with tab_gr:
    render_view(s1_gr, s2_gr, s3_gr, 'overrides_gr', 'Gross Revenue')

with tab_ins:

    # ── 1. WoW Progression ───────────────────────────────────
    st.markdown("### Week-on-Week Progression ($M)")
    render_wow_html(wow_tbl, wow_lbls, wow_piv)

    st.divider()

    # ── 2. Weekly Progression Table ─────────────────────────
    st.markdown("### 📋 Weekly Estimated vs Actual Progression — NR ($M)")
    lk1, lk2, lk3 = st.columns(3)
    with lk1:
        st.markdown(
            "<span style='background:#d4edda;padding:3px 8px;border-radius:4px;"
            "font-size:13px;'>🟢 <b>Actual</b> — confirmed NR</span>",
            unsafe_allow_html=True)
    with lk2:
        st.markdown(
            f"<span style='background:#fff3cd;padding:3px 8px;border-radius:4px;"
            f"font-size:13px;'>🟡 <b>Est.</b> — projected from {forecast_display}</span>",
            unsafe_allow_html=True)
    with lk3:
        _to_go_lbl = forecast_display
        st.markdown(
            f"<span style='background:#ffd5d5;padding:3px 8px;border-radius:4px;"
            f"font-size:13px;'>🔴 <b>$ To Go</b> — remaining vs {_to_go_lbl}</span>",
            unsafe_allow_html=True)
    st.markdown("")

    if not prog_tbl.empty:
        actual_cnames = [c for c, a in prog_meta if a]
        est_cnames    = [c for c, a in prog_meta if not a]
        prog_fmt      = {c: fmt_m for c in prog_week_cols +
                         [fm_col_name, 'MTD Actual', '$ To Go']}
        prog_fmt['% Complete'] = fmt_pct_complete

        def style_progression(df):
            styles = pd.DataFrame('', index=df.index, columns=df.columns)
            for c in actual_cnames:
                if c in df.columns:
                    styles[c] = 'background-color:#e8f5e9;color:#1b5e20;font-weight:bold;'
            for c in est_cnames:
                if c in df.columns:
                    styles[c] = 'background-color:#fff8e1;color:#e65100;font-style:italic;'
            if fm_col_name in df.columns:
                styles[fm_col_name] = 'background-color:#e3f2fd;font-weight:bold;'
            if 'MTD Actual' in df.columns:
                styles['MTD Actual'] = 'background-color:#e8f5e9;font-weight:bold;'
            if '$ To Go' in df.columns:
                for i, v in enumerate(df['$ To Go']):
                    try:
                        num = float(str(v).replace('$','').replace('M',''))
                        styles.iloc[i, df.columns.get_loc('$ To Go')] = (
                            f'color:{CLR_RED};font-weight:bold;' if num > 0
                            else f'color:{CLR_GREEN};font-weight:bold;')
                    except: pass
            if '% Complete' in df.columns:
                for i, v in enumerate(df['% Complete']):
                    try:
                        pct = float(str(v).replace('%','')) / 100
                        clr = (CLR_GREEN      if pct >= prorate_factor * 0.95
                               else '#f57c00' if pct >= prorate_factor * 0.80
                               else CLR_RED)
                        styles.iloc[i, df.columns.get_loc('% Complete')] = (
                            f'color:{clr};font-weight:bold;')
                    except: pass
            for i, p in enumerate(df.get('Product', pd.Series())):
                if p == 'Total Money Management':
                    styles.iloc[i] = styles.iloc[i].apply(
                        lambda x: x + ';font-weight:bold;background-color:#f1f3f4;')
            return styles

        prog_cols = (['Product'] + prog_week_cols +
                     [fm_col_name, 'MTD Actual', '$ To Go', '% Complete'])
        st.dataframe(
            prog_tbl[prog_cols].style
              .format(prog_fmt)
              .apply(style_progression, axis=None)
              .set_table_styles(TBL_STYLE),
            hide_index=True, use_container_width=True)

        total_row = prog_tbl[prog_tbl['Product'] == 'Total Money Management']
        if not total_row.empty:
            st.markdown("")
            k1, k2, k3, k4 = st.columns(4)
            mtd_v    = total_row['MTD Actual'].values[0]
            bud_v    = total_row[fm_col_name].values[0]
            tog_v    = total_row['$ To Go'].values[0]
            pct_v    = total_row['% Complete'].values[0] * 100   # % completed
            rem_pct  = 100.0 - pct_v                             # % still remaining

            k1.metric("MTD Actual ($M)",     f"${mtd_v:.1f}M")
            k2.metric(f"{fm_col_name} ($M)", f"${bud_v:.1f}M")

            # Card 3: $ To Go — delta shows % remaining vs the selected version
            k3.metric(
                "$ To Go ($M)",
                f"${tog_v:.1f}M",
                delta=f"{rem_pct:.0f}% remaining vs {forecast_display}",
                delta_color="inverse",   # red when positive = behind target
            )

            # Card 4: % Complete — delta shows gap vs pro-rated expected %
            expected_pct = prorate_factor * 100
            gap_pct      = pct_v - expected_pct
            k4.metric(
                "% Complete",
                f"{pct_v:.0f}%",
                delta=f"{gap_pct:+.0f}pp vs expected {expected_pct:.0f}%",
                delta_color=("normal" if pct_v >= prorate_factor * 95 else "inverse"),
            )
    else:
        st.info("No progression data available. Check that CSVs are loaded correctly.")

    st.divider()

    # ── 3. Budget Pacing ─────────────────────────────────────
    st.markdown(
        f"### 🎯 Budget Pacing — MTD vs Full Month  "
        f"*(Day {as_of_date.day} of {days_in_month} = {prorate_factor:.0%} elapsed)*")

    pac_rows = []
    for prod in [p for p in product_order if p != 'Total Money Management']:
        ma = (s1_nr[s1_nr['Product'] == prod]['Actual'].values[0]
              if not s1_nr[s1_nr['Product'] == prod].empty else 0)
        fb = (s2_nr[s2_nr['Product'] == prod]['Budget'].values[0]
              if not s2_nr[s2_nr['Product'] == prod].empty else 0)
        pac_rows.append({'Product': prod, 'MTD Actual': ma,
                         'Full Month Budget': fb,
                         'Pacing': ma / fb if fb != 0 else 0.0})

    pac_df = pd.DataFrame(pac_rows)

    def _pac_status(p):
        if   p >= prorate_factor:        return 'On Track (Above)'
        elif p >= prorate_factor * 0.90: return 'On Track (Near)'
        else:                             return 'Behind'

    pac_df['Status'] = pac_df['Pacing'].apply(_pac_status)
    status_rank = {'On Track (Above)': 0, 'On Track (Near)': 1, 'Behind': 2}
    pac_df['_rank'] = pac_df['Status'].map(status_rank)
    pac_df = pac_df.sort_values(['_rank', 'Pacing'], ascending=[True, False])
    y_order = pac_df['Product'].tolist()[::-1]

    color_map = {
        'On Track (Above)': '#006400',
        'On Track (Near)':  '#90EE90',
        'Behind':           CLR_RED,
    }
    f_pac = px.bar(
        pac_df, x='Pacing', y='Product', orientation='h',
        title='NR MTD Pacing vs Full Month Budget',
        text=pac_df['Pacing'].apply(lambda x: f'{x:.0%}'),
        color='Status',
        color_discrete_map=color_map,
        category_orders={'Product': y_order},
    )
    f_pac.add_vline(x=prorate_factor, line_dash='dash', line_color='orange',
                    annotation_text=f'Expected {prorate_factor:.0%}',
                    annotation_position='top right')
    f_pac.update_traces(textposition='outside')
    x_min = min(pac_df['Pacing'].min() * 1.25, -0.05)
    x_max = max(pac_df['Pacing'].max() * 1.25, prorate_factor * 1.5)
    f_pac.update_layout(
        xaxis=dict(tickformat='.0%', range=[x_min, x_max]),
        legend=dict(orientation='v', x=1.02, y=0.5,
                    xanchor='left', yanchor='middle',
                    bgcolor='rgba(255,255,255,0.85)',
                    bordercolor='#cccccc', borderwidth=1),
        margin=dict(l=10, r=160, t=50, b=10),
    )
    st.plotly_chart(f_pac, use_container_width=True)

    st.divider()

    # ── 4. Product Mix ───────────────────────────────────────
    st.markdown("### 🍩 Product Mix — MTD NR Actual")
    mix_df = s1_nr[~s1_nr['Product'].isin(['Total Money Management'])].copy()
    mix_df = mix_df[mix_df['Actual'] > 0]
    if not mix_df.empty:
        f_mix = px.pie(mix_df, names='Product', values='Actual',
                       title='NR Product Mix (MTD Actuals)', hole=0.4,
                       color_discrete_sequence=px.colors.qualitative.Pastel)
        f_mix.update_traces(textinfo='label+percent', pull=[0.03]*len(mix_df))
        st.plotly_chart(f_mix, use_container_width=True)

    st.divider()

    # ── 5. NR vs GR Comparison ───────────────────────────────
    st.markdown("### 🔁 NR vs GR Comparison — MTD Actuals ($M)")

    EXCL  = ['Implied End of Month', 'Stretch']
    ch_nr = s3_nr[~s3_nr['Product'].isin(EXCL)].copy()
    ch_gr = s3_gr[~s3_gr['Product'].isin(EXCL)].copy()
    comp  = (ch_nr[['Product','Actual']].rename(columns={'Actual':'NR Actual'})
             .merge(ch_gr[['Product','Actual']].rename(columns={'Actual':'GR Actual'}),
                    on='Product', how='left'))
    comp['Take Rate'] = np.where(comp['GR Actual'] != 0,
                                 comp['NR Actual'] / comp['GR Actual'], np.nan)

    cc1, cc2 = st.columns(2)

    with cc1:
        m2 = comp.melt(id_vars='Product', value_vars=['NR Actual','GR Actual'],
                       var_name='Type', value_name='$M')
        m2['Label'] = m2['$M'].apply(lambda x: f"{x:.1f}" if not np.isnan(x) else "")

        f_comp = px.bar(m2, x='Product', y='$M', color='Type', barmode='group',
                        title='MTD: NR vs GR Actuals ($M)',
                        text='Label',
                        color_discrete_sequence=['#1f77b4', '#ff7f0e'])
        f_comp.update_traces(textposition='outside',
                             textfont=dict(color='black', size=10))
        f_comp.update_layout(
            xaxis_tickangle=-35,
            xaxis=dict(showgrid=False),
            yaxis=dict(range=[0, m2['$M'].max() * 1.35], showgrid=False),
            plot_bgcolor='white',
            legend=dict(orientation='h', yanchor='top', y=-0.28,
                        x=0.5, xanchor='center', title_text=''),
            margin=dict(t=50, b=110),
        )
        st.plotly_chart(f_comp, use_container_width=True)

    with cc2:
        cx = comp[comp['Take Rate'].notna()].copy()

        order_map   = {p: i for i, p in enumerate(product_order)}
        cx['_ord']  = cx['Product'].map(order_map).fillna(999)
        cx          = cx.sort_values('_ord', ascending=False)
        y_cat_order = list(cx['Product'])
        cx          = cx.drop(columns='_ord')

        avg_tr         = cx['Take Rate'].mean() if not cx.empty else 0.0
        cx['TR_Label'] = cx['Take Rate'].apply(lambda x: f'{x:.1%}')

        prods_cx = cx[cx['Product'] != 'Total Money Management']
        total_cx = cx[cx['Product'] == 'Total Money Management']

        f_tr = go.Figure()
        if not prods_cx.empty:
            f_tr.add_trace(go.Bar(
                x=prods_cx['Take Rate'], y=prods_cx['Product'],
                orientation='h', marker_color='#6a0dad',
                text=prods_cx['TR_Label'], textposition='outside',
                textfont=dict(color='black', size=10),
                name='Products',
                hovertemplate='%{y}: %{x:.1%}<extra></extra>',
            ))
        if not total_cx.empty:
            f_tr.add_trace(go.Bar(
                x=total_cx['Take Rate'], y=total_cx['Product'],
                orientation='h', marker_color='#ff7f0e',
                text=total_cx['TR_Label'], textposition='outside',
                textfont=dict(color='black', size=10),
                name='Total MM',
                hovertemplate='%{y}: %{x:.1%}<extra></extra>',
            ))

        max_tr   = cx['Take Rate'].max() if not cx.empty else 0.1
        x_max_tr = max(max_tr * 1.55, 0.12)

        f_tr.update_layout(
            title='Take Rate by Product',
            barmode='relative',
            xaxis=dict(tickformat='.0%', range=[0, x_max_tr],
                       tickfont=dict(size=11)),
            yaxis=dict(
                categoryorder='array',
                categoryarray=y_cat_order,
                tickfont=dict(size=11),
                automargin=True,
            ),
            plot_bgcolor='white',
            legend=dict(orientation='h', yanchor='top', y=-0.10,
                        x=0.5, xanchor='center', title_text=''),
            margin=dict(t=60, b=90, r=110, l=180),
        )
        f_tr.update_xaxes(showgrid=True, gridcolor='#eeeeee')
        f_tr.update_yaxes(showgrid=False)

        if avg_tr > 0:
            f_tr.add_shape(
                type='line',
                xref='x', yref='paper',
                x0=avg_tr, x1=avg_tr,
                y0=0, y1=1,
                line=dict(color='#FFD700', width=2.5, dash='dash'),
                layer='above',
            )
            f_tr.add_annotation(
                xref='x', yref='paper',
                x=avg_tr, y=1.01,
                text=f'<b>Avg {avg_tr:.1%}</b>',
                showarrow=False,
                xanchor='left',
                yanchor='bottom',
                font=dict(color='#FFD700', size=12),
                bgcolor='rgba(20,0,40,0.80)',
                bordercolor='#FFD700',
                borderwidth=1,
                borderpad=4,
            )

        st.plotly_chart(f_tr, use_container_width=True)

# ============================================================
# TAB 4 — Manual Data Inputs
# ============================================================
with tab_man:
    st.markdown("### ⚙️ Manual Adjustment Management")
    st.info(
        "**1-Times:** unchecked → NR View  |  checked → GR View\n\n"
        "Stretch Budget & Bridge Rolling apply to both views."
    )
    df_all     = load_manual()
    edited_man = st.data_editor(
        df_all, num_rows='dynamic', use_container_width=True, hide_index=True,
        column_config={
            "category":          st.column_config.SelectboxColumn("Category",
                                    options=["1-Times","Stretch Budget","Bridge Rolling"],
                                    required=True),
            "product":           st.column_config.SelectboxColumn("Product Line",
                                    options=product_order, required=True),
            "month":             st.column_config.SelectboxColumn("Month",
                                    options=[str(i) for i in range(1, 13)],
                                    required=True),
            "year":              st.column_config.SelectboxColumn("Year",
                                    options=[str(y) for y in range(2024, 2031)],
                                    required=True),
            "adjustment_amount": st.column_config.NumberColumn("$ Adjustment",
                                    format="$%.2f"),
            "comment":           st.column_config.TextColumn("Comment"),
            "is_gross_revenue":  st.column_config.CheckboxColumn(
                                    "Is Gross Revenue?", default=False,
                                    help="Tick = GR View. Untick = NR View.")
        }
    )
    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("💾 Save Locally"):
            os.makedirs(_HERE, exist_ok=True)
            edited_man.to_csv(MANUAL_FILE, index=False)
            st.success("Saved ✅")
    with bc2:
        st.download_button(
            label="⬇️ Download CSV for GitHub Sync",
            data=edited_man.to_csv(index=False).encode('utf-8'),
            file_name="data_manual_adj.csv", mime="text/csv")
    st.divider()
    st.info("""
**3-To sync with GitHub after every update:**

1. Edit rows above → click **Download CSV for GitHub Sync**
2. Replace `weekly_nr_dashboard/data_manual_adj.csv` on your desktop
3. In VS Code terminal:
   ```
   git add weekly_nr_dashboard/data_manual_adj.csv
   git commit -m "update manual adj"
   git push
   ```
   ✅ Streamlit Cloud auto-redeploys in ~1 minute.

**Auto-push tip:** Add `GITHUB_TOKEN` to Streamlit Secrets and use
`PyGithub` to push the CSV directly from the dashboard.
    """)