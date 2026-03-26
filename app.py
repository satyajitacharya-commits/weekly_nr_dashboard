import streamlit as st
import pandas as pd
import datetime
import calendar
import numpy as np
import os
import warnings
import plotly.express as px
import pytz
import getpass
import plotly.graph_objects as go

# Suppress background terminal warnings
warnings.filterwarnings('ignore', category=UserWarning)

st.set_page_config(layout="wide", page_title="Weekly NR Dashboard")

# --- FILE PATH FOR MANUAL INPUTS ---
MANUAL_FILE = 'data_manual_adj.csv'

# --- UI CONTROLS (Sidebar) ---
st.sidebar.header("Dashboard Settings")
forecast_version = st.sidebar.selectbox("Forecast Version", ["Budget", "2_10", "5_7", "8_4"])
as_of_date = st.sidebar.date_input("As-Of Date", datetime.date(2026, 3, 17))

# --- 1. ADDITION: LAST REFRESHED INFO ---
pt = pytz.timezone('America/Los_Angeles')
refresh_time = datetime.datetime.now(pt).strftime("%Y-%m-%d %I:%M %p")
#user_name = getpass.getuser()
user_name = st.experimental_user.get("email", "Local User")

st.sidebar.markdown(f"**Last Sync:** `{refresh_time} PT`")
st.sidebar.markdown(f"**Refreshed By:** `{user_name}`")

start_of_month = as_of_date.replace(day=1)
days_in_month = calendar.monthrange(as_of_date.year, as_of_date.month)[1]
end_of_month = as_of_date.replace(day=days_in_month)
prorate_factor = as_of_date.day / days_in_month

product_order = [
    "Connect", "Instant Payouts", "Multicurrency Settlement", "Capital", 
    "Issuing", "Bridge", "Faster Payouts", "Mass Payouts", 
    "Financial Accounts", "Other BaaS Products", "Stretch", "Total Money Management"
]
prorate_rule_products = ["Bridge", "Faster Payouts", "Mass Payouts", "Financial Accounts", "Other BaaS Products", "Stretch"]

product_file_mapping = {
    "Connect": "data_mm_connect.csv", "Instant Payouts": "data_mm_connect.csv",
    "Multicurrency Settlement": "data_mm_connect.csv", "Capital": "data_mm_connect.csv",
    "Issuing": "data_issuing.csv",
    "Bridge": "data_bridge_other.csv", "Faster Payouts": "data_bridge_other.csv",
    "Mass Payouts": "data_bridge_other.csv", "Financial Accounts": "data_bridge_other.csv",
    "Other BaaS Products": "data_bridge_other.csv"
}

prod_normalization_map = {k.lower(): k for k in product_order}

# --- NEW MANUAL DATA LOADER ---
def load_manual_inputs():
    if os.path.exists(MANUAL_FILE):
        df = pd.read_csv(MANUAL_FILE)
        df['month'] = df['month'].astype(str).str.strip()
        df['year'] = df['year'].astype(str).str.strip()
        return df
    else:
        return pd.DataFrame(columns=["month", "year", "category", "product", "adjustment_amount", "comment"])

# --- DATA CLEANING ENGINE ---
def clean_money(series):
    if series.dtype == 'object':
        s = series.astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.strip()
        mask_neg = s.str.startswith('(') & s.str.endswith(')')
        s = s.str.replace('(', '', regex=False).str.replace(')', '', regex=False)
        num = pd.to_numeric(s, errors='coerce').fillna(0)
        return np.where(mask_neg, -num, num)
    return pd.to_numeric(series, errors='coerce').fillna(0)

# --- DATA LOADER ---
def load_real_csv_data(target_date, fcst_ver):
    all_data = []
    file_mappings = {
        'data_mm_connect.csv': {'act': 'daily_actual_net_revenue', 'bud': 'estimated_fy26_budget', '2_10': 'estimated_fy25_2_10_forecast', '5_7': 'estimated_fy25_5_7_forecast', '8_4': 'estimated_fy25_8_4_forecast'},
        'data_bridge_other.csv': {'act': 'daily_actual_net_revenue', 'bud': 'estimated_fy26_budget', '2_10': 'estimated_fy25_2_10_forecast', '5_7': 'estimated_fy25_5_7_forecast', '8_4': 'estimated_fy25_8_4_forecast'},
        'data_issuing.csv': {'act': 'tmbl_actuals', 'bud': 'estimated_tmbl_based_on_budget', '2_10': 'estimated_tmbl_based_on_reforecast_2_plus_10', '5_7': 'estimated_tmbl_based_on_reforecast_5_plus_7', '8_4': 'estimated_tmbl_based_on_reforecast_8_plus_4'}
    }
    
    for file, cols in file_mappings.items():
        if os.path.exists(file):
            df = pd.read_csv(file)
            df.columns = df.columns.astype(str).str.replace(r'[^a-zA-Z0-9_]', '', regex=True).str.lower()
            date_col = 'reporting_date' if 'reporting_date' in df.columns else None
            prod_col = 'product_grouping' if 'product_grouping' in df.columns else 'product_pillar' if 'product_pillar' in df.columns else None
            
            if date_col and prod_col:
                df['reporting_date_clean'] = pd.to_datetime(df[date_col], errors='coerce').dt.date
                temp = pd.DataFrame()
                temp['reporting_date'] = df['reporting_date_clean']
                raw_prods = df[prod_col].astype(str).str.strip().str.lower()
                temp['Product'] = raw_prods.map(prod_normalization_map).fillna(df[prod_col].astype(str).str.strip())
                temp['source_file'] = file 
                
                for tgt, src in cols.items():
                    if src in df.columns:
                        temp[tgt] = clean_money(df[src])
                    else:
                        if tgt == 'bud' and 'estimated_fy25_budget' in df.columns:
                            temp[tgt] = clean_money(df['estimated_fy25_budget'])
                        else:
                            temp[tgt] = 0.0
                all_data.append(temp)
            
    if not all_data:
        return pd.DataFrame(), pd.DataFrame(), False, pd.DataFrame()
        
    master_df = pd.concat(all_data, ignore_index=True)
    master_df['valid'] = False
    for prod, f in product_file_mapping.items():
        master_df.loc[(master_df['Product'] == prod) & (master_df['source_file'] == f), 'valid'] = True
    master_df = master_df[master_df['valid']]
    
    exact_date_df = master_df[master_df['reporting_date'] == target_date]
    date_has_actuals = abs(exact_date_df['act'].sum()) > 0
    
    mtd_daily_df = master_df[(master_df['reporting_date'] >= target_date.replace(day=1)) & (master_df['reporting_date'] <= target_date)].copy()
    
    mtd_agg = mtd_daily_df.groupby('Product').sum(numeric_only=True).reset_index()
    mtd_agg['Forecast'] = mtd_agg[fcst_ver] if fcst_ver in mtd_agg.columns else mtd_agg['bud']
    mtd_agg.rename(columns={'bud': 'Budget', 'act': 'Actual'}, inplace=True)
    
    full_df = master_df[(master_df['reporting_date'] >= target_date.replace(day=1)) & (master_df['reporting_date'] <= end_of_month)]
    full_agg = full_df.groupby('Product').sum(numeric_only=True).reset_index()
    full_agg.rename(columns={'bud': 'Budget', 'act': 'Actual'}, inplace=True)
    
    return mtd_agg.set_index('Product'), full_agg.set_index('Product'), date_has_actuals, mtd_daily_df

df_mtd, df_full, date_has_actuals, df_daily = load_real_csv_data(as_of_date, forecast_version)
df_mtd = df_mtd.reindex(product_order).fillna(0)
df_full = df_full.reindex(product_order).fillna(0)

# --- DYNAMIC TRUE/FALSE CHECK IN SIDEBAR ---
if date_has_actuals:
    st.sidebar.markdown(f"**Date Has Actuals:** <span style='color:green; background-color:#d4edda; padding: 2px 5px; border-radius: 3px; font-weight:bold;'>TRUE</span>", unsafe_allow_html=True)
else:
    st.sidebar.markdown(f"**Date Has Actuals:** <span style='color:#721c24; background-color:#f8d7da; padding: 2px 5px; border-radius: 3px; font-weight:bold;'>FALSE</span>", unsafe_allow_html=True)
st.sidebar.markdown("*If 'FALSE' variances are inaccurate because daily Budget/Forecast and Actuals are not populated for consistent days. Use an earlier As-Of Date.*")

# --- MANUAL INPUTS FROM CSV ---
df_inputs = load_manual_inputs()
mask = (df_inputs['month'] == str(as_of_date.month)) & (df_inputs['year'] == str(as_of_date.year))
current_inputs = df_inputs[mask]

one_times_dict = current_inputs[current_inputs['category'] == '1-Times'].groupby('product')['adjustment_amount'].sum().to_dict()
stretch_bud_val = current_inputs[(current_inputs['category'] == 'Stretch Budget') & (current_inputs['product'] == 'Stretch')]['adjustment_amount'].sum()
bridge_rolling_val = current_inputs[(current_inputs['category'] == 'Bridge Rolling') & (current_inputs['product'] == 'Bridge')]['adjustment_amount'].sum()

# --- DATA PROCESSING ---
sec1 = df_mtd.copy()
sec1['VtB'] = np.where(sec1['Budget'] == 0, 0, (sec1['Actual'] / sec1['Budget']) - 1)
sec1['VtF'] = np.where(sec1['Forecast'] == 0, 0, (sec1['Actual'] / sec1['Forecast']) - 1)

sec2 = pd.DataFrame(index=product_order)
sec2['1-Times'] = sec2.index.map(one_times_dict).fillna(0)
sec2['Budget'] = df_full['Budget']
sec2['2_10'] = df_full['2_10'] if '2_10' in df_full.columns else 0
sec2['5_7'] = df_full['5_7'] if '5_7' in df_full.columns else 0
sec2['8_4'] = df_full['8_4'] if '8_4' in df_full.columns else 0
sec2['Rolling'] = 0.0

sec2.loc['Stretch', 'Budget'] = stretch_bud_val
sec2.loc['Bridge', 'Rolling'] = bridge_rolling_val
bridge_rolling = sec2.loc['Bridge', 'Rolling']
if bridge_rolling != 0:
    sec2.loc['Bridge', '1-Times'] += (bridge_rolling - sec2.loc['Bridge', forecast_version])

if 'overrides' not in st.session_state:
    st.session_state.overrides = {prod: False for prod in product_order}
sec3 = pd.DataFrame(index=product_order)
sec3['Budget'] = np.where((sec3.index.isin(prorate_rule_products)) & (sec1['Budget'] == 0), sec2['Budget'] * prorate_factor, sec1['Budget'])
sec3['Forecast'] = np.where((sec3.index.isin(prorate_rule_products)) & (sec1['Forecast'] == 0), sec2[forecast_version] * prorate_factor, sec1['Forecast'])

actual_if_override = sec3['Forecast'] + sec2['1-Times']
actual_no_override = sec1['Actual'] + (sec2['1-Times'] * prorate_factor)
override_mask = [st.session_state.overrides.get(p, False) for p in sec3.index]
sec3['Actual'] = np.where(override_mask, actual_if_override, actual_no_override)

sec3['VtB'] = np.where(sec3['Budget'] == 0, 0, (sec3['Actual'] / sec3['Budget']) - 1)
sec3['VtF'] = np.where(sec3['Forecast'] == 0, 0, (sec3['Actual'] / sec3['Forecast']) - 1)
sec3['ACT=FCST OVERRIDE'] = override_mask  

for df in [sec1, sec2, sec3]:
    df.loc['Total Money Management'] = df.drop(['Total Money Management', 'ACT=FCST OVERRIDE'], errors='ignore').sum(numeric_only=True)

for df in [sec1, sec3]:
    tot_act = df.loc['Total Money Management', 'Actual']
    tot_bud = df.loc['Total Money Management', 'Budget']
    tot_fct = df.loc['Total Money Management', 'Forecast']
    df.loc['Total Money Management', 'VtB'] = (tot_act / tot_bud) - 1 if tot_bud != 0 else 0
    df.loc['Total Money Management', 'VtF'] = (tot_act / tot_fct) - 1 if tot_fct != 0 else 0

implied_budget = sec2.loc['Total Money Management', 'Budget']
implied_vtb_total = sec3.loc['Total Money Management', 'VtB']
implied_actual = implied_budget * (1 + implied_vtb_total)
implied_forecast = sec2.loc['Total Money Management', 'Budget'] if forecast_version == "Budget" else sec2.loc['Total Money Management', forecast_version]

implied_row = pd.Series({
    "Actual": implied_actual, "Budget": implied_budget, "Forecast": implied_forecast,
    "VtB": "", "VtF": "", "ACT=FCST OVERRIDE": None
}, name="Implied End of Month")

sec3 = pd.concat([sec3, implied_row.to_frame().T])
sec3.loc['Total Money Management', 'ACT=FCST OVERRIDE'] = False

# Scale to Millions
for col in ['Actual', 'Budget', 'Forecast']:
    sec1[col] = sec1[col] / 1000000
    sec3[col] = sec3[col] / 1000000
for col in ['1-Times', 'Budget', '2_10', '5_7', '8_4', 'Rolling']:
    sec2[col] = sec2[col] / 1000000

# Copy unformatted data for charts
chart_df = sec3.copy().drop([ 'Implied End of Month'], errors='ignore').reset_index(names='Product')

sec1.reset_index(names='Product', inplace=True)
sec2.reset_index(names='Product', inplace=True)
sec3.reset_index(names='Product', inplace=True)

cols_sec1 = ['Product', 'Actual', 'Budget', 'Forecast', 'VtB', 'VtF']
cols_sec2 = ['Product', '1-Times', 'Budget', '2_10', '5_7', '8_4', 'Rolling']
cols_sec3 = ['Product', 'Actual', 'Budget', 'Forecast', 'VtB', 'VtF', 'ACT=FCST OVERRIDE']

sec1 = sec1[cols_sec1]
sec2 = sec2[cols_sec2]
sec3 = sec3[cols_sec3]

# --- WoW ENGINE ---
if not df_daily.empty:
    df_daily['reporting_date'] = pd.to_datetime(df_daily['reporting_date'])
    df_daily['ISO_Week'] = df_daily['reporting_date'].dt.isocalendar().week
    
    wow_pivot = df_daily.pivot_table(index='Product', columns='ISO_Week', values='act', aggfunc='sum').reindex(product_order).fillna(0)
    wow_pivot.loc['Total Money Management'] = wow_pivot.sum()
    wow_pivot = wow_pivot / 1000000
    
    weeks = sorted(wow_pivot.columns)
    if len(weeks) >= 2:
        wow_df = pd.DataFrame(index=wow_pivot.index)
        wow_df['Prev Week'] = wow_pivot[weeks[-2]]
        wow_df['Current Week'] = wow_pivot[weeks[-1]]
        wow_df['Week Delta'] = wow_df['Current Week'] - wow_df['Prev Week']
        wow_df['WoW %'] = np.where(wow_df['Prev Week'] == 0, 0, (wow_df['Current Week'] / wow_df['Prev Week']) - 1)
        wow_df['Trend'] = wow_df['WoW %'].apply(lambda x: "📈" if x > 0.01 else "📉" if x < -0.01 else "➡️")
    else:
        wow_df = pd.DataFrame({'Product': product_order, 'Prev Week': 0.0, 'Current Week': 0.0, 'Week Delta': 0.0, 'WoW %': 0.0, 'Trend': "🆕"})
    wow_df.reset_index(names='Product', inplace=True)
else:
    wow_df = pd.DataFrame(columns=['Product', 'Prev Week', 'Current Week', 'Week Delta', 'WoW %', 'Trend'])
    
# --- FORMATTING RULES & BOLD ROW INJECTION ---
def fmt_m(val):
    if val == "" or val is None: return ""
    if pd.isna(val) or val == "na": return "$0.0M"
    try: return f"${float(val):.1f}M"
    except: return "$0.0M"

def fmt_p(val):
    if val == "" or val is None: return ""
    if pd.isna(val) or val == "na": return "0.0%"
    try: return f"{float(val) * 100:.0f}%"
    except: return "0.0%"

def color_variances(val):
    try:
        if pd.isna(val) or val == "": return ''
        v = float(str(val).replace('%', '').replace(',', ''))
        if v < 0: return 'color: #d32f2f; font-weight: bold;'
        elif v > 0: return 'color: #388e3c; font-weight: bold;'
        return ''
    except:
        return ''

def highlight_totals(row):
    if row['Product'] in ['Total Money Management', 'Implied End of Month']:
        return ['font-weight: bold; background-color: #f1f3f4;'] * len(row)
    return [''] * len(row)

format_dict_sec13 = {'Actual': fmt_m, 'Budget': fmt_m, 'Forecast': fmt_m, 'VtB': fmt_p, 'VtF': fmt_p}
format_dict_sec2 = {'1-Times': fmt_m, 'Budget': fmt_m, '2_10': fmt_m, '5_7': fmt_m, '8_4': fmt_m, 'Rolling': fmt_m}

table_styles = [
    dict(selector="th", props=[("text-align", "center"), ("font-weight", "bold"), ("font-size", "14px")]),
    dict(selector="td", props=[("text-align", "center"),("font-size", "12px"),("min-width", "80px"),("width", "80px")])
]

# --- LAYOUT: UI TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Financial Summary", "📈 Insights & WoW Trends", "⚙️ Manual Data Inputs"])

with tab1:
    st.markdown("### **MTD Raw Data**")
    styled_sec1 = sec1.style.format(format_dict_sec13)\
        .map(color_variances, subset=['VtB', 'VtF'])\
        .apply(highlight_totals, axis=1)\
        .set_table_styles(table_styles)
    st.dataframe(styled_sec1, hide_index=True, use_container_width=True)

    st.markdown("### **Overlays (Full Month)**")
    styled_sec2 = sec2.style.format(format_dict_sec2)\
        .apply(highlight_totals, axis=1)\
        .set_table_styles(table_styles)
    st.dataframe(styled_sec2, hide_index=True, use_container_width=True)

    st.markdown("### **MTD with 1-Times Overlay**")
    styled_sec3 = sec3.style.format(format_dict_sec13)\
        .map(color_variances, subset=['VtB', 'VtF'])\
        .apply(highlight_totals, axis=1)\
        .set_table_styles(table_styles)
    
    edited_sec3 = st.data_editor(
        styled_sec3, 
        column_order=cols_sec3, 
        column_config={"ACT=FCST OVERRIDE": st.column_config.CheckboxColumn("ACT=FCST OVERRIDE", default=False)},
        disabled=['Product', 'Actual', 'Budget', 'Forecast', 'VtB', 'VtF'],
        hide_index=True,
        use_container_width=True
    )
    
    new_checkboxes = edited_sec3['ACT=FCST OVERRIDE'].tolist()
    for i, prod in enumerate(product_order[:-1]): 
        if new_checkboxes[i] != st.session_state.overrides[prod]:
            st.session_state.overrides[prod] = new_checkboxes[i]
            st.rerun()

with tab2:
    st.markdown("### **Week-on-Week Progression ($M)**")
    wow_format = {'Prev Week': fmt_m, 'Current Week': fmt_m, 'Week Delta': fmt_m, 'WoW %': fmt_p}
    styled_wow = wow_df.style.format(wow_format).map(color_variances, subset=['Week Delta', 'WoW %']).apply(highlight_totals, axis=1).set_table_styles(table_styles)
    st.dataframe(styled_wow, hide_index=True, use_container_width=True)
    
    st.divider()
    st.markdown("### **Visual Insights (MTD with Overlays)**")
    col1, col2 = st.columns(2)
    
    compare_col = 'Budget' if forecast_version == 'Budget' else 'Forecast'
    var_col, var_name = ('VtB', 'VtB') if forecast_version == 'Budget' else ('VtF', 'VtF')

    with col1:
        df_melt = chart_df.melt(id_vars='Product', value_vars=['Actual', compare_col], var_name='Metric', value_name='Net Revenue ($M)')
        fig1 = px.bar(df_melt, x='Product', y='Net Revenue ($M)', color='Metric', barmode='group', title=f"MTD Actuals vs {compare_col}", text_auto='.1f', color_discrete_sequence=['#1f77b4', '#aec7e8'])
        fig1.update_traces(textfont_size=12, textangle=0, textposition="outside", cliponaxis=False)
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        chart_df['Var_Chart'] = chart_df[var_col] * 100
        fig2 = px.bar(chart_df, x='Var_Chart', y='Product', orientation='h', title=f"MTD Variance ({var_name} %)", text=chart_df['Var_Chart'].apply(lambda x: f"{x:.1f}%"), color=np.where(chart_df['Var_Chart'] >= 0, 'Favorable', 'Unfavorable'), color_discrete_map={'Favorable': '#388e3c', 'Unfavorable': '#d32f2f'})
        fig2.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig2, use_container_width=True)

    
    st.markdown("### **Week-on-Week Actual NR Trend ($M)**")
    chart_pivot = df_daily.pivot_table(index='Product', columns='ISO_Week', values='act', aggfunc='sum').fillna(0) / 1000000
    chart_pivot.loc['Total Money Management'] = chart_pivot.sum()
    bar_data = chart_pivot.drop('Total Money Management').reset_index().melt(id_vars='Product', var_name='Week', value_name='Actual NR')
    line_data = chart_pivot.loc[['Total Money Management']].reset_index().melt(id_vars='Product', var_name='Week', value_name='Total')

    fig3 = go.Figure()
    for prod in bar_data['Product'].unique():
        p_df = bar_data[bar_data['Product'] == prod]
        fig3.add_trace(go.Bar(x=p_df['Week'], y=p_df['Actual NR'], name=prod, text=p_df['Actual NR'].apply(lambda x: f"{x:.1f}" if x != 0 else ""), textposition='inside', insidetextanchor='middle', textangle=0))
    fig3.add_trace(go.Scatter(x=line_data['Week'], y=line_data['Total'], name="Total Money Management", mode='lines+markers+text', text=line_data['Total'].apply(lambda x: f"<b>${x:.1f}M</b>"), textposition="top center", line=dict(color='#ff80ff', width=4), marker=dict(size=10, color='#ff80ff'), textfont=dict(color='black', size=11)))
    fig3.update_traces(texttemplate="<span style='background-color:rgba(255,255,255,0.7); padding:2px'>%{text}</span>", selector=dict(name="Total Money Management"))
    fig3.update_layout(yaxis_title="Net Revenue ($M)", xaxis_title="Week Number", barmode='stack', margin=dict(t=50),xaxis= dict(tickmode='linear',tick0=1,dtick=1))
    st.plotly_chart(fig3, use_container_width=True)

# --- REFRESHED TAB 3 FOR CSV MANAGEMENT ---
with tab3:
    st.markdown("### **Manual Adjustment Management**")
    st.info("Edit adjustments below. To save permanently, download the CSV and sync via VS Code.")
    
    df_all_manual = load_manual_inputs()
    
    edited_manual_df = st.data_editor(
        df_all_manual, 
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "category": st.column_config.SelectboxColumn("Category", options=["1-Times", "Stretch Budget", "Bridge Rolling"], required=True),
            "product": st.column_config.SelectboxColumn("Product Line", options=product_order, required=True),
            "month": st.column_config.SelectboxColumn("Month", options=[str(i) for i in range(1, 13)], required=True),
            "year": st.column_config.SelectboxColumn("Year", options=[str(y) for y in range(2024, 2031)], required=True),
            "adjustment_amount": st.column_config.NumberColumn("$ Adjustment", format="$%.2f")
        }
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Save Locally (Laptop Only)"):
            edited_manual_df.to_csv(MANUAL_FILE, index=False)
            st.success("File saved to your local folder!")

    with col_btn2:
        csv_data = edited_manual_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Updated CSV for Sync",
            data=csv_data,
            file_name="data_manual_adj.csv",
            mime="text/csv",
        )