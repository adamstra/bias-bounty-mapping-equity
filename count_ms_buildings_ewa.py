import time
import duckdb

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial;")

print("[1/3] Loading Eastern WA tracts...")
t0 = time.time()
con.sql("""
CREATE TABLE tracts AS
SELECT GEOID, ST_GeomFromWKB(ST_AsWKB(geometry)) AS geom
FROM read_parquet('data_cache/eastern-wa-census-tracts.parquet');
""")
n_tracts = con.sql("SELECT count(*) FROM tracts").fetchone()[0]
print(f"Loaded {n_tracts} tracts in {time.time()-t0:.2f}s")

# Eastern WA bounding box: (-122.284435, 45.606098, -116.916071, 49.000916)
print("[2/3] Filtering and centroiding MS Buildings in Eastern WA bounding box...")
t1 = time.time()
con.sql("""
CREATE TABLE ms_east AS
SELECT ST_GeomFromWKB(ST_AsWKB(ST_Centroid(geom))) AS c
FROM ST_Read('data_cache/Washington.geojson')
WHERE ST_XMin(geom) >= -122.35 
  AND ST_XMax(geom) <= -116.90 
  AND ST_YMin(geom) >= 45.60 
  AND ST_YMax(geom) <= 49.05;
""")
n_bldgs = con.sql("SELECT count(*) FROM ms_east").fetchone()[0]
print(f"Found {n_bldgs:,} MS buildings in Eastern WA bounding box in {time.time()-t1:.2f}s")

print("[3/3] Joining MS buildings into tracts via ST_Within...")
t2 = time.time()
res_df = con.sql("""
SELECT t.GEOID, count(b.c) AS ms_n
FROM tracts t
LEFT JOIN ms_east b ON ST_Within(b.c, t.geom)
GROUP BY 1
ORDER BY 1;
""").df()
print(f"Joined across all {len(res_df)} tracts in {time.time()-t2:.2f}s")
print(f"Total MS buildings within tracts: {int(res_df['ms_n'].sum()):,}")
print(f"Tracts with ms_n > 0: {(res_df['ms_n'] > 0).sum()} / {len(res_df)}")
print(res_df.head(10))

res_df.to_csv("data_cache/eastern-wa-ms-buildings-exact.csv", index=False)
print("Saved to data_cache/eastern-wa-ms-buildings-exact.csv")
