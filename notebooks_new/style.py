"""Shared figure style for every notebook in notebooks_new.

Usage, in the config cell of a notebook:

    from style import *
    apply_style()
"""

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

BLUE = '#5b8fc7'
DARK_BLUE = '#3f6f9f'
LIGHT_BLUE = '#a9cbe8'
PALE_BLUE = '#d9e4ef'
ORANGE = '#e39b5b'
LIGHT_ORANGE = '#f3cf9f'
GREEN = '#6fb07f'
LIGHT_GREEN = '#b5dbb0'
PURPLE = '#a58cc7'
LIGHT_PURPLE = '#cfc9e0'
RED = '#c46a5a'
PINK = '#f4b6b0'
NAVY = '#1f3a5f'
TEAL = '#0f766e'
LIGHT_TEAL = '#cce7e2'
SLATE = '#6b7d8f'
GREY = '#8c8c8c'
LIGHT_GREY = '#d3d7dc'
PALE_GREY = '#ececec'
SILVER = '#b9bfc8'
TEXT = '#333333'
MUTED_TEXT = '#888888'

GRID_COLOR = PALE_GREY
REFERENCE_LINE_COLOR = GREY
MAP_COLORMAP = 'YlGnBu'
BACKGROUND_COLOR = 'white'

MAIN_COLOR = BLUE
MAIN_LINE_COLOR = DARK_BLUE
NEUTRAL_BAR_COLOR = SLATE
POINT_CLOUD_COLOR = SILVER
HIGHLIGHT_COLOR = RED
BAND_ALPHA = 0.2
REFERENCE_LINE = {'color': REFERENCE_LINE_COLOR, 'linestyle': ':', 'linewidth': 0.8}

FONT_FAMILY = 'DejaVu Sans'
FIGSIZE = (12, 5)
FIGSIZE_WIDE = (15, 6)
FIGSIZE_GRID = (14, 9)

DATABASE_COLORS = {
    'cultura': BLUE,
    'cross_verified': ORANGE,
    'pantheon_2': GREEN,
}

COVERAGE_COLORS = {
    'western_catalog': BLUE,
    'non_western_catalog': ORANGE,
    'international_catalog': GREEN,
    'western_wikipedia': LIGHT_BLUE,
    'non_western_wikipedia': LIGHT_ORANGE,
    'both_catalogs': GREY,
    'both_wikipedias': LIGHT_PURPLE,
    'no_catalog_no_wiki': PALE_GREY,
}
LIGHT_COLORS = {LIGHT_BLUE, LIGHT_ORANGE, LIGHT_PURPLE, PALE_GREY, PALE_BLUE, LIGHT_GREY, LIGHT_GREEN}

OCCUPATION_COLORS = {
    'Culture': BLUE,
    'Discovery/Science': GREEN,
    'Leadership': ORANGE,
    'Sports/Games': PURPLE,
}

METHOD_COLORS = {
    'Floruit (P1317)': RED,
    'Works span': BLUE,
    'Single work': LIGHT_BLUE,
    'Birth + death': ORANGE,
    'Birth only': LIGHT_ORANGE,
    'Death only': LIGHT_PURPLE,
    'No window': LIGHT_GREY,
}

ERA_COLORS = {
    'before 500': RED,
    '500 – 1500': ORANGE,
    '1500 – 1800': GREEN,
    '1800 – 1900': BLUE,
    'after 1900': PURPLE,
}

PRECISION_COLORS = {
    'year': BLUE,
    'decade': LIGHT_ORANGE,
    'century': PALE_BLUE,
}

CHINESE_POLITY_COLORS = {
    'Shang': '#6c2a2c', 'Zhou': '#8e4f33', 'Qin': '#b07a3f', 'Han': '#c8a472',
    'Six Dynasties': '#8e7a8a', 'Sui': '#6c8a8a', 'Tang': '#4f8a98', 'Five Dynasties': '#5b6f8e',
    'Song': '#3e5b8e', 'Yuan': '#6a4f8a', 'Ming': '#8e4f7a', 'Qing': '#a05a6a',
}

POLITY_MATCH_COLORS = {
    'with_polity': GREEN,
    'without_polity': ORANGE,
}

TABLE_FONT_BODY = 14
TABLE_FONT_HEAD = 15

VALUE_LABEL_FONTSIZE = 12
POINT_LABEL_FONTSIZE = 11
LONG_TICK_LABEL_FONTSIZE = 12
SMALL_LEGEND_FONTSIZE = 11
PANEL_LABEL_FONTSIZE = 16
DONUT_CENTER_FONTSIZE = 20
PLOTLY_FONT = {'family': FONT_FAMILY, 'size': 15, 'color': TEXT}

THOUSANDS = FuncFormatter(lambda x, _: f'{x:,.0f}')
PERCENT = FuncFormatter(lambda x, _: f'{x:.0f}%')


def apply_style():
    plt.rcParams.update({
        'figure.dpi': 120,
        'figure.figsize': FIGSIZE,
        'font.family': FONT_FAMILY,
        'font.size': 14,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'axes.titlesize': 16,
        'axes.titlecolor': 'black',
        'axes.labelsize': 16,
        'axes.grid': False,
        'axes.axisbelow': True,
        'grid.color': GRID_COLOR,
        'grid.linewidth': 0.8,
        'xtick.labelsize': 14,
        'ytick.labelsize': 14,
        'legend.fontsize': 13,
        'legend.frameon': False,
        'lines.linewidth': 2,
        'axes.formatter.useoffset': False,
        'axes.formatter.limits': (-99, 99),
    })


def text_color_on(color):
    return TEXT if color in LIGHT_COLORS else 'white'


def categorical_palette(names):
    colors = list(plt.cm.tab20.colors) + list(plt.cm.tab20b.colors) + list(plt.cm.tab20c.colors)
    return {name: colors[i % len(colors)] for i, name in enumerate(names)}


def hex_to_rgba(hex_color, alpha):
    r, g, b = (int(hex_color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
    return f'rgba({r},{g},{b},{alpha})'
