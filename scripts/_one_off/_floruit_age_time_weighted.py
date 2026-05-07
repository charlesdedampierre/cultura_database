"""Weighted regression: age at floruit ~ time, with each time bin counting equally."""
import re
import sqlite3
import numpy as np
import polars as pl
from scipy import stats

DB = "../data/humans_clean.sqlite3"
AGE_MIN, AGE_MAX = 10, 100
BIN_WIDTH = 500  # 500-year time bins, matches the rest of the notebook

conn = sqlite3.connect(DB)
Q = """
SELECT f.wikidata_id,
       f.floruit_period_start,
       f.floruit_precision,
       i.birthdate
FROM individuals_floruit_period f
JOIN individuals i ON i.wikidata_id = f.wikidata_id
WHERE f.floruit_period_start IS NOT NULL
  AND i.birthdate IS NOT NULL
  AND f.floruit_precision >= 9
"""
raw = pl.read_database(Q, conn)
conn.close()


def signed_year(s):
    if not isinstance(s, str):
        return None
    m = re.match(r"^(-?)(\d+)", s.strip())
    if not m:
        return None
    y = int(m.group(2))
    return -y if m.group(1) == "-" else y


raw = (
    raw.with_columns(
        pl.col("birthdate").map_elements(signed_year, return_dtype=pl.Int64).alias("birth_year")
    )
    .drop_nulls(subset=["birth_year"])
    .with_columns(
        pl.col("birth_year").cast(pl.Int64),
        pl.col("floruit_period_start").cast(pl.Int64),
    )
    .with_columns(
        (pl.col("floruit_period_start") - pl.col("birth_year")).alias("age_at_floruit")
    )
)

plausible = raw.filter(
    (pl.col("age_at_floruit") >= AGE_MIN) & (pl.col("age_at_floruit") <= AGE_MAX)
)

x = plausible["floruit_period_start"].cast(pl.Float64).to_numpy()
y = plausible["age_at_floruit"].cast(pl.Float64).to_numpy()
n = len(x)

# Overall summary stats for the paragraph
print("=== OVERALL DISTRIBUTION (plausible age subset) ===")
print(f"n        = {n:,}")
print(f"mean     = {y.mean():.2f}")
print(f"median   = {np.median(y):.2f}")
print(f"q25      = {np.quantile(y, 0.25):.2f}")
print(f"q75      = {np.quantile(y, 0.75):.2f}")
print(f"std      = {y.std():.2f}")
print()

# Time bins
bins = np.floor(x / BIN_WIDTH).astype(int) * BIN_WIDTH
unique_bins, counts = np.unique(bins, return_counts=True)
count_map = dict(zip(unique_bins, counts))
print(f"n bins (width={BIN_WIDTH}y) = {len(unique_bins)}  range {int(unique_bins.min())}..{int(unique_bins.max())}")
print("counts per bin:")
for b, c in zip(unique_bins, counts):
    print(f"  {int(b):>6d}  n={c:,}")
print()

# Weight = 1 / n_in_bin so each bin sums to 1 (equal weight per time step)
w = np.array([1.0 / count_map[b] for b in bins])

# --- Unweighted (naive) regression for comparison ---
lr = stats.linregress(x, y)
print("=== UNWEIGHTED OLS (each individual = 1) ===")
print(f"slope = {lr.slope:+.6f} yr-of-age per yr-of-time")
print(f"slope (per century) = {lr.slope*100:+.3f}  [95% CI {(lr.slope-1.96*lr.stderr)*100:+.3f}, {(lr.slope+1.96*lr.stderr)*100:+.3f}]")
print(f"intercept = {lr.intercept:+.3f}")
print(f"R^2       = {lr.rvalue**2:.5f}")
print(f"p-value   = {lr.pvalue:.3g}")
print()

# --- Weighted OLS: each time bin counts equally ---
def weighted_linregress(x, y, w):
    sw = w.sum()
    xw = (w * x).sum() / sw
    yw = (w * y).sum() / sw
    dx = x - xw
    dy = y - yw
    Sxx = (w * dx * dx).sum()
    Sxy = (w * dx * dy).sum()
    Syy = (w * dy * dy).sum()
    beta = Sxy / Sxx
    alpha = yw - beta * xw
    yhat = alpha + beta * x
    resid = y - yhat
    rss = (w * resid * resid).sum()
    n_eff = (sw ** 2) / (w * w).sum()  # Kish effective sample size
    df = max(n_eff - 2, 1.0)
    sigma2 = rss / df
    se_beta = float(np.sqrt(sigma2 / Sxx))
    t_stat = float(beta / se_beta)
    p_val = float(2 * (1 - stats.t.cdf(abs(t_stat), df)))
    r2 = float(1 - rss / Syy)
    return dict(slope=float(beta), intercept=float(alpha), se=se_beta,
                t=t_stat, p=p_val, r2=r2, n_eff=float(n_eff), df=float(df))


wls = weighted_linregress(x, y, w)
print("=== EQUAL-WEIGHT-PER-TIME-BIN OLS  (each 500-year bin contributes equally) ===")
print(f"effective n (Kish) = {wls['n_eff']:.1f}   (raw n = {n:,}, n bins = {len(unique_bins)})")
print(f"slope = {wls['slope']:+.6f} yr-of-age per yr-of-time")
print(f"slope (per century) = {wls['slope']*100:+.3f}  [95% CI {(wls['slope']-1.96*wls['se'])*100:+.3f}, {(wls['slope']+1.96*wls['se'])*100:+.3f}]")
print(f"intercept = {wls['intercept']:+.3f}")
print(f"R^2       = {wls['r2']:.5f}")
print(f"t-stat    = {wls['t']:+.3f}")
print(f"p-value   = {wls['p']:.3g}")
print()
verdict = "STATISTICALLY SIGNIFICANT" if wls["p"] < 0.05 else "NOT statistically significant"
print(f"-> Slope (weighted) is {verdict} at alpha=0.05.")
