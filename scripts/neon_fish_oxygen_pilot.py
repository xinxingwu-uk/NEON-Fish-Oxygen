"""NEON fish and dissolved-oxygen feasibility pilot.

Study sites: GUIL, BLUE, KING. Data release: RELEASE-2026.
Run with: python neon_fish_oxygen_pilot.py
Requires a NEON API token supplied through NEON_TOKEN or the hidden prompt.
The input/output calculations match KAS_NEON_Fish_Oxygen_Pilot_Clean.ipynb.
"""
from __future__ import annotations

# --- Configuration and imports ---
# Change study years, sites, or exposure definitions only for a new versioned analysis.
import os, re, json
from pathlib import Path
from datetime import datetime, timezone
from getpass import getpass
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
try:
    from IPython.display import display
except ImportError:
    def display(value):
        print(value)
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm.auto import tqdm
API = 'https://data.neonscience.org/api/v0'
FISH = 'DP1.20107.001'
WATER = 'DP1.20288.001'
RELEASE = 'RELEASE-2026'
YEAR_MIN, YEAR_MAX = (2022, 2025)
PILOT_SITE_IDS = ("GUIL", "BLUE", "KING")
MAX_FISH_MONTHS_PER_SITE = 4
WINDOWS_DAYS = [7, 14, 30]
MIN_COVERAGE = 0.7
MIN_MINUTE_MEASUREMENTS_PER_HOUR = 20
DO_CUTOFF = 5.0
# Wider candidate list is used only for the availability audit; the cohort is fixed above.
PREFERRED_STREAM_SITES = [
    'BLUE', 'WALK', 'KING', 'LEWI', 'PRIN', 'BLWA', 'MAYF', 'MCDI',
    'HOPB', 'POSE', 'FLNT', 'ARIK', 'WLOU', 'COMO', 'BIGC', 'MART',
    'MCRA', 'CARI', 'OKSR', 'REDB', 'SYCA', 'TECR', 'CUPE', 'GUIL',
]
OUT = Path('/content/kas_neon_fish_pilot') if Path('/content').exists() else Path('kas_neon_fish_pilot')
CACHE = OUT / 'cache'
FIG = OUT / 'figures'
TABLE = OUT / 'tables'
for p in [CACHE, FIG, TABLE]:
    p.mkdir(parents=True, exist_ok=True)
retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['GET'])
session = requests.Session()
session.mount('https://', HTTPAdapter(max_retries=retry))
session.headers['User-Agent'] = 'KAS-undergraduate-ecology-research-pilot/1.0'
print('Output directory:', OUT)
print('Fish product:', FISH, '  Water product:', WATER, '  Release:', RELEASE)

# --- Product availability and fixed-site selection ---
# Fix the pilot sites to avoid tie-dependent changes in the study cohort.
def get_json(url, auth=False, params=None):
    r = session.get(url, params=params, timeout=90)
    if r.status_code in (401, 403) and auth:
        raise RuntimeError('NEON download authorization failed. Refresh your token on the NEON Data Portal.')
    r.raise_for_status()
    result = r.json()
    if 'data' not in result:
        raise RuntimeError(f'Unexpected NEON response: {str(result)[:300]}')
    return result['data']

def product_availability(pid):
    data = get_json(f'{API}/products/{pid}')
    avail = {}
    for entry in data.get('siteCodes', []):
        months = []
        for release_entry in entry.get('availableReleases', []):
            if release_entry.get('release') == RELEASE:
                months = release_entry.get('availableMonths', [])
                break
        avail[entry['siteCode']] = sorted(set(months))
    return avail
fish_meta = product_availability(FISH)
water_meta = product_availability(WATER)

def prev_month(ym):
    return (pd.Timestamp(ym + '-01') - pd.DateOffset(months=1)).strftime('%Y-%m')
plan_rows = []
for site in PREFERRED_STREAM_SITES:
    fmonths = [m for m in fish_meta.get(site, []) if YEAR_MIN <= int(m[:4]) <= YEAR_MAX]
    wmonths = set(water_meta.get(site, []))
    qualified = [m for m in fmonths if m in wmonths and prev_month(m) in wmonths]
    plan_rows.append({'siteID': site, 'fish_months': len(fmonths), 'fish_months_with_two_WQ_months': len(qualified), 'eligible_months': qualified})
plan_df = pd.DataFrame(plan_rows).sort_values('fish_months_with_two_WQ_months', ascending=False)
display(plan_df[['siteID', 'fish_months', 'fish_months_with_two_WQ_months']].head(20))
available_sites = plan_df.loc[plan_df.fish_months_with_two_WQ_months > 0]
missing_sites = [site for site in PILOT_SITE_IDS if site not in set(available_sites.siteID)]
if missing_sites:
    raise RuntimeError(f"Selected sites lack eligible fish/water months: {missing_sites}")
selected = available_sites.set_index("siteID", drop=False).loc[list(PILOT_SITE_IDS)].copy()
site_month_plan = {row.siteID: sorted(row.eligible_months)[-MAX_FISH_MONTHS_PER_SITE:] for row in selected.itertuples()}
print('Selected sites and fish months (2026 released data):', site_month_plan)
if not site_month_plan:
    raise RuntimeError('No fish+water months with full two-month availability; broaden YEAR range or candidate sites.')
plan_df.drop(columns=['eligible_months']).to_csv(TABLE / 'availability_summary.csv', index=False)
with open(TABLE / 'download_plan.json', 'w') as f:
    json.dump({'release': RELEASE, 'sites': site_month_plan, 'selected_at_utc': datetime.now(timezone.utc).isoformat()}, f, indent=2)

# --- NEON token ---
NEON_TOKEN = os.getenv('NEON_TOKEN', '').strip()
if not NEON_TOKEN:
    NEON_TOKEN = getpass('Paste your NEON API token (hidden): ').strip()
if not NEON_TOKEN:
    raise RuntimeError('A NEON API token is required to download public datasets.')
session.headers['X-API-Token'] = NEON_TOKEN
print('NEON token configured (not displayed).')

# --- Download released CSV files ---
# Keep original NEON CSV filenames to preserve sensor-position metadata.
TARGET_FISH = ['fsh_perFish', 'fsh_bulkCount', 'fsh_perPass', 'fsh_fieldData']
TARGET_WATER = ['waq_instantaneous']

def month_files(pid, site, month):
    data = get_json(f'{API}/data/{pid}/{site}/{month}', auth=True, params={'release': RELEASE, 'package': 'basic'})
    return data.get('files', [])

def download_one_file(record, site, month, table_name):
    name = record['name']
    safe = re.sub('[^A-Za-z0-9._-]+', '_', name)
    local = CACHE / safe
    if local.exists() and local.stat().st_size > 0:
        return local
    url = record['url']
    from urllib.parse import urlparse
    same_host = urlparse(url).hostname == 'data.neonscience.org'
    client = session if same_host else requests
    with client.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        temp = local.with_suffix(local.suffix + '.part')
        try:
            with temp.open('wb') as fout:
                for chunk in r.iter_content(chunk_size=2 ** 20):
                    if chunk:
                        fout.write(chunk)
            temp.replace(local)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    return local

def table_matches(filename, t):
    return filename.lower().endswith('.csv') and re.search('(?<![a-z])' + re.escape(t.lower()) + '(?![a-z])', filename.lower()) is not None
filepaths = {k: [] for k in TARGET_FISH + TARGET_WATER}
requests_plan = []
for site, month_list in site_month_plan.items():
    for m in month_list:
        requests_plan.append((FISH, site, m, TARGET_FISH))
        for wm in [prev_month(m), m]:
            requests_plan.append((WATER, site, wm, TARGET_WATER))
seen = set()
unique = []
for row in requests_plan:
    key = row[:3]
    if key not in seen:
        unique.append(row)
        seen.add(key)
log = []
for pid, site, month, targets in tqdm(unique, desc='NEON released site-month packages'):
    try:
        records = month_files(pid, site, month)
        found = []
        for target in targets:
            matches = [r for r in records if table_matches(r.get('name', ''), target)]
            for record in matches:
                path = download_one_file(record, site, month, target)
                if path not in filepaths[target]:
                    filepaths[target].append(path)
                found.append(target)
        log.append({'siteID': site, 'month': month, 'product': pid, 'tables': ';'.join(sorted(set(found))), 'n_files': len(found), 'status': 'ok'})
    except Exception as exc:
        log.append({'siteID': site, 'month': month, 'product': pid, 'tables': '', 'n_files': 0, 'status': f'ERROR: {str(exc)[:160]}'})
        print('WARNING', pid, site, month, ':', str(exc)[:160])
download_log = pd.DataFrame(log)
display(download_log)
download_log.to_csv(TABLE / 'download_log.csv', index=False)
print('Tables downloaded:', {k: len(v) for k, v in filepaths.items()})
if not filepaths['fsh_perFish'] and (not filepaths['fsh_bulkCount']):
    raise RuntimeError('No fish count files. Check the download log, token, and chosen release.')
if not filepaths['waq_instantaneous']:
    raise RuntimeError('No water quality files. Check the download log and chosen sites.')

# --- Read instrument and fish tables ---
# Restore site and sensor metadata from the original NEON instrument filename.
WATER_COLS = {'siteID', 'horizontalPosition', 'verticalPosition', 'temporalIndex', 'startDateTime', 'endDateTime', 'dissolvedOxygen', 'dissolvedOxygenFinalQF'}
SENSOR_FILE_PATTERN = re.compile(
    r'^NEON\.D\d{2}\.(?P<site>[A-Z0-9]{4})\.'
    r'DP1\.20288\.001\.'
    r'(?P<hor>[A-Z0-9]{3})\.'
    r'(?P<ver>[A-Z0-9]{3})\.'
    r'(?P<tmi>[A-Z0-9]{3})\.'
    r'waq_instantaneous\.',
    flags=re.IGNORECASE,
)

def metadata_from_neon_filename(path):
    match = SENSOR_FILE_PATTERN.match(Path(path).name)
    if not match:
        return None
    return {'siteID': match.group('site').upper(), 'horizontalPosition': match.group('hor'), 'verticalPosition': match.group('ver'), 'temporalIndex': match.group('tmi')}

def read_table(paths, table):
    if not paths:
        return pd.DataFrame()
    frames = []
    for path in paths:
        kwargs = {'low_memory': False}
        if table == 'waq_instantaneous':
            kwargs['usecols'] = lambda c: c in WATER_COLS
        df = pd.read_csv(path, **kwargs)
        if table == 'waq_instantaneous':
            info = metadata_from_neon_filename(path)
            needed_meta = ['siteID', 'horizontalPosition', 'verticalPosition']
            missing_meta = [c for c in needed_meta if c not in df.columns]
            if missing_meta and info is None:
                raise ValueError(f'Cannot recover {missing_meta} from file: {Path(path).name}\nExpected original NEON instrument filename with SITE/HOR/VER/TMI. Do not rename raw downloaded CSVs.')
            if info is not None:
                for col, val in info.items():
                    if col in df.columns:
                        observed = df[col].dropna().astype(str).str.replace('\\.0$', '', regex=True)
                        bad = observed[observed.str.upper() != str(val).upper()]
                        if len(bad):
                            raise ValueError(f'Conflicting {col} in {Path(path).name}: filename={val}, CSV={bad.iloc[0]}')
                    df[col] = val
        df['source_file'] = Path(path).name
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
tables = {tab: read_table(paths, tab) for tab, paths in filepaths.items()}
for tab, df in tables.items():
    print(f'{tab}: {len(df):,} rows; first columns:', list(df.columns[:14]))
for tab in ['fsh_perFish', 'fsh_bulkCount']:
    if len(tables[tab]) and (not {'siteID', 'eventID', 'taxonID'}.issubset(tables[tab].columns)):
        raise ValueError(f'{tab}: unexpected fish table fields.')
required = {'siteID', 'endDateTime', 'dissolvedOxygen', 'dissolvedOxygenFinalQF', 'horizontalPosition', 'verticalPosition', 'temporalIndex'}
missing = required - set(tables['waq_instantaneous'].columns)
if missing:
    raise ValueError(f'Water quality fields still missing: {missing}')
water = tables['waq_instantaneous']
if not water.empty and (not water.temporalIndex.astype(str).eq('100').all()):
    raise ValueError('Unexpected temporal index. This notebook requires instantaneous (TMI=100) sensor data.')
print('\nWater-quality sites:', sorted(water.siteID.dropna().unique().tolist()))
print('Sensor positions and record counts:')
display(water.groupby(['siteID', 'horizontalPosition', 'verticalPosition', 'temporalIndex']).size().rename('n_rows').reset_index())

# --- Build event-level fish summaries ---
# Preserve the original event-level count and richness calculations.
parts = []
per = tables['fsh_perFish'].copy()
bulk = tables['fsh_bulkCount'].copy()
for name, frame in [('processed', per), ('bulk', bulk)]:
    if frame.empty:
        continue
    x = frame.copy()
    x['siteID'] = x['siteID'].astype(str)
    x['taxonID'] = x['taxonID'].astype('string')
    x = x[x['taxonID'].notna() & x['eventID'].notna()]
    if name == 'processed':
        x['count'] = 1
    else:
        if 'bulkFishCount' not in x:
            raise ValueError('NEON bulk count field bulkFishCount not found.')
        x['count'] = pd.to_numeric(x['bulkFishCount'], errors='coerce').fillna(0)
        x = x[x['count'] >= 0]
    x['origin'] = name
    parts.append(x)
if not parts:
    raise RuntimeError('Fish capture tables have no taxon records.')
fish_long = pd.concat(parts, ignore_index=True)
fish_long['count'] = pd.to_numeric(fish_long['count'], errors='coerce').fillna(0)
fish_taxa = fish_long.groupby(['siteID', 'eventID', 'taxonID'], as_index=False)['count'].sum().rename(columns={'count': 'captured_count'})
# Diagnostic only: retain the original richness definition to preserve the archived pilot.
# Zero-count taxon rows, if present, may inflate distinct-taxon richness.
zero_only_taxa = fish_taxa.loc[fish_taxa['captured_count'].eq(0)].copy()
print(f'Richness audit: {len(zero_only_taxa)} site/event/taxon groups have zero recorded captures.')
if not zero_only_taxa.empty:
    print('WARNING: provisional observed_taxa counts these groups. Recalculate richness using')
    print('strictly positive captures in a separate, explicitly versioned analysis before inference.')
zero_only_taxa.to_csv(TABLE / 'zero_count_taxon_audit.csv', index=False)
date_parts = []
for tab in ['fsh_fieldData', 'fsh_perPass', 'fsh_perFish', 'fsh_bulkCount']:
    x = tables[tab]
    if x.empty or 'boutEndDate' not in x.columns or 'eventID' not in x.columns:
        continue
    dt = pd.DataFrame({'siteID': x.siteID, 'eventID': x.eventID, 'event_datetime': pd.to_datetime(x['boutEndDate'], utc=True, errors='coerce')})
    date_parts.append(dt)
if not date_parts:
    raise ValueError('No boutEndDate found. Inspect the 2026 NEON fish file schema.')
dates = pd.concat(date_parts, ignore_index=True).dropna(subset=['event_datetime']).groupby(['siteID', 'eventID'], as_index=False)['event_datetime'].min()
fish_events = fish_taxa.groupby(['siteID', 'eventID'], as_index=False).agg(observed_taxa=('taxonID', 'nunique'), captured_fish=('captured_count', 'sum'))
fish_events = fish_events.merge(dates, on=['siteID', 'eventID'], how='left')
fish_events['date'] = fish_events.event_datetime.dt.floor('D')
fish_events['season'] = fish_events.eventID.astype(str).str.extract('\\.(spring|fall)\\b', flags=re.I)[0].str.lower().fillna('unknown')
fish_events = fish_events.sort_values(['siteID', 'date']).reset_index(drop=True)
print(f'Events with captured fish: {len(fish_events)} (zero-capture or unsampled events not reconstructed)')
display(fish_events.head(12))
fish_events.to_csv(TABLE / 'fish_events_capture_only.csv', index=False)
fish_taxa.to_csv(TABLE / 'fish_event_taxon_counts.csv', index=False)

# --- Apply DO quality checks and aggregate to hourly medians ---
# One sensor position per site; retain the upstream fallback when S2 is absent.
waq = tables['waq_instantaneous'].copy()
waq['time'] = pd.to_datetime(waq.endDateTime, utc=True, errors='coerce')
waq['do_mg_l'] = pd.to_numeric(waq['dissolvedOxygen'], errors='coerce')
waq['qf'] = pd.to_numeric(waq['dissolvedOxygenFinalQF'], errors='coerce')
waq['hor'] = pd.to_numeric(waq['horizontalPosition'], errors='coerce').astype('Int64')
waq['ver'] = pd.to_numeric(waq.get('verticalPosition', pd.Series([0] * len(waq))), errors='coerce')
waq = waq.dropna(subset=['siteID', 'time', 'hor'])
sensor_choice = {}
clean_list = []
for site, x in waq.groupby('siteID'):
    hor_counts = x.hor.value_counts()
    downstream = [int(h) for h in hor_counts.index if int(h) in (102, 112)]
    upstream = [int(h) for h in hor_counts.index if int(h) in (101, 111)]
    buoy = [int(h) for h in hor_counts.index if int(h) == 103]
    if downstream:
        hor = max(downstream, key=lambda h: hor_counts.loc[h])
        sensor_set = 'downstream (S2)'
    elif upstream:
        hor = max(upstream, key=lambda h: hor_counts.loc[h])
        sensor_set = 'upstream (S1 fallback; no S2 downloaded)'
    elif buoy:
        hor = 103
        sensor_set = 'buoy (check habitat comparability)'
    else:
        print(f'WARNING: {site} has unrecognized HOR positions {list(hor_counts.index)}; skipped.')
        continue
    y = x[x.hor == hor]
    vcounts = y.ver.value_counts(dropna=True)
    if len(vcounts):
        ver = vcounts.index[0]
        y = y[y.ver == ver]
    else:
        ver = None
    sensor_choice[site] = {'horizontalPosition': int(hor), 'verticalPosition': None if ver is None else float(ver), 'sensor_set': sensor_set, 'raw_rows': len(y)}
    clean_list.append(y)
if not clean_list:
    raise RuntimeError('No usable sensor locations found; inspect the site/sensor summary in Cell 10.')
print('IMPORTANT: sensor positions may change over time; review sensor_positions_20288 for publication.')
waq = pd.concat(clean_list, ignore_index=True)
raw_count = len(waq)
waq = waq[(waq.qf == 0) & (waq.do_mg_l >= 0) & (waq.do_mg_l <= 25)].copy()
waq = waq.drop_duplicates(subset=['siteID', 'hor', 'ver', 'time']).sort_values('time')
print('Selected downstream sensors:', sensor_choice)
print('Quality-filtered measurements:', len(waq), 'of', raw_count, f'({len(waq) / max(raw_count, 1):.1%})')
hourly_parts = []
for site, x in waq.groupby('siteID'):
    h = x.set_index('time')['do_mg_l'].resample('h').agg(['median', 'count'])
    h['do_mg_l'] = h['median'].where(h['count'] >= MIN_MINUTE_MEASUREMENTS_PER_HOUR)
    h = h[['do_mg_l', 'count']].reset_index().rename(columns={'time': 'hour', 'count': 'n_valid_minutes'})
    h['siteID'] = site
    hourly_parts.append(h)
hourly = pd.concat(hourly_parts, ignore_index=True)
print('Total hourly records:', len(hourly), 'Valid:', hourly.do_mg_l.notna().sum())
with open(TABLE / 'downstream_sensor_choices.json', 'w') as f:
    json.dump(sensor_choice, f, indent=2)
hourly.to_csv(TABLE / 'qc_hourly_dissolved_oxygen.csv', index=False)

# --- Calculate pre-survey DO exposure windows ---
# Every window ends before the survey date and requires adequate hourly coverage.
def metrics_from_hourly(series, asof, days, cutoff=DO_CUTOFF):
    end = pd.Timestamp(asof)
    if pd.isna(end):
        return {'coverage': 0, 'hours_good': 0, 'hours_expected': days * 24}
    start = end - pd.Timedelta(days=days)
    x = series[(series.index >= start) & (series.index < end)].dropna()
    expected = days * 24
    coverage = len(x) / expected
    record = {'coverage': coverage, 'hours_good': len(x), 'hours_expected': expected}
    if coverage < MIN_COVERAGE:
        record.update({'do_mean': np.nan, 'do_p10': np.nan, 'do_min': np.nan, 'do_sd': np.nan, 'prop_below_5': np.nan})
    else:
        record.update({'do_mean': x.mean(), 'do_p10': x.quantile(0.1), 'do_min': x.min(), 'do_sd': x.std(), 'prop_below_5': (x < cutoff).mean()})
    return record
series_by_site = {site: x.set_index('hour')['do_mg_l'].sort_index() for site, x in hourly.groupby('siteID')}
metrics = []
for ev in fish_events.itertuples():
    if ev.siteID not in series_by_site:
        continue
    s = series_by_site[ev.siteID]
    for days in WINDOWS_DAYS:
        metrics.append({'siteID': ev.siteID, 'eventID': ev.eventID, 'window_days': days, **metrics_from_hourly(s, ev.date, days)})
oxygen_metrics = pd.DataFrame(metrics)
if oxygen_metrics.empty:
    oxygen_metrics = pd.DataFrame(columns=['siteID', 'eventID', 'window_days', 'coverage', 'hours_good', 'hours_expected', 'do_mean', 'do_p10', 'do_min', 'do_sd', 'prop_below_5'])
paired = fish_events.merge(oxygen_metrics, on=['siteID', 'eventID'], how='left')
paired['usable'] = paired.do_mean.notna()
print('Availability of adequate pre-survey oxygen windows:')
display(paired.groupby('window_days', dropna=False).agg(n_events=('eventID', 'nunique'), n_adequate=('usable', 'sum'), median_coverage=('coverage', 'median')).reset_index())
display(paired[['siteID', 'eventID', 'date', 'window_days', 'observed_taxa', 'do_mean', 'do_p10', 'prop_below_5', 'coverage', 'usable']].head(18))
paired.to_csv(TABLE / 'paired_fish_oxygen_all_windows.csv', index=False)
oxygen_metrics.to_csv(TABLE / 'oxygen_window_metrics.csv', index=False)

# --- Plot pre-survey oxygen time series ---
# Figures display observed, QC-filtered data without gap interpolation.
import matplotlib as mpl
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

FIG.mkdir(parents=True, exist_ok=True)
COLOR_MAIN = '#165D75'
COLOR_ACCENT = '#D19A48'
COLOR_TEXT = '#1F2937'
COLOR_SUB = '#526174'
COLOR_GRID = '#E7EBF0'
SITE_COLORS = {
    'BLUE': '#2866A6',
    'GUIL': '#E38838',
    'KING': '#409378',
}

mpl.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 10,
    'axes.titlesize': 13,
    'axes.labelsize': 11,
    'axes.labelcolor': COLOR_TEXT,
    'text.color': COLOR_TEXT,
    'xtick.color': COLOR_SUB,
    'ytick.color': COLOR_SUB,
    'axes.edgecolor': '#B5BEC8',
    'axes.linewidth': .85,
    'xtick.major.size': 0,
    'ytick.major.size': 0,
    'savefig.facecolor': 'white',
    'figure.facecolor': 'white',
    'svg.fonttype': 'none',
    'pdf.fonttype': 42,
})

def clean_axes(ax, grid_axis='y'):
    ax.set_facecolor('white')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis=grid_axis, alpha=1, color=COLOR_GRID, linewidth=.75)
    ax.set_axisbelow(True)
    ax.tick_params(axis='both', pad=7)

def save_scientific_figure(fig, stem):

    for ext in ['png', 'pdf', 'svg']:
        fig.savefig(FIG / f'{stem}.{ext}', dpi=350, facecolor='white',
                    bbox_inches='tight', pad_inches=.16)
    print('Saved high-resolution PNG + vector PDF/SVG:', FIG / f'{stem}.png')

matched30 = paired[(paired.window_days == 30) & paired.usable].copy()
if matched30.empty:
    print('Figure 1 skipped: no adequate 30-day pre-survey DO records.')
else:
    ev = matched30.sort_values('coverage', ascending=False).iloc[0]
    site, date = str(ev['siteID']), pd.Timestamp(ev['date'])
    segment = series_by_site[site].loc[
        lambda s: (s.index >= date - pd.Timedelta(days=30)) & (s.index < date)
    ]
    observed = segment.dropna()
    if observed.empty:
        print('Figure 1 skipped: the selected time series has no valid observations.')
    else:

        spaced = segment.reindex(
            pd.date_range(date - pd.Timedelta(days=30),
                          date - pd.Timedelta(hours=1), freq='h', tz='UTC')
        )

        fig, ax = plt.subplots(figsize=(10.8, 4.8))
        fig.subplots_adjust(left=.105, right=.975, top=.71, bottom=.22)
        clean_axes(ax)
        ax.plot(spaced.index, spaced.values, color=COLOR_MAIN,
                linewidth=1.6, solid_capstyle='round',
                label='Valid hourly median DO', zorder=3)

        threshold = float(DO_CUTOFF)
        n_below = int((observed < threshold).sum())
        n_obs = len(observed)
        low = float(observed.min()); high = float(observed.max())
        mid = float(observed.mean())
        pad = max((high - low) * .16, .35)
        ylo, yhi = low - pad, high + pad

        if threshold >= ylo - .15 and threshold <= yhi + .15:
            ylo=min(ylo, threshold - .20)
            ax.axhline(threshold, color=COLOR_ACCENT,
                       lw=1.25, ls=(0, (5, 3)),
                       label=f'Exploratory reference: {threshold:g} mg/L')
        ax.set_ylim(ylo, yhi)
        ax.axhline(mid, color=COLOR_SUB, lw=1, alpha=.7,
                   ls=(0, (2, 4)), label=f'30-day mean: {mid:.2f} mg/L')
        ax.set_ylabel('Dissolved oxygen (mg/L)', labelpad=10)
        ax.set_xlabel('Date (UTC)', labelpad=9)
        ax.set_xlim(spaced.index.min(), spaced.index.max())
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.legend(loc='upper left', bbox_to_anchor=(0.0, 1.045),
                  ncol=2, frameon=False, fontsize=9.2)

        fig.text(.105, .927, 'FIGURE 1  /  ENVIRONMENTAL TIME SERIES',
                 fontsize=9.0, fontweight='bold', color=COLOR_MAIN)
        fig.text(.105, .856,
                 f'Dissolved oxygen before the {site} fish survey',
                 fontsize=16.5, weight='bold', color=COLOR_TEXT)
        fig.text(.105, .790,
                 f'30 days before survey  ·  {date:%d %b %Y} survey date  ·  '
                 f'{n_obs}/{30*24} valid hourly medians ({n_obs/(30*24):.1%} coverage)',
                 fontsize=9.7, color=COLOR_SUB)

        detail = (f'Observed hourly medians: {low:.2f}–{high:.2f} mg/L'
                  f'    |    {n_below}/{n_obs} below exploratory {threshold:g} mg/L reference')
        fig.text(.105, .085, detail, fontsize=9.4, color=COLOR_TEXT)
        fig.text(.105, .040,
                 'NEON DP1.20288.001  ·  QC-passed readings  ·  Exploratory, not a fish-health threshold',
                 fontsize=8.4, color=COLOR_SUB)
        save_scientific_figure(fig, 'Figure_1_Presurvey_Dissolved_Oxygen')
        plt.show()

# --- Plot fish richness and oxygen metrics ---
# Preserve the original exploratory Figure 2: mean DO and DO standard deviation.
window = paired[(paired.window_days == 30) & paired.usable].copy()
if window.empty:
    for alternative in [14, 7]:
        candidate = paired[(paired.window_days == alternative) & paired.usable].copy()
        if len(candidate):
            window = candidate
            break
if window.empty:
    print('Figure 2 skipped: no paired survey events with adequate oxygen coverage.')
else:
    window = window.dropna(subset=['observed_taxa', 'do_mean', 'do_sd']).copy()
    if window.empty:
        print('Figure 2 skipped: paired observations have missing richness or oxygen metrics.')
    else:
        days = int(window.window_days.iloc[0])
        n = len(window)
        ns = window.siteID.nunique()
        sites = sorted(window.siteID.unique())
        default_colors = mpl.colormaps['tab10']
        colors = {s: SITE_COLORS.get(s, default_colors(i % 10))
                  for i, s in enumerate(sites)}
        fig, axs = plt.subplots(1, 2, figsize=(11.8, 5.4), sharey=True)
        fig.subplots_adjust(left=.085, right=.970, top=.70, bottom=.23, wspace=.15)

        for ax, feature, xlabel, letter, label in [
            (axs[0], 'do_mean', 'Mean dissolved oxygen (mg/L)', 'A', 'Average oxygen'),
            (axs[1], 'do_sd', 'Dissolved oxygen SD (mg/L)', 'B', 'Oxygen variability')
        ]:
            clean_axes(ax)
            for site in sites:
                g = window[window.siteID == site]
                ax.scatter(g[feature], g.observed_taxa, s=74,
                           color=colors[site], edgecolor='white', linewidth=1.15,
                           alpha=.96, zorder=5, label=site)
            ax.set_xlabel(xlabel, labelpad=10)
            ax.set_title(f'{letter}   {label}', loc='left', fontsize=12.2,
                         fontweight='bold', pad=15)
            ax.margins(x=.15, y=.15)
            ax.yaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True, nbins=6))
            ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(nbins=5))
        axs[0].set_ylabel('Observed fish-taxon richness', labelpad=10)

        keys = [Line2D([0],[0], marker='o', linestyle='None',
                       markerfacecolor=colors[site], markeredgecolor='white',
                       markersize=9, label=site) for site in sites]
        fig.legend(handles=keys, loc='upper right', bbox_to_anchor=(.972, .783),
                   frameon=False, ncol=max(1, len(keys)),
                   fontsize=9.5, title='NEON site', title_fontsize=9.5)

        frac = pd.to_numeric(window.prop_below_5, errors='coerce')
        valid = frac.notna().sum()
        zeros = int(frac.eq(0).sum())
        if valid > 0 and zeros == valid:
            threshold_note = (f'All {valid} matched windows had 0% of valid hourly medians '
                              f'below {DO_CUTOFF:g} mg/L.')
        elif valid > 0:
            threshold_note = (f'{zeros}/{valid} windows had no valid hourly medians '
                              f'below {DO_CUTOFF:g} mg/L.')
        else:
            threshold_note = f'Low-oxygen frequency below {DO_CUTOFF:g} mg/L was unavailable.'
        fig.text(.085, .927, 'FIGURE 2  /  EXPLORATORY FISH–OXYGEN RELATIONSHIPS',
                 fontsize=9.0, fontweight='bold', color=COLOR_MAIN)
        fig.text(.085, .853, 'Fish richness and pre-survey oxygen conditions',
                 fontsize=16.5, weight='bold', color=COLOR_TEXT)
        fig.text(.085, .785, f'{days}-day windows  ·  {n} survey events  ·  {ns} NEON sites',
                 fontsize=9.7, color=COLOR_SUB)
        fig.text(.085, .098, threshold_note, fontsize=9.5, color=COLOR_TEXT)
        fig.text(.085, .047,
                 'Descriptive only; taxa counts are not adjusted for sampling effort, habitat, or site differences.',
                 fontsize=8.75, color=COLOR_SUB)
        save_scientific_figure(fig, 'Figure_2_Richness_vs_Oxygen_Mean_and_Variability')
        plt.show()

# --- Optional grouped modeling ---
# Leave-one-site-out modeling is skipped if the specified minimum is unmet.
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.metrics import mean_absolute_error, mean_squared_error
model_data = paired[(paired.window_days == 30) & paired.usable].dropna(subset=['observed_taxa']).copy()
model_results = pd.DataFrame()
if len(model_data) < 20 or model_data.siteID.nunique() < 4:
    print(f'Model correctly skipped: {len(model_data)} paired events / {model_data.siteID.nunique()} sites; require >=20 events and >=4 sites.')
    print('To expand the pilot, extend PILOT_SITE_IDS to >=4 sites and set MAX_FISH_MONTHS_PER_SITE >=6 in Setup; re-run all cells.')
else:
    season = pd.get_dummies(model_data['season'], prefix='season', dtype=float)
    base = pd.concat([model_data[['do_mean']].reset_index(drop=True), season.reset_index(drop=True)], axis=1)
    extra = pd.concat([model_data[['do_mean', 'do_p10', 'prop_below_5', 'do_sd']].reset_index(drop=True), season.reset_index(drop=True)], axis=1)
    y = model_data.observed_taxa.to_numpy(dtype=float)
    groups = model_data.siteID.to_numpy()
    cv = LeaveOneGroupOut()
    predictions = []
    for label, features in [('Baseline: mean DO + season', base), ('Plus short-term DO metrics', extra)]:
        preds = np.zeros(len(y))
        for train, test in cv.split(features, y, groups=groups):
            mdl = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge(alpha=10.0))
            mdl.fit(features.iloc[train], y[train])
            preds[test] = mdl.predict(features.iloc[test])
        predictions.append({'model': label, 'n_events': len(y), 'n_sites': len(set(groups)), 'MAE': mean_absolute_error(y, preds), 'RMSE': np.sqrt(mean_squared_error(y, preds))})
    model_results = pd.DataFrame(predictions)
    display(model_results)
    model_results.to_csv(TABLE / 'held_out_site_model_comparison.csv', index=False)
    print('Interpret as exploratory; richer ecological covariates and adequate replication are needed.')

# --- Sensitivity to oxygen reference values ---
sensitivity = []
for ev in fish_events.itertuples():
    if ev.siteID not in series_by_site:
        continue
    s = series_by_site[ev.siteID]
    for days in WINDOWS_DAYS:
        for cutoff in [4.0, 5.0, 6.0]:
            m = metrics_from_hourly(s, ev.date, days, cutoff=cutoff)
            sensitivity.append({'siteID': ev.siteID, 'eventID': ev.eventID, 'window_days': days, 'DO_threshold_mg_L': cutoff, 'fraction_low_DO': m.get('prop_below_5', np.nan), 'coverage': m['coverage']})
sensitivity_df = pd.DataFrame(sensitivity)
sensitivity_df.to_csv(TABLE / 'oxygen_threshold_sensitivity.csv', index=False)
summary = sensitivity_df.groupby(['window_days', 'DO_threshold_mg_L']).agg(n_usable=('fraction_low_DO', 'count'), median_low_fraction=('fraction_low_DO', 'median')).reset_index()
display(summary)

# --- Run summary and export ---
usable30=paired[(paired.window_days==30)&paired.usable]
usable_any=paired[paired.usable]
report=f"""KAS 2027 — NEON fish/oxygen preliminary-data audit
Generated UTC: {datetime.now(timezone.utc).isoformat()}
Fish: {FISH}, {RELEASE} (DOI https://doi.org/10.48443/s1e6-df79)
Water quality: {WATER}, {RELEASE} (DOI https://doi.org/10.48443/15k3-aj25)
Study period: {YEAR_MIN} through {YEAR_MAX}; sites selected: {list(site_month_plan)}
Captured-fish survey events observed: {len(fish_events)}
Sites with captured-fish events: {fish_events.siteID.nunique()}
Matched survey-event + 30-day DO windows (>=70% hourly coverage): {len(usable30)}
Independent sites in adequate 30-day set: {usable30.siteID.nunique()}
Other matched window rows (7,14,30 days combined): {len(usable_any)}
Analytical unit: fish survey event (NOT individual DO sensor readings)
Outcome: provisional observed fish-taxon richness from processed fish + bulk captures.
Cautions: zero-capture surveys not reconstructed; sampling effort not standardized;
no streamflow/temperature adjustment; sensor is not fish microhabitat;
no causal inference; DO<5 mg/L is illustrative and species-specific thresholds vary.
"""
if len(usable30)<20 or usable30.siteID.nunique()<4:
    report+='ASSESSMENT: feasibility pilot only; insufficient independent matched samples for the pre-specified grouped prediction comparison.\n'
else:
    report+='ASSESSMENT: preliminary grouped prediction comparison computed; scientific interpretation requires ecology covariates and follow-up validation.\n'
print(report)
(TABLE/'pilot_report.txt').write_text(report)

assert fish_taxa.captured_count.ge(0).all()
assert paired.loc[paired.usable,'coverage'].ge(MIN_COVERAGE).all()
assert paired.loc[paired.usable,'prop_below_5'].between(0,1).all()

import zipfile
zip_path=OUT/'KAS_NEON_Pilot_Results.zip'
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for folder in [TABLE,FIG]:
        for f in folder.iterdir():
            if f.is_file():
                z.write(f,arcname=f'{folder.name}/{f.name}')
print('Exported tables + figures ZIP:',zip_path)
try:
    from google.colab import files as colab_files
    colab_files.download(zip_path)
except ImportError:
    print('Outside Colab: open the ZIP at',zip_path)
