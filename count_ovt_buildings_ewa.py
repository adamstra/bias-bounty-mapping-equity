import time
import duckdb

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial;")

print("[1/2] Loading Eastern WA tracts...")
t0 = time.time()
con.sql("""
CREATE TABLE tracts AS
SELECT GEOID, ST_GeomFromWKB(ST_AsWKB(geometry)) AS geom
FROM read_parquet('data_cache/eastern-wa-census-tracts.parquet');
""")

print("[2/2] Counting Overture buildings per tract by centroid...")
t1 = time.time()
ovt_df = con.sql("""
WITH ovb AS (
    SELECT ST_GeomFromWKB(ST_AsWKB(ST_Centroid(geometry))) AS c
    FROM read_parquet('data_cache/eastern-wa-overture-buildings.parquet')
)
SELECT t.GEOID, count(b.c) AS ovt_bldg_cnt
FROM tracts t
LEFT JOIN ovb b ON ST_Within(b.c, t.geom)
GROUP BY 1
ORDER BY 1;
""").df()

print(f"Counted across all {len(ovt_df)} tracts in {time.time()-t1:.2f}s")
print(f"Total Overture buildings: {int(ovt_df['ovt_bldg_cnt'].sum()):,}")
print(ovt_df.head(10))

ovt_df.to_csv("data_cache/eastern-wa-overture-buildings-exact.csv", index=False)
print("Saved to data_cache/eastern-wa-overture-buildings-exact.csv")
