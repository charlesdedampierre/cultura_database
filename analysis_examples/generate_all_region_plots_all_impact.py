"""
Generate dynasty/polity timeline plots for ALL world regions.
Uses individuals_impact_date table (full impact dates for all individuals)
instead of individuals_cliopatria.impact_date (which has NULLs for many).

Saves plots to dynasty_plots_all_impact_dates/ directory.
"""
import sqlite3
import math
import os
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker

matplotlib.rcParams['figure.figsize'] = (18, 10)
matplotlib.rcParams['figure.dpi'] = 120

DB_PATH = '../data/humans_clean.sqlite3'
PLOT_DIR = 'dynasty_plots_all_impact_dates'
TASK_LOG = '../task.log'
os.makedirs(PLOT_DIR, exist_ok=True)


def log(msg):
    print(msg)
    with open(TASK_LOG, 'a') as f:
        f.write(msg + '\n')


def half_century_of(year):
    if year == 0:
        return 0
    return int(math.copysign(1, year)) * (abs(year) // 50) * 50


def precompute_all_distributions(conn):
    """Pre-compute impact year distributions for ALL polities in one pass.
    Joins individuals_cliopatria (polity assignment) with individuals_impact_date
    (full impact dates) to get the year from individuals_impact_date.
    """
    log("[precompute] Loading all polity distributions from individuals_impact_date...")

    cur = conn.execute('''
        SELECT ic.polity_id,
               CASE
                   WHEN iid.impact_date LIKE '-%'
                   THEN -CAST(SUBSTR(iid.impact_date, 2, 4) AS INTEGER)
                   ELSE CAST(SUBSTR(iid.impact_date, 1, 4) AS INTEGER)
               END as year,
               COUNT(*) as cnt
        FROM individuals_cliopatria ic
        JOIN individuals_impact_date iid ON ic.wikidata_id = iid.wikidata_id
        WHERE iid.impact_date IS NOT NULL
        GROUP BY ic.polity_id, year
        ORDER BY ic.polity_id, year
    ''')

    # Build: polity_id -> {half_century_period -> count}
    all_distributions = defaultdict(lambda: defaultdict(int))
    total_rows = 0
    for polity_id, year, cnt in cur:
        if year is None:
            continue
        period = half_century_of(year)
        all_distributions[polity_id][period] += cnt
        total_rows += cnt

    log(f"[precompute] Done: {len(all_distributions)} polities, {total_rows:,} individual-polity rows")
    return all_distributions


def get_time_range(conn, polity_id):
    cur = conn.execute(
        'SELECT MIN(from_year), MAX(to_year) FROM cliopatria_polity_periods WHERE polity_id = ?',
        (polity_id,)
    )
    return cur.fetchone()


def load_region_data(conn, polities, all_distributions):
    data = []
    for pid, name, color, is_major in polities:
        fr, to = get_time_range(conn, pid)
        if fr is None or to is None:
            continue
        periods = dict(all_distributions.get(pid, {}))
        total = sum(periods.values())
        data.append({
            'id': pid, 'name': name, 'color': color, 'is_major': is_major,
            'from': fr, 'to': to, 'periods': periods, 'total': total,
        })
    return data


def plot_timeline_and_lines(data, region_name, xlim, save_name):
    if not data:
        log(f"  SKIP {region_name} - no data")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11),
                                    gridspec_kw={'height_ratios': [1, 1.8]})

    # --- Top panel: timeline bars ---
    y_pos = 0
    for d in data:
        width = d['to'] - d['from']
        alpha = 0.9 if d['is_major'] else 0.5
        lw = 2 if d['is_major'] else 1
        ax1.barh(y_pos, width, left=d['from'], height=0.7,
                 color=d['color'], alpha=alpha, edgecolor='black', linewidth=lw)
        mid = d['from'] + width / 2
        fs = 8 if d['is_major'] else 6
        fw = 'bold' if d['is_major'] else 'normal'
        ax1.text(mid, y_pos, d['name'], ha='center', va='center',
                 fontsize=fs, fontweight=fw, color='white',
                 path_effects=[pe.withStroke(linewidth=2, foreground='black')])
        y_pos += 1

    ax1.set_yticks([])
    ax1.set_title(f"{region_name}",
                  fontsize=14, fontweight='bold', pad=15)
    ax1.set_xlim(*xlim)
    ax1.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    ax1.grid(axis='x', alpha=0.3)
    ax1.set_facecolor('#f8f8f8')
    ax1.invert_yaxis()

    # --- Bottom panel: individuals per 50-year period (log scale) ---
    has_lines = False
    for d in data:
        if d['total'] < 5:
            continue
        pds = sorted([p for p in d['periods'].keys() if xlim[0] <= p <= xlim[1]])
        if not pds:
            continue
        counts = [d['periods'].get(p, 0) for p in pds]
        lw = 2.5 if d['is_major'] else 1.2
        alpha = 0.9 if d['is_major'] else 0.6
        ls = '-' if d['is_major'] else '--'
        ms = 4 if d['is_major'] else 2
        ax2.plot(pds, counts, color=d['color'], linewidth=lw, alpha=alpha,
                 linestyle=ls, marker='o', markersize=ms,
                 label=f"{d['name']} ({d['total']:,})")
        has_lines = True

    if has_lines:
        ax2.set_yscale('log')
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))

    ax2.set_xlabel('Half-Century', fontsize=12)
    ax2.set_ylabel('Number of Individuals (log scale)', fontsize=12)
    ax2.set_xlim(*xlim)
    ax2.axvline(x=0, color='gray', linestyle='--', alpha=0.3)
    ax2.grid(True, alpha=0.3, which='both')
    ax2.set_facecolor('#f8f8f8')

    for d in data:
        if d['is_major']:
            ax2.axvspan(d['from'], d['to'], alpha=0.08, color=d['color'])

    ax2.legend(fontsize=7, loc='upper left', ncol=2, framealpha=0.9)
    plt.tight_layout()

    path = os.path.join(PLOT_DIR, save_name)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    total_ind = sum(d['total'] for d in data)
    log(f"  Saved: {path} ({len(data)} polities, {total_ind:,} individuals)")


# ============================================================
# DEFINE ALL WORLD REGIONS (same as generate_all_region_plots.py)
# ============================================================

ALL_REGIONS = {}

# --- 1. Western Europe ---
ALL_REGIONS['01_western_europe'] = {
    'name': 'Western Europe',
    'xlim': (-600, 1950),
    'polities': [
        (91,   'Roman Republic',     '#8B0000', True),
        (208,  'Roman Empire',       '#DC143C', True),
        (275,  'Western Roman',      '#CD5C5C', False),
        (274,  'Eastern Roman',      '#B22222', False),
        (407,  'Carolingian Empire', '#FF8C00', True),
        (537,  'Kingdom of England', '#2E8B57', True),
        (583,  'Kingdom of France',  '#4169E1', True),
        (527,  'Holy Roman Empire',  '#DAA520', True),
        (351,  'Kingdom of Italy',   '#FF4500', True),
        (425,  'Papal States',       '#9370DB', False),
        (403,  'Republic of Venice', '#20B2AA', False),
        (539,  'Kingdom of Denmark', '#6495ED', False),
        (1003, 'Kingdom of Spain',   '#FF6347', True),
        (695,  'Kingdom of Portugal','#228B22', False),
        (954,  'Habsburg Monarchy',  '#8B4513', True),
        (1048, 'Dutch Republic',     '#FF7F50', False),
        (1102, 'Kingdom of Prussia', '#4682B4', False),
        (772,  'Republic of Florence','#D2691E', False),
    ],
}

# --- 2. Eastern Europe ---
ALL_REGIONS['02_eastern_europe'] = {
    'name': 'Eastern Europe',
    'xlim': (550, 2000),
    'polities': [
        (380,  'Byzantine Empire',      '#9370DB', True),
        (399,  'First Bulgarian Empire', '#CD853F', False),
        (487,  'Kievan Rus',            '#DC143C', True),
        (561,  'Kingdom of Poland',     '#B22222', False),
        (585,  'Kingdom of Hungary',    '#DAA520', False),
        (712,  'Second Bulgarian Empire','#8B4513', False),
        (725,  'Kingdom of Bohemia',    '#556B2F', False),
        (752,  'Grand Duchy of Lithuania','#228B22', False),
        (1030, 'Tsardom of Russia',     '#4682B4', True),
        (1043, 'Polish-Lithuanian',     '#FF8C00', True),
        (1125, 'Russian Empire',        '#FF4500', True),
        (1391, 'Kingdom of Romania',    '#20B2AA', False),
        (1403, 'Soviet Union',          '#B22222', True),
    ],
}

# --- 3. Arab & Islamic World ---
ALL_REGIONS['03_arab_islamic'] = {
    'name': 'Arab & Islamic World',
    'xlim': (550, 1950),
    'polities': [
        (379,  'Rashidun Caliphate',  '#2E8B57', True),
        (388,  'Umayyad Caliphate',  '#DAA520', True),
        (419,  'Abbasid Caliphate',  '#FF8C00', True),
        (489,  'Samanid Empire',     '#6495ED', False),
        (510,  'Fatimid Caliphate',  '#9370DB', False),
        (544,  'Buyid Dynasty',      '#708090', False),
        (560,  'Ghaznavid Empire',   '#CD853F', False),
        (624,  'Great Seljuk Empire','#B22222', True),
        (638,  'Almoravid Dynasty',  '#556B2F', False),
        (693,  'Almohad Caliphate',  '#228B22', False),
        (709,  'Ayyubid Sultanate',  '#4682B4', False),
        (764,  'Mamluk Sultanate',   '#8B4513', False),
        (903,  'Timurid Empire',     '#DC143C', False),
        (842,  'Ottoman Empire',     '#FF4500', True),
        (993,  'Safavid Dynasty',    '#4169E1', True),
        (1165, 'Qajar Dynasty',      '#FFD700', False),
    ],
}

# --- 4. Mesopotamia & Ancient Persia ---
ALL_REGIONS['04_mesopotamia_persia'] = {
    'name': 'Mesopotamia & Ancient Persia',
    'xlim': (-3500, 700),
    'polities': [
        (1,    'Sumerian City-States','#8B4513', True),
        (6,    'Akkadian Empire',    '#DAA520', True),
        (13,   'Babylonia',          '#DC143C', True),
        (11,   'Assyria',            '#B22222', True),
        (31,   'Neo-Assyrian Empire','#FF8C00', True),
        (73,   'Neo-Babylonian',     '#4169E1', True),
        (89,   'Achaemenid Empire',  '#FF4500', True),
        (125,  'Seleucid Empire',    '#9370DB', False),
        (150,  'Parthian Empire',    '#228B22', False),
        (229,  'Sasanian Empire',    '#8B0000', True),
    ],
}

# --- 5. Indian World ---
ALL_REGIONS['05_indian_world'] = {
    'name': 'Indian World',
    'xlim': (-400, 1960),
    'polities': [
        (124,  'Maurya Empire',       '#FF8C00', True),
        (213,  'Kushan Empire',       '#8B4513', False),
        (250,  'Gupta Empire',        '#DAA520', True),
        (424,  'Rashtrakuta Dynasty', '#708090', False),
        (458,  'Chola Empire',        '#B22222', False),
        (746,  'Delhi Sultanate',     '#4169E1', True),
        (877,  'Vijayanagara Empire', '#228B22', True),
        (988,  'Mughal Empire',       '#DC143C', True),
        (1038, 'Kingdom of Mysore',   '#20B2AA', False),
        (1096, 'Maratha Empire',      '#FF4500', False),
        (1182, 'Sikh Empire',         '#FFD700', False),
        (1330, 'British Raj',         '#4682B4', True),
    ],
}

# --- 6. East Asia (Japan & Korea) ---
ALL_REGIONS['06_east_asia_japan_korea'] = {
    'name': 'East Asia (Japan & Korea)',
    'xlim': (-100, 1960),
    'polities': [
        (206,  'Goguryeo',            '#8B4513', False),
        (265,  'Silla',               '#CD853F', False),
        (257,  'Baekje',              '#556B2F', False),
        (330,  'Yamato',              '#DC143C', True),
        (397,  'Unified Silla',       '#DAA520', False),
        (530,  'Goryeo',              '#4169E1', True),
        (716,  'Kamakura Shogunate',  '#B22222', False),
        (734,  'Mongol Empire',       '#FF8C00', True),
        (875,  'Ashikaga Shogunate',  '#228B22', False),
        (916,  'Joseon',              '#9370DB', True),
        (969,  'Warring States Japan','#708090', False),
        (1054, 'Tokugawa Shogunate',  '#FF4500', True),
        (1340, 'Empire of Japan',     '#8B0000', True),
    ],
}

# --- 7. Southeast Asia ---
ALL_REGIONS['07_southeast_asia'] = {
    'name': 'Southeast Asia',
    'xlim': (100, 2030),
    'polities': [
        (223,  'Champa',              '#CD853F', False),
        (394,  'Srivijaya',           '#20B2AA', False),
        (440,  'Khmer Empire',        '#DC143C', True),
        (456,  'Pagan Kingdom',       '#DAA520', True),
        (766,  'Sukhothai Kingdom',   '#4169E1', False),
        (814,  'Majapahit',           '#228B22', True),
        (882,  'Ayutthaya Kingdom',   '#FF8C00', True),
        (897,  'Lan Xang',            '#9370DB', False),
        (994,  'Toungoo Empire',      '#B22222', False),
        (1163, 'Rattanakosin',        '#FF4500', True),
        (1185, 'Dutch East Indies',   '#FF7F50', False),
        (1418, 'Kingdom of Thailand', '#FFD700', True),
        (1445, 'Republic of Indonesia','#DC143C', True),
        (1451, 'Republic of Philippines','#4169E1', True),
        (1516, 'Malaysia',            '#228B22', False),
    ],
}

# --- 8. Africa ---
ALL_REGIONS['08_africa'] = {
    'name': 'Africa (Ancient & Medieval)',
    'xlim': (-3100, 1950),
    'polities': [
        (3,    'Early Dynastic Egypt','#DAA520', False),
        (5,    'Old Kingdom Egypt',   '#CD853F', False),
        (10,   'Middle Kingdom Egypt','#B8860B', False),
        (23,   'New Kingdom Egypt',   '#FF8C00', True),
        (29,   'Kingdom of Kush',     '#8B4513', False),
        (115,  'Ptolemaic Kingdom',   '#4169E1', False),
        (205,  'Kingdom of Axum',     '#228B22', True),
        (757,  'Mali Empire',         '#DC143C', True),
        (791,  'Ethiopian Empire',    '#2E8B57', True),
        (941,  'Kingdom of Kongo',    '#9370DB', False),
        (961,  'Songhai Empire',      '#B22222', True),
        (1058, 'Oyo Empire',          '#FF4500', False),
        (1104, 'Ashanti Empire',      '#FFD700', False),
        (1197, 'Sokoto Caliphate',    '#4682B4', False),
    ],
}

# --- 9. North America ---
ALL_REGIONS['09_north_america'] = {
    'name': 'North America',
    'xlim': (-300, 2030),
    'polities': [
        (149,  'Mayan City-States',   '#228B22', True),
        (938,  'Aztec Triple Alliance','#DC143C', True),
        (949,  'Haudenosaunee',       '#8B4513', False),
        (1057, 'New France',          '#4169E1', False),
        (1060, 'English Colonies',    '#2E8B57', False),
        (1273, 'Mexico (early)',      '#FF8C00', False),
        (1159, 'United States',       '#B22222', True),
        (1343, 'Mexico',              '#228B22', True),
        (1417, 'Canada',              '#FF4500', True),
        (1491, 'Cuba',                '#DAA520', False),
    ],
}

# --- 10. South America ---
ALL_REGIONS['10_south_america'] = {
    'name': 'South America',
    'xlim': (1400, 2030),
    'polities': [
        (940,  'Inca Empire',           '#FF8C00', True),
        (1266, 'Empire of Brazil',      '#228B22', True),
        (1267, 'Gran Colombia',         '#DC143C', True),
        (1234, 'Republic of Chile',     '#B22222', False),
        (1270, 'Republic of Peru',      '#DAA520', False),
        (1283, 'Venezuela',             '#4169E1', False),
        (1274, 'Bolivia',               '#8B4513', False),
        (1286, 'Argentine Confed.',     '#FF4500', False),
        (1278, 'Uruguay',               '#9370DB', False),
        (1285, 'Republic of Ecuador',   '#20B2AA', False),
        (1230, 'Paraguay',              '#556B2F', False),
        (1359, 'Brazilian Republic',    '#2E8B57', True),
        (1414, 'Argentine Republic',    '#CD853F', True),
    ],
}

# --- 11. Oceania ---
ALL_REGIONS['11_oceania'] = {
    'name': 'Oceania',
    'xlim': (1895, 2030),
    'polities': [
        (1435, 'Australia',    '#FF4500', True),
        (1456, 'New Zealand',  '#228B22', True),
        (1446, 'Papua New Guinea', '#DAA520', False),
        (1545, 'Republic of Fiji', '#4169E1', False),
    ],
}

# --- 12. Greek World ---
ALL_REGIONS['12_greek_world'] = {
    'name': 'Greek World',
    'xlim': (-1600, 2030),
    'polities': [
        (22,   'Mycenaean Greece',       '#8B4513', False),
        (35,   'Greek City-States',      '#4169E1', True),
        (61,   'Macedonian Empire',      '#DAA520', True),
        (115,  'Ptolemaic Kingdom',      '#228B22', False),
        (125,  'Seleucid Empire',        '#9370DB', False),
        (142,  'Antigonid Macedonia',    '#708090', False),
        (138,  'Achaean League',         '#CD853F', False),
        (1269, 'First Hellenic Republic','#DC143C', True),
        (1438, 'Kingdom of Greece',      '#FF8C00', False),
        (1553, 'Third Hellenic Republic','#2E8B57', True),
    ],
}

# --- 13. Roman / Latin World ---
ALL_REGIONS['13_roman_world'] = {
    'name': 'Roman / Latin World',
    'xlim': (-800, 1500),
    'polities': [
        (41,   'Etruscans',              '#8B4513', False),
        (91,   'Roman Republic',          '#8B0000', True),
        (208,  'Roman Empire',            '#DC143C', True),
        (275,  'Western Roman Empire',    '#CD5C5C', False),
        (274,  'Eastern Roman Empire',    '#B22222', True),
        (380,  'Byzantine Empire',        '#9370DB', True),
    ],
}

# --- 14. Chinese World ---
ALL_REGIONS['14_chinese_world'] = {
    'name': 'Chinese World',
    'xlim': (-1700, 2030),
    'polities': [
        (20,   'Shang Dynasty',               '#8B4513', False),
        (27,   'Zhou Dynasty',                 '#CD853F', False),
        (153,  'Qin Dynasty',                  '#FF8C00', False),
        (173,  'Han Dynasty',                  '#DC143C', True),
        (232,  'Cao Wei (Three Kingdoms)',      '#708090', False),
        (267,  'Northern Wei',                 '#556B2F', False),
        (355,  'Sui Dynasty',                  '#DAA520', False),
        (371,  'Tang Dynasty',                 '#4169E1', True),
        (559,  'Northern Song',                '#228B22', True),
        (616,  'Southern Song',                '#2E8B57', True),
        (808,  'Yuan Dynasty',                 '#B22222', True),
        (900,  'Ming Dynasty',                 '#FF4500', True),
        (1083, 'Qing Dynasty',                 '#9370DB', True),
        (1373, 'Republic of China',            '#20B2AA', True),
        (1465, "People's Republic of China",   '#8B0000', True),
    ],
}

# ============================================================
# NEW REGIONS (filling gaps in world coverage)
# ============================================================

# --- 15. Nordic & Scandinavian ---
ALL_REGIONS['15_nordic_scandinavian'] = {
    'name': 'Nordic & Scandinavian World',
    'xlim': (700, 2030),
    'polities': [
        (471,  'Old Kingdom of Norway',  '#4169E1', False),
        (539,  'Kingdom of Denmark',     '#DC143C', True),
        (564,  'Kingdom of Sweden',      '#FFD700', True),
        (921,  'Kalmar Union',           '#9370DB', False),
        (1015, 'Denmark-Norway',         '#B22222', False),
        (1239, 'Kingdom of Norway',      '#228B22', True),
        (1250, 'Sweden-Norway',          '#DAA520', False),
        (1386, 'Republic of Finland',    '#20B2AA', True),
        (1441, 'Denmark',               '#FF4500', True),
    ],
}

# --- 16. German World ---
ALL_REGIONS['16_german_world'] = {
    'name': 'German World',
    'xlim': (800, 2030),
    'polities': [
        (527,  'Holy Roman Empire',      '#DAA520', True),
        (886,  'Electorate of Saxony',   '#CD853F', False),
        (954,  'Habsburg Monarchy',      '#8B4513', True),
        (1064, 'Brandenburg-Prussia',    '#708090', False),
        (1102, 'Kingdom of Prussia',     '#4682B4', True),
        (1204, 'Austrian Empire',        '#FF8C00', True),
        (1225, 'Confederation of Rhine', '#556B2F', False),
        (1339, 'Austria-Hungary',        '#B22222', True),
        (1348, 'German Empire',          '#DC143C', True),
        (1399, 'Weimar Republic',        '#FFD700', True),
        (1427, 'Nazi Germany',           '#000000', True),
        (1447, 'Second Rep. Austria',    '#FF4500', False),
        (1464, 'East Germany (GDR)',     '#9370DB', False),
        (1466, 'West Germany (FRG)',     '#228B22', True),
        (1582, 'Federated Rep. Germany', '#2E8B57', True),
    ],
}

# --- 17. British Isles ---
ALL_REGIONS['17_british_isles'] = {
    'name': 'British Isles',
    'xlim': (800, 2030),
    'polities': [
        (537,  'Kingdom of England',       '#DC143C', True),
        (812,  'Kingdom of Scotland',      '#4169E1', True),
        (1085, 'Commonwealth of England',  '#708090', False),
        (1110, 'Kingdom of Great Britain', '#B22222', True),
        (1405, 'Irish Free State',         '#228B22', False),
    ],
}

# --- 18. French World ---
ALL_REGIONS['18_french_world'] = {
    'name': 'French World',
    'xlim': (700, 2030),
    'polities': [
        (407,  'Carolingian Empire',       '#DAA520', True),
        (583,  'Kingdom of France',        '#4169E1', True),
        (1170, 'French First Republic',    '#DC143C', True),
        (1198, 'First French Empire',      '#B22222', True),
        (1311, 'French Second Republic',   '#FF8C00', False),
        (1312, 'Second French Empire',     '#8B4513', False),
        (1345, 'French Third Republic',    '#228B22', True),
        (1432, 'Vichy France',             '#708090', False),
        (1439, 'French Fourth Republic',   '#FF4500', True),
        (1482, 'French Fifth Republic',    '#2E8B57', True),
    ],
}

# --- 19. Iberian World ---
ALL_REGIONS['19_iberian_world'] = {
    'name': 'Iberian World',
    'xlim': (700, 2030),
    'polities': [
        (534,  'Caliphate of Córdoba',   '#DAA520', True),
        (706,  'Crown of Aragon',        '#FF8C00', False),
        (762,  'Crown of Castile',       '#DC143C', False),
        (695,  'Kingdom of Portugal',    '#228B22', True),
        (1003, 'Kingdom of Spain',       '#FF4500', True),
        (1350, 'First Spanish Republic', '#9370DB', False),
        (1369, 'Portuguese Republic',    '#2E8B57', True),
        (1420, 'Second Spanish Republic','#B22222', False),
        (1425, 'Spanish Nationalists',   '#708090', False),
        (1430, 'Francoist Spain',        '#8B4513', True),
        (1562, 'Portugal',               '#4169E1', True),
    ],
}

# --- 20. Italian World ---
ALL_REGIONS['20_italian_world'] = {
    'name': 'Italian World',
    'xlim': (400, 2030),
    'polities': [
        (351,  'Kingdom of Italy',       '#DAA520', True),
        (403,  'Republic of Venice',     '#20B2AA', True),
        (425,  'Papal States',           '#9370DB', True),
        (772,  'Republic of Florence',   '#D2691E', False),
        (960,  'Republic of San Marino', '#228B22', False),
        (1123, 'Kingdom of Sardinia',    '#4682B4', False),
        (1249, 'Kingdom of Two Sicilies','#FF8C00', False),
        (1194, 'Italian Republic',       '#DC143C', True),
        (1444, 'Republic of Italy',      '#2E8B57', True),
    ],
}

# --- 21. Central Asia & Steppe ---
ALL_REGIONS['21_central_asia_steppe'] = {
    'name': 'Central Asia & Steppe',
    'xlim': (500, 2030),
    'polities': [
        (489,  'Samanid Empire',         '#DAA520', False),
        (624,  'Great Seljuk Empire',    '#DC143C', True),
        (663,  'Khwarezmid Dynasty',     '#8B4513', False),
        (734,  'Mongol Empire',          '#FF8C00', True),
        (824,  'Chagatai Khanate',       '#9370DB', False),
        (903,  'Timurid Empire',         '#4169E1', True),
        (968,  'Kazakh Khanate',         '#228B22', False),
        (999,  'Khanate of Khiva',       '#B22222', False),
        (1006, 'Khanate of Bukhara',     '#556B2F', False),
        (1586, 'Kazakhstan',             '#20B2AA', True),
        (1593, 'Mongolia',               '#FF4500', False),
        (1595, 'Kyrgyzstan',             '#708090', False),
        (1602, 'Uzbekistan',             '#4682B4', True),
        (1607, 'Turkmenistan',           '#CD853F', False),
        (1585, 'Tajikistan',             '#FFD700', False),
    ],
}

# --- 22. Modern Middle East ---
ALL_REGIONS['22_modern_middle_east'] = {
    'name': 'Modern Middle East',
    'xlim': (1900, 2030),
    'polities': [
        (1147, 'Kuwait',                 '#4682B4', False),
        (1407, 'Republic of Turkey',     '#DC143C', True),
        (1408, 'Pahlavi Dynasty (Iran)', '#9370DB', True),
        (1419, 'Kingdom of Iraq',        '#DAA520', False),
        (1424, 'Kingdom of Saudi Arabia','#228B22', True),
        (1437, 'Lebanon',               '#FF8C00', False),
        (1454, 'Kingdom of Jordan',      '#CD853F', False),
        (1463, 'State of Israel',        '#4169E1', True),
        (1484, 'Republic of Iraq',       '#B22222', True),
        (1494, 'Republic of Syria',      '#8B4513', False),
        (1543, 'Kingdom of Bahrain',     '#FFD700', False),
        (1548, 'State of Qatar',         '#20B2AA', False),
        (1549, 'United Arab Emirates',   '#FF4500', False),
        (1567, 'Islamic Rep. of Iran',   '#556B2F', True),
        (1578, 'Republic of Yemen',      '#708090', False),
        (1615, 'Arab Republic of Egypt', '#CD5C5C', True),
    ],
}

# --- 23. North Africa ---
ALL_REGIONS['23_north_africa'] = {
    'name': 'North Africa',
    'xlim': (600, 2030),
    'polities': [
        (388,  'Umayyad Caliphate',     '#DAA520', True),
        (436,  'Idrisids',              '#8B4513', False),
        (534,  'Caliphate of Córdoba',  '#FF8C00', False),
        (638,  'Almoravid Dynasty',     '#556B2F', False),
        (693,  'Almohad Caliphate',     '#228B22', True),
        (759,  'Hafsid Dynasty',        '#9370DB', False),
        (842,  'Ottoman Empire',        '#DC143C', True),
        (1093, 'Morocco',               '#2E8B57', True),
        (1196, 'Muhammad Ali dynasty',  '#4169E1', True),
        (1426, 'Kingdom of Egypt',      '#B22222', False),
        (1470, 'Republic of Egypt',     '#FF4500', True),
        (1474, 'Republic of Tunisia',   '#4682B4', True),
        (1514, 'Algeria',               '#FFD700', True),
        (1614, 'State of Libya',        '#CD853F', False),
    ],
}

# --- 24. West Africa (Modern) ---
ALL_REGIONS['24_west_africa'] = {
    'name': 'West Africa',
    'xlim': (1200, 2030),
    'polities': [
        (757,  'Mali Empire',           '#DAA520', True),
        (961,  'Songhai Empire',        '#DC143C', True),
        (1058, 'Oyo Empire',           '#8B4513', False),
        (1104, 'Ashanti Empire',       '#FFD700', False),
        (1197, 'Sokoto Caliphate',     '#9370DB', False),
        (1478, 'Ghana',                '#228B22', True),
        (1492, 'Cameroon',             '#FF8C00', False),
        (1500, "Côte d'Ivoire",        '#B22222', False),
        (1501, 'Senegal',              '#4169E1', True),
        (1505, 'Nigeria',              '#FF4500', True),
        (1509, 'Niger',                '#556B2F', False),
    ],
}

# --- 25. East & Southern Africa ---
ALL_REGIONS['25_east_southern_africa'] = {
    'name': 'East & Southern Africa',
    'xlim': (1300, 2030),
    'polities': [
        (791,  'Ethiopian Empire',      '#228B22', False),
        (1172, 'Merina Kingdom',        '#DAA520', False),
        (1309, 'Republic of Liberia',   '#8B4513', False),
        (1416, 'South Africa',          '#FF4500', True),
        (1434, 'Ethiopia',              '#2E8B57', True),
        (1485, 'Madagascar',            '#9370DB', False),
        (1490, 'Somalia',               '#CD853F', False),
        (1495, 'Tanzania',              '#4169E1', True),
        (1507, 'Dem. Rep. Congo',       '#B22222', True),
        (1510, 'Kenya',                 '#DC143C', True),
        (1511, 'Rwanda',                '#556B2F', False),
        (1517, 'Uganda',                '#FF8C00', True),
        (1520, 'Malawi',                '#20B2AA', False),
        (1525, 'Zambia',                '#4682B4', False),
        (1534, 'Botswana',              '#FFD700', False),
        (1555, 'Mozambique',            '#708090', False),
        (1571, 'Zimbabwe',              '#8B0000', True),
        (1580, 'Namibia',               '#CD5C5C', False),
    ],
}

# --- 26. Balkans ---
ALL_REGIONS['26_balkans'] = {
    'name': 'Balkans',
    'xlim': (1800, 2030),
    'polities': [
        (1269, 'First Hellenic Republic','#4169E1', True),
        (1318, 'Montenegro',            '#708090', False),
        (1329, 'United Principalities',  '#DAA520', False),
        (1387, 'Serbia',                '#DC143C', True),
        (1391, 'Kingdom of Romania',    '#228B22', False),
        (1395, 'Yugoslavia',            '#FF8C00', True),
        (1438, 'Kingdom of Greece',     '#4682B4', False),
        (1442, 'Socialist Albania',     '#B22222', False),
        (1443, 'SFR Yugoslavia',        '#CD853F', True),
        (1461, 'Socialist Romania',     '#9370DB', False),
        (1530, 'Greek junta',           '#556B2F', False),
        (1553, 'Third Hellenic Republic','#2E8B57', True),
        (1577, 'Romania',               '#FFD700', True),
        (1583, 'Republic of Albania',   '#FF4500', False),
        (1587, 'Croatia',               '#20B2AA', True),
        (1590, 'Serbia-Montenegro',     '#8B0000', True),
        (1591, 'Slovenia',              '#4169E1', False),
        (1598, 'Bosnia and Herzegovina','#8B4513', False),
        (1600, 'North Macedonia',       '#CD853F', False),
        (1610, 'Kosovo',                '#228B22', False),
    ],
}

# --- 27. Central Europe ---
ALL_REGIONS['27_central_europe'] = {
    'name': 'Central Europe',
    'xlim': (900, 2030),
    'polities': [
        (585,  'Kingdom of Hungary',     '#DC143C', True),
        (725,  'Kingdom of Bohemia',     '#4169E1', True),
        (954,  'Habsburg Monarchy',      '#DAA520', True),
        (1204, 'Austrian Empire',        '#FF8C00', True),
        (1339, 'Austria-Hungary',        '#B22222', True),
        (1389, 'Czechoslovakia',         '#228B22', True),
        (1397, 'Second Polish Republic', '#9370DB', False),
        (1398, 'Republic of Austria',    '#CD853F', False),
        (1447, 'Second Rep. Austria',    '#FF4500', True),
        (1468, 'Republic of Poland',     '#8B0000', True),
        (1596, 'Slovakia',              '#4682B4', False),
        (1599, 'Czech Republic',        '#2E8B57', True),
    ],
}

# --- 28. Caucasus ---
ALL_REGIONS['28_caucasus'] = {
    'name': 'Caucasus',
    'xlim': (-200, 2030),
    'polities': [
        (118,  'Kingdom of Armenia',       '#DAA520', False),
        (344,  'Georgia',                  '#DC143C', True),
        (591,  'Kingdom of Georgia',       '#FF8C00', False),
        (1143, 'Khanates of Caucasus',     '#708090', False),
        (1384, 'Azerbaijan Dem. Rep.',     '#4169E1', False),
        (1385, 'Armenia',                  '#B22222', False),
        (1589, 'Republic of Armenia',      '#9370DB', True),
        (1597, 'Republic of Azerbaijan',   '#228B22', True),
    ],
}

# --- 29. Caribbean & Central America ---
ALL_REGIONS['29_caribbean_central_america'] = {
    'name': 'Caribbean & Central America',
    'xlim': (1800, 2030),
    'polities': [
        (1171, 'Haiti',                 '#4682B4', True),
        (1293, 'Honduras',              '#DAA520', False),
        (1295, 'Costa Rica',            '#4169E1', False),
        (1296, 'Guatemala',             '#DC143C', True),
        (1299, 'Nicaragua',             '#B22222', False),
        (1300, 'El Salvador',           '#FF8C00', False),
        (1306, 'Dominican Republic',    '#8B4513', True),
        (1367, 'Republic of Cuba',      '#FF4500', True),
        (1368, 'Panama',               '#9370DB', False),
        (1491, 'Cuba',                 '#DC143C', False),
        (1512, 'Jamaica',              '#2E8B57', True),
        (1513, 'Trinidad and Tobago',  '#556B2F', False),
        (1527, 'Barbados',             '#CD853F', False),
    ],
}

# --- 30. Persian World ---
ALL_REGIONS['30_persian_world'] = {
    'name': 'Persian World',
    'xlim': (-600, 2030),
    'polities': [
        (89,   'Achaemenid Empire',    '#FF8C00', True),
        (150,  'Parthian Empire',      '#228B22', True),
        (229,  'Sasanian Empire',      '#8B0000', True),
        (993,  'Safavid Dynasty',      '#4169E1', True),
        (1112, 'Hotaki Dynasty',       '#708090', False),
        (1133, 'Afsharid Iran',        '#CD853F', False),
        (1145, 'Zand Dynasty',         '#DAA520', False),
        (1165, 'Qajar Dynasty',        '#DC143C', True),
        (1408, 'Pahlavi Dynasty',      '#B22222', True),
        (1567, 'Islamic Rep. Iran',    '#556B2F', True),
    ],
}

# --- 31. Baltic States & Finland ---
ALL_REGIONS['31_baltic_states'] = {
    'name': 'Baltic States & Finland',
    'xlim': (1200, 2030),
    'polities': [
        (752,  'Grand Duchy of Lithuania', '#228B22', True),
        (1043, 'Polish-Lithuanian',        '#DAA520', True),
        (1393, 'Kingdom of Lithuania',     '#DC143C', False),
        (1386, 'Republic of Finland',      '#FF4500', True),
        (1396, 'Estonia',                  '#4169E1', False),
        (1400, 'Republic of Latvia',       '#B22222', True),
        (1579, 'Republic of Lithuania',    '#9370DB', True),
        (1603, 'Republic of Estonia',      '#20B2AA', True),
    ],
}

# --- 32. Post-Soviet States ---
ALL_REGIONS['32_post_soviet'] = {
    'name': 'Post-Soviet States',
    'xlim': (1900, 2030),
    'polities': [
        (344,  'Georgia',                '#20B2AA', False),
        (1125, 'Russian Empire',         '#4682B4', True),
        (1403, 'Soviet Union',           '#B22222', True),
        (1586, 'Kazakhstan',             '#FF8C00', True),
        (1589, 'Armenia',                '#9370DB', False),
        (1594, 'Belarus',                '#228B22', True),
        (1597, 'Azerbaijan',             '#FF4500', False),
        (1602, 'Uzbekistan',             '#DAA520', False),
        (1604, 'Moldova',                '#CD853F', False),
        (1605, 'Ukraine',                '#4169E1', True),
        (1606, 'Russian Federation',     '#DC143C', True),
    ],
}


# ============================================================
# MAIN: Generate all plots
# ============================================================

def main():
    # Reset task.log
    if os.path.exists(TASK_LOG):
        os.remove(TASK_LOG)

    log("=== Generating all world region plots (using individuals_impact_date) ===")
    log(f"Total regions to plot: {len(ALL_REGIONS)}")

    conn = sqlite3.connect(DB_PATH)

    # Pre-compute all distributions in one pass (much faster than per-polity queries)
    all_distributions = precompute_all_distributions(conn)

    summary = []
    for key in sorted(ALL_REGIONS.keys()):
        region = ALL_REGIONS[key]
        name = region['name']
        xlim = region['xlim']
        polities = region['polities']
        save_name = f"{key}.png"

        log(f"\n--- {name} ---")
        data = load_region_data(conn, polities, all_distributions)

        # Print summary table
        for d in data:
            fr_s = f"{abs(d['from'])} BCE" if d['from'] < 0 else f"{d['from']} CE"
            to_s = f"{abs(d['to'])} BCE" if d['to'] < 0 else f"{d['to']} CE"
            marker = '*' if d['is_major'] else ' '
            log(f"  {marker} {d['name']:<35s}  {fr_s:>7s} - {to_s:<6s}  {d['total']:>10,d}")

        plot_timeline_and_lines(data, name, xlim, save_name)
        total_ind = sum(d['total'] for d in data)
        summary.append((name, len(data), total_ind))

    # Print final summary
    log(f"\n{'='*80}")
    log(f"  SUMMARY: All World Regions (using individuals_impact_date)")
    log(f"{'='*80}")
    log(f"  {'Region':<35s}  {'Polities':>9s}  {'Individuals':>12s}")
    log(f"  {'-'*60}")
    grand_total = 0
    for name, count, total in summary:
        log(f"  {name:<35s}  {count:>9d}  {total:>12,d}")
        grand_total += total
    log(f"  {'-'*60}")
    log(f"  {'GRAND TOTAL':<35s}  {'':>9s}  {grand_total:>12,d}")
    log(f"\n=== All plots saved to {PLOT_DIR}/ ===")

    conn.close()


if __name__ == '__main__':
    main()
