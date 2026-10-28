import duckdb
import pandas as pd
import numpy as np
import time

t0 = time.time()
print("=== Computing Exact Transport Gap for All Regions with Full TIGER Concurrent Routes ===")

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial;")
con.sql("SET threads TO 8;")

S3_BASE = "https://data.source.coop/humane-intelligence/bias-bounty-mapping-equity-challenge"

REGIONS_CONFIG = [
    {
        "region": "northern-ca",
        "tracts_url": f"{S3_BASE}/strata/northern-ca/northern-ca-census-tracts.parquet",
        "ovt_url": f"{S3_BASE}/reference/northern-ca/northern-ca-overture-roads.parquet",
        "tiger_shps": ["data_cache/tiger_prisec/tl_2025_06_prisecroads/tl_2025_06_prisecroads.shp"]
    },
    {
        "region": "eastern-ok",
        "tracts_url": f"{S3_BASE}/strata/eastern-ok/eastern-ok-census-tracts.parquet",
        "ovt_url": f"{S3_BASE}/reference/eastern-ok/eastern-ok-overture-roads.parquet",
        "tiger_shps": ["data_cache/tiger_prisec/tl_2025_40_prisecroads/tl_2025_40_prisecroads.shp"]
    },
    {
        "region": "maricopa-az",
        "tracts_url": f"{S3_BASE}/strata/maricopa-az/maricopa-az-census-tracts.parquet",
        "ovt_url": f"{S3_BASE}/reference/maricopa-az/maricopa-az-overture-roads.parquet",
        "tiger_shps": [
            "data_cache/tiger_prisec/tl_2025_04_prisecroads/tl_2025_04_prisecroads.shp",
            "data_cache/tiger_prisec/tl_2025_35_prisecroads/tl_2025_35_prisecroads.shp"
        ]
    },
    {
        "region": "south-central-tx",
        "tracts_url": f"{S3_BASE}/strata/south-central-tx/south-central-tx-census-tracts.parquet",
        "ovt_url": f"{S3_BASE}/reference/south-central-tx/south-central-tx-overture-roads.parquet",
        "tiger_shps": ["data_cache/tiger_prisec/tl_2025_48_prisecroads/tl_2025_48_prisecroads.shp"]
    },
    {
        "region": "eastern-wa",
        "tracts_url": f"{S3_BASE}/strata/eastern-wa/eastern-wa-census-tracts.parquet",
        "ovt_url": f"{S3_BASE}/reference/eastern-wa/eastern-wa-overture-roads.parquet",
        "tiger_shps": ["data_cache/tiger_prisec/tl_2025_53_prisecroads/tl_2025_53_prisecroads.shp"]
    }
]

dfs = []
for cfg in REGIONS_CONFIG:
    reg = cfg["region"]
    r_t0 = time.time()
    print(f"\nProcessing {reg}...")

    con.sql(f"""
        CREATE OR REPLACE TABLE tracts AS
        SELECT GEOID, ST_GeomFromWKB(ST_AsWKB(geometry)) as geom
        FROM read_parquet('{cfg["tracts_url"]}')
    """)

    min_x, min_y, max_x, max_y = con.sql("""
        SELECT min(ST_XMin(geom)), min(ST_YMin(geom)), max(ST_XMax(geom)), max(ST_YMax(geom)) FROM tracts
    """).fetchone()

    # Union all state shapefiles for this region
    tiger_queries = []
    for shp in cfg["tiger_shps"]:
        tiger_queries.append(f"""
            SELECT ST_GeomFromWKB(ST_AsWKB(geom)) as geom
            FROM ST_Read('{shp}')
            WHERE MTFCC IN ('S1100', 'S1200')
              AND ST_Intersects(geom, ST_MakeEnvelope({min_x}, {min_y}, {max_x}, {max_y}))
        """)
    union_sql = " UNION ALL ".join(tiger_queries)
    con.sql(f"CREATE OR REPLACE TABLE tiger AS {union_sql}")

    con.sql(f"""
        CREATE OR REPLACE TABLE overture AS
        SELECT ST_GeomFromWKB(ST_AsWKB(geometry)) as geom
        FROM read_parquet('{cfg["ovt_url"]}')
        WHERE class IN ('motorway', 'trunk', 'primary', 'secondary')
    """)

    res = con.sql("""
        WITH kt AS (
            SELECT t.GEOID,
                   sum(ST_Length(ST_Transform(ST_Intersection(r.geom, t.geom), 'EPSG:4326', 'EPSG:5070', always_xy := true))) / 1000.0 as tiger_km
            FROM tracts t
            JOIN tiger r ON ST_Intersects(r.geom, t.geom)
            GROUP BY t.GEOID
        ),
        ko AS (
            SELECT t.GEOID,
                   sum(ST_Length(ST_Transform(ST_Intersection(r.geom, t.geom), 'EPSG:4326', 'EPSG:5070', always_xy := true))) / 1000.0 as overture_km
            FROM tracts t
            JOIN overture r ON ST_Intersects(r.geom, t.geom)
            GROUP BY t.GEOID
        )
        SELECT t.GEOID,
               coalesce(kt.tiger_km, 0.0) as tiger_km,
               coalesce(ko.overture_km, 0.0) as overture_km,
               (coalesce(kt.tiger_km, 0.0) > 0.0) as transport_defined,
               CASE WHEN coalesce(kt.tiger_km, 0.0) > 0.0
                    THEN 1.0 - least(1.0, coalesce(ko.overture_km, 0.0) / kt.tiger_km)
                    ELSE 0.0
               END as transport_gap
        FROM tracts t
        LEFT JOIN kt USING (GEOID)
        LEFT JOIN ko USING (GEOID)
    """).df()

    res["region"] = reg
    res["GEOID"] = res["GEOID"].astype(str).str.strip().str.zfill(11)
    dfs.append(res)
    print(f"  {reg}: {len(res)} tracts ({res['transport_defined'].sum()} defined, {(~res['transport_defined']).sum()} undefined) in {time.time()-r_t0:.2f}s")

all_transport = pd.concat(dfs, ignore_index=True)
all_transport.to_csv("data_cache/all_transport_restored_exact.csv", index=False)
print(f"\nSuccessfully computed exact transport for all {len(all_transport)} tracts in {time.time()-t0:.2f}s!")
