"""
Compute Economic Complexity Index (ECI) per (polity, century).

For each century t and polity i:
    N_ik,t = sum over active individuals of HPI weight
              for individuals with occupation k associated with polity i
              and floruit_year falling in century t
    HPI weight = distinct catalog count = COUNT(DISTINCT property_id)
                 in the identifiers table for that individual
    M_ik,t = 1 if RCA = (N_ik / N_i) / (N_k / N) >= 1 else 0
    Then iterate:
        ECI_i = (1/M_i.) sum_k M_ik PCI_k
        PCI_k = (1/M_.k) sum_i M_ik ECI_i
    Implemented via the eigenvector-of-M~M' formulation (Hidalgo & Hausmann).

Output: data/eci_polity_century.parquet with columns
    polity_id, polity_name, century, n_individuals, total_hpi, eci, diversity
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "humans_clean.sqlite3"
OUT = ROOT / "data" / "eci_polity_century.parquet"


def century_of(year: int) -> int:
    """Return century bin label (year // 100). E.g. 1850 -> 18, 50 -> 0, -50 -> -1."""
    return int(np.floor(year / 100.0))


def load_data(con: sqlite3.Connection) -> pd.DataFrame:
    """Pull (wikidata_id, polity_id, polity_name, century, occupation, hpi)
    for every active individual, exploded across polities and occupations."""

    print("[1/4] Loading HPI (distinct catalogs per individual)...")
    hpi = pd.read_sql_query(
        """
        SELECT wikidata_id, COUNT(DISTINCT property_id) AS hpi
        FROM identifiers
        GROUP BY wikidata_id
        """,
        con,
    )
    print(f"      {len(hpi):,} individuals with at least one catalog")

    print("[2/4] Loading polity assignments + occupations + floruit_year...")
    df = pd.read_sql_query(
        """
        SELECT ic.wikidata_id,
               ic.polity_id,
               ic.polity_name,
               ic.floruit_year,
               i.occupations_en
          FROM individuals_cliopatria ic
          JOIN individuals i ON i.wikidata_id = ic.wikidata_id
         WHERE ic.floruit_year IS NOT NULL
           AND i.occupations_en IS NOT NULL
           AND i.occupations_en <> ''
        """,
        con,
    )
    print(f"      {len(df):,} (individual, origin) rows")

    df = df.merge(hpi, on="wikidata_id", how="left")
    df["hpi"] = df["hpi"].fillna(0).astype(np.int32)

    print("[3/4] Exploding multi-polity rows (semicolon-separated)...")
    df["polity_id"] = df["polity_id"].astype(str).str.split(";")
    df["polity_name"] = df["polity_name"].astype(str).str.split(";")
    df = df.explode(["polity_id", "polity_name"], ignore_index=True)
    df["polity_id"] = df["polity_id"].str.strip()
    df["polity_name"] = df["polity_name"].str.strip()
    df = df[df["polity_id"] != ""]

    # An individual associated with the same polity through multiple origin
    # types (birthplace + citizenship + deathplace) should count once.
    df = df.drop_duplicates(subset=["wikidata_id", "polity_id"])
    print(f"      {len(df):,} unique (individual, polity) pairs")

    print("[4/4] Exploding occupations (semicolon-separated)...")
    df["occupation"] = df["occupations_en"].str.split(";")
    df = df.drop(columns=["occupations_en"]).explode("occupation", ignore_index=True)
    df["occupation"] = df["occupation"].str.strip()
    df = df[df["occupation"].astype(bool)]

    df["century"] = df["floruit_year"].astype(int).map(century_of)
    df = df[["wikidata_id", "polity_id", "polity_name", "century", "occupation", "hpi"]]
    print(f"      {len(df):,} (individual, polity, occupation) rows after explode")
    return df


def compute_eci_one_century(
    cell_df: pd.DataFrame,
) -> pd.DataFrame:
    """Given a long DataFrame with columns (polity_id, occupation, weight) for one
    century, return per-polity (eci, diversity, total_weight)."""

    polities = cell_df["polity_id"].unique()
    occupations = cell_df["occupation"].unique()
    if len(polities) < 2 or len(occupations) < 2:
        return pd.DataFrame(
            {
                "polity_id": polities,
                "eci": np.nan,
                "diversity": np.nan,
                "total_hpi": cell_df.groupby("polity_id")["weight"].sum().reindex(polities).values,
            }
        )

    pidx = {p: i for i, p in enumerate(polities)}
    oidx = {o: j for j, o in enumerate(occupations)}
    rows = cell_df["polity_id"].map(pidx).values
    cols = cell_df["occupation"].map(oidx).values
    vals = cell_df["weight"].values.astype(np.float64)

    N = csr_matrix(
        (vals, (rows, cols)), shape=(len(polities), len(occupations))
    ).toarray()

    Ni = N.sum(axis=1, keepdims=True)
    Nk = N.sum(axis=0, keepdims=True)
    Ntot = N.sum()
    if Ntot == 0:
        return pd.DataFrame()

    with np.errstate(divide="ignore", invalid="ignore"):
        rca = (N / Ni) / (Nk / Ntot)
        rca = np.nan_to_num(rca, nan=0.0, posinf=0.0, neginf=0.0)
    M = (rca >= 1).astype(np.float64)

    diversity_full = M.sum(axis=1)        # M_i. (before pruning)
    # Iteratively prune polities/occupations with diversity/ubiquity <= 1.
    # Such "isolated" nodes form disconnected components in the bipartite
    # specialisation graph and produce degenerate eigenvectors (spikes
    # localised on a single polity), which is the well-known failure mode
    # of the method-of-reflections on sparse data.
    keep_p = np.ones(M.shape[0], dtype=bool)
    keep_o = np.ones(M.shape[1], dtype=bool)
    for _ in range(50):
        Mp = M[np.ix_(keep_p, keep_o)]
        div_p = Mp.sum(axis=1)
        ubi_o = Mp.sum(axis=0)
        bad_p = div_p <= 1
        bad_o = ubi_o <= 1
        if not bad_p.any() and not bad_o.any():
            break
        kp_idx = np.where(keep_p)[0]
        ko_idx = np.where(keep_o)[0]
        keep_p[kp_idx[bad_p]] = False
        keep_o[ko_idx[bad_o]] = False
    if keep_p.sum() < 3 or keep_o.sum() < 3:
        return pd.DataFrame(
            {
                "polity_id": polities,
                "eci": np.nan,
                "diversity": diversity_full,
                "total_hpi": N.sum(axis=1),
            }
        )

    Mp = M[np.ix_(keep_p, keep_o)]
    div_p = Mp.sum(axis=1)
    ubi_o = Mp.sum(axis=0)

    # Method of reflections eigenvalue formulation:
    #   M_tilde[i,i'] = sum_k (M_ik * M_i'k) / (div_i * ubi_k)
    # ECI is the eigenvector of M_tilde corresponding to the second-largest
    # eigenvalue (the largest is trivially 1 with constant eigenvector).
    Dinv = 1.0 / div_p
    Uinv = 1.0 / ubi_o
    # row-stochastic: P_pp' = sum_k M_ik / div_i * M_i'k / ubi_k
    A = (Mp * Dinv[:, None]) @ (Mp * Uinv[None, :]).T
    # symmetric eigendecomp via similarity is not exact; use plain eig.
    w, v = np.linalg.eig(A)
    order = np.argsort(-w.real)
    # second-largest eigenvalue
    eci_vec = v[:, order[1]].real
    # Standard sign convention: align with diversity (more diverse -> higher ECI).
    if np.corrcoef(eci_vec, div_p)[0, 1] < 0:
        eci_vec = -eci_vec
    # z-score
    eci_vec = (eci_vec - eci_vec.mean()) / (eci_vec.std() + 1e-12)

    eci_full = np.full(len(polities), np.nan)
    eci_full[np.where(keep_p)[0]] = eci_vec

    return pd.DataFrame(
        {
            "polity_id": polities,
            "eci": eci_full,
            "diversity": diversity_full,
            "total_hpi": N.sum(axis=1),
        }
    )


def main() -> None:
    with sqlite3.connect(DB) as con:
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
        long_df = load_data(con)

    name_map = (
        long_df[["polity_id", "polity_name"]]
        .dropna()
        .drop_duplicates("polity_id")
        .set_index("polity_id")["polity_name"]
    )

    # weight per (polity, occupation, century, individual) is the individual's
    # HPI; we want N_ik,t = sum over individuals.  Group once.
    grouped = (
        long_df.groupby(["century", "polity_id", "occupation"], as_index=False)["hpi"]
        .sum()
        .rename(columns={"hpi": "weight"})
    )
    n_indiv = (
        long_df.groupby(["century", "polity_id"])["wikidata_id"]
        .nunique()
        .rename("n_individuals")
        .reset_index()
    )

    centuries = sorted(grouped["century"].unique())
    print(f"\nComputing ECI for {len(centuries)} centuries...")

    results = []
    for c in tqdm(centuries, desc="centuries"):
        sub = grouped[grouped["century"] == c][["polity_id", "occupation", "weight"]]
        out = compute_eci_one_century(sub)
        if out.empty:
            continue
        out["century"] = c
        results.append(out)

    res = pd.concat(results, ignore_index=True)
    res = res.merge(n_indiv, on=["century", "polity_id"], how="left")
    res["polity_name"] = res["polity_id"].map(name_map)
    res = res[
        ["century", "polity_id", "polity_name", "n_individuals", "total_hpi", "diversity", "eci"]
    ].sort_values(["century", "eci"], ascending=[True, False])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(OUT, index=False)
    print(f"\nWrote {len(res):,} rows to {OUT}")
    print(res.head(10))
    print("...")
    print(res.tail(5))


if __name__ == "__main__":
    main()
