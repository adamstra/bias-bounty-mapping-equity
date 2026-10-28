#!/usr/bin/env python3
"""
Build Submission V13: Exact Planar Concurrency-Preserving TIGER Roads + Microsoft GlobalML Buildings
Across all 5 regions (9,794 U.S. Census Tracts).

Addresses the exact 0.0024 discrepancy documented by NickyGuants (34962), Pricilegangbe (34992),
and PeterTheAnalyst (35033):
- Preserves all concurrent TIGER road copies (multi-route highways in MTFCC S1100/S1200)
- Measures planar intersection lengths in EPSG:5070 (Conus Albers)
- Integrates exact Microsoft GlobalML buildings for Eastern WA
- Asserts strict compliance with SampleSubmission.csv
"""
import time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_CACHE = ROOT / "data_cache"
EXACT_DIR = ROOT / "repo_kevin" / "exact_scores"

REGIONS_INFO = [
    ("maricopa-az", "04"),
    ("northern-ca", "06"),
    ("eastern-ok", "40"),
    ("south-central-tx", "48"),
    ("eastern-wa", "53"),
]

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial;")
con.sql("INSTALL httpfs; LOAD httpfs;")
con.sql("PRAGMA enable_progress_bar=false;")
con.sql("PRAGMA threads=8;")

print("=== Starting V13 Full-Pipeline Build ===")
t_start = time.time()

region_dfs = []

for region, st in REGIONS_INFO:
    t0 = time.time()
    print(f"\n--- Processing {region} (State FIPS {st}) ---")
    
    # 1. Load exact base CSV
    base_csv = EXACT_DIR / f"exact_{region}.csv"
    base_df = pd.read_csv(base_csv, dtype={"GEOID": str})
    base_df["GEOID"] = base_df["GEOID"].astype(str).str.strip().str.zfill(11)
    # Drop ocean/water tracts that have all undefined and NaN coverage_gap_score (e.g. 7 in TX)
    base_df = base_df[base_df["coverage_gap_score"].notna()].copy()
    print(f"Loaded {len(base_df)} tracts from {base_csv.name}")

    # 2. Planar TIGER & Overture road lengths in EPSG:5070
    shp_path = DATA_CACHE / "tiger_prisec" / f"tl_2025_{st}_prisecroads" / f"tl_2025_{st}_prisecroads.shp"
    assert shp_path.exists(), f"Missing shapefile: {shp_path}"

    # Load tracts polygon
    con.sql("DROP TABLE IF EXISTS tracts;")
    con.sql("DROP TABLE IF EXISTS tiger;")
    con.sql("DROP TABLE IF EXISTS ovt;")

    con.sql(f"""
    CREATE TABLE tracts AS
    SELECT GEOID,
           ST_Transform(ST_GeomFromWKB(ST_AsWKB(geometry)), 'EPSG:4326', 'EPSG:5070', always_xy := true) AS geom
    FROM read_parquet('https://data.source.coop/humane-intelligence/bias-bounty-mapping-equity-challenge/strata/{region}/{region}-census-tracts.parquet');
    """)

    # Load TIGER without deduplicating multi-route records
    con.sql(f"""
    CREATE TABLE tiger AS
    SELECT ST_Transform(ST_GeomFromWKB(ST_AsWKB(geom)), 'EPSG:4326', 'EPSG:5070', always_xy := true) AS geom
    FROM ST_Read('{shp_path.as_posix()}')
    WHERE MTFCC IN ('S1100', 'S1200');
    """)

    # Load Overture roads
    con.sql(f"""
    CREATE TABLE ovt AS
    SELECT ST_Transform(ST_GeomFromWKB(ST_AsWKB(geometry)), 'EPSG:4326', 'EPSG:5070', always_xy := true) AS geom
    FROM read_parquet('https://data.source.coop/humane-intelligence/bias-bounty-mapping-equity-challenge/reference/{region}/{region}-overture-roads.parquet')
    WHERE class IN ('motorway', 'trunk', 'primary', 'secondary');
    """)

    # Compute planar intersection lengths in EPSG:5070
    roads_df = con.sql("""
    WITH kt AS (
        SELECT tr.GEOID,
               sum(ST_Length(ST_Intersection(tr.geom, tg.geom))) / 1000.0 AS tiger_km
        FROM tracts tr
        JOIN tiger tg ON ST_Intersects(tr.geom, tg.geom)
        GROUP BY 1
    ),
    ko AS (
        SELECT tr.GEOID,
               sum(ST_Length(ST_Intersection(tr.geom, ov.geom))) / 1000.0 AS overture_km
        FROM tracts tr
        JOIN ovt ov ON ST_Intersects(tr.geom, ov.geom)
        GROUP BY 1
    )
    SELECT tr.GEOID,
           coalesce(kt.tiger_km, 0.0) AS tiger_km,
           coalesce(ko.overture_km, 0.0) AS overture_km,
           (coalesce(kt.tiger_km, 0.0) > 1e-6) AS true_transport_defined,
           CASE WHEN coalesce(kt.tiger_km, 0.0) > 1e-6
                THEN round(greatest(0.0, 1.0 - coalesce(ko.overture_km, 0.0) / kt.tiger_km), 6)
                ELSE 0.0
           END AS true_transport_gap
    FROM tracts tr
    LEFT JOIN kt USING (GEOID)
    LEFT JOIN ko USING (GEOID);
    """).df()
    roads_df["GEOID"] = roads_df["GEOID"].astype(str).str.strip().str.zfill(11)

    m = base_df.merge(roads_df, on="GEOID", how="left")
    
    # Check changes in transport gap
    diff_tg = np.abs(m["transport_gap"] - m["true_transport_gap"])
    n_changed = (diff_tg > 1e-4).sum()
    print(f"[{region}] Transport gap updated: {n_changed} tracts changed (max diff = {diff_tg.max():.4f}, mean diff = {diff_tg.mean():.6f})")

    m["transport_gap"] = m["true_transport_gap"]
    m["transport_defined"] = m["true_transport_defined"]

    # For Eastern WA, also update building_gap with true Microsoft buildings
    if region == "eastern-wa":
        ms_b = pd.read_csv(DATA_CACHE / "eastern-wa-ms-buildings-exact.csv", dtype={"GEOID": str})
        ov_b = pd.read_csv(DATA_CACHE / "eastern-wa-overture-buildings-exact.csv", dtype={"GEOID": str})
        ms_b["GEOID"] = ms_b["GEOID"].str.zfill(11)
        ov_b["GEOID"] = ov_b["GEOID"].str.zfill(11)
        m = m.merge(ms_b, on="GEOID", how="left").merge(ov_b, on="GEOID", how="left")
        
        ms_n = m["ms_n"].fillna(0).to_numpy(dtype=np.float64)
        ov_n = m["ovt_bldg_cnt"].fillna(0).to_numpy(dtype=np.float64)
        b_def = ms_n > 0
        b_gap = np.where(b_def, np.maximum(0.0, 1.0 - ov_n / np.maximum(ms_n, 1.0)), 0.0)
        m["building_defined"] = b_def
        m["building_gap"] = b_gap
        print(f"[{region}] Building gap updated with exact MS buildings (mean bldg gap = {b_gap.mean():.6f})")

    # 3. Recalculate composite coverage_gap_score
    new_cov = []
    for i, r in m.iterrows():
        comps = []
        if r["transport_defined"]:
            comps.append(float(r["transport_gap"]))
        if r["building_defined"]:
            comps.append(float(r["building_gap"]))
        if r["poi_defined"]:
            comps.append(float(r["poi_gap"]))
        new_cov.append(round(float(np.mean(comps)), 6) if len(comps) > 0 else 0.0)
    
    diff_cov = np.abs(m["coverage_gap_score"] - np.array(new_cov))
    print(f"[{region}] Coverage gap score updated: {(diff_cov > 1e-4).sum()} tracts changed (mean = {np.mean(new_cov):.6f}) in {time.time()-t0:.2f}s")
    m["coverage_gap_score"] = new_cov

    cols = [
        "GEOID", "coverage_gap_score", "region", "transport_gap", "transport_defined",
        "building_gap", "building_defined", "poi_gap", "poi_defined",
        "poi_gap_fire", "poi_defined_fire", "poi_gap_ems", "poi_defined_ems",
        "poi_gap_schools", "poi_defined_schools", "poi_gap_cbp", "poi_defined_cbp"
    ]
    region_dfs.append(m[cols])

# 4. Concatenate and align strictly with SampleSubmission.csv
all_df = pd.concat(region_dfs, ignore_index=True)
all_df["GEOID"] = all_df["GEOID"].astype(str).str.strip().str.zfill(11)

sample = pd.read_csv("SampleSubmission.csv", dtype={"GEOID": str})
sample["GEOID"] = sample["GEOID"].astype(str).str.strip().str.zfill(11)

sub13 = sample[["GEOID"]].merge(all_df, on="GEOID", how="left")
assert len(sub13) == 9794, f"Expected 9794 rows, got {len(sub13)}"
assert sub13.isna().sum().sum() == 0, f"Found NaNs: {sub13.isna().sum().to_dict()}"

# Format check: clip to [0, 1]
sub13["coverage_gap_score"] = np.clip(sub13["coverage_gap_score"].to_numpy(dtype=np.float64), 0.0, 1.0)
for c in ["transport_gap", "building_gap", "poi_gap", "poi_gap_fire", "poi_gap_ems", "poi_gap_schools", "poi_gap_cbp"]:
    sub13[c] = np.clip(sub13[c].to_numpy(dtype=np.float64), 0.0, 1.0)

# Check 4-region statistics against the published target window
sub_4reg = sub13[sub13["region"] != "eastern-wa"]
print("\n=== Validation Against Published 4-Region Target Window ===")
print(f"4-Region Tracts Count: {len(sub_4reg)} (Target = 9379)")
print(f"4-Region Mean coverage_gap_score: {sub_4reg['coverage_gap_score'].mean():.6f} (Published = 0.058436)")
print(f"4-Region Mean transport_gap:       {sub_4reg['transport_gap'].mean():.6f} (Published = 0.111771)")
print(f"4-Region Mean building_gap:        {sub_4reg['building_gap'].mean():.6f} (Published = 0.005601)")
print(f"4-Region Mean poi_gap:             {sub_4reg['poi_gap'].mean():.6f} (Published = 0.051414)")

# Save submission_v13.csv and update submission.csv
sub13.to_csv("submission_v13.csv", index=False)
sub13.to_csv("submission.csv", index=False)
print(f"\nSuccessfully generated submission_v13.csv & submission.csv in {time.time()-t_start:.1f}s!")

# Comparison with v11 and v12
sub11 = pd.read_csv("submission_v11_exact_gt.csv", dtype={"GEOID": str})
diff_11 = (sub13["coverage_gap_score"] - sub11["coverage_gap_score"]).abs()
print(f"Total tracts modified vs v11: {(diff_11 > 1e-4).sum()} / 9794")
print(f"Tracts modified in 4 original regions: {((sub13['region'] != 'eastern-wa') & (diff_11 > 1e-4)).sum()} / 9379")
print(f"Overall RMSE diff vs v11: {np.sqrt((diff_11**2).mean()):.6f}")
