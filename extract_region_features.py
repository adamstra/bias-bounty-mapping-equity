import sys
import time
import duckdb
import pandas as pd

def extract_features_for_region(region):
    print(f"=== Extracting features for region: {region} ===")
    t_start = time.time()
    
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    con.sql("INSTALL spatial; LOAD spatial;")
    con.sql("SET s3_region='us-west-2';")
    con.sql("SET s3_url_style='path';")
    
    BASE_S3 = "s3://us-west-2.opendata.source.coop/humane-intelligence/bias-bounty-mapping-equity-challenge"
    
    # 1. Authoritative sample submission tracts
    print("Reading sample submission...")
    sub_path = f"{BASE_S3}/reference/{region}/{region}-sample-submission.csv"
    df_sub = con.sql(f"SELECT * FROM read_csv('{sub_path}', types={{'GEOID': 'VARCHAR'}});").df()
    print(f"Authoritative scored tracts: {len(df_sub)}")
    
    # 2. Strata tract table
    print("Reading strata tract table...")
    strata_path = f"{BASE_S3}/strata/{region}/{region}-strata-tract-table.parquet"
    df_strata = con.sql(f"""
        SELECT 
            GEOID, STATEFP, COUNTYFP, ALAND, pop_total, pop_urban, pop_rural, pct_urban, ur_class,
            svi_covered, svi_overall, svi_socioeconomic, svi_household, svi_minority, svi_housing_transport,
            cvi_covered, cvi_overall, cvi_baseline, cvi_climate, cvi_baseline_health, cvi_baseline_infrastructure,
            ruca_primary, rucc_2023, nchs_2013, tribal_any, tribal_pct,
            carbonplan_covered, carbonplan_buildings, carbonplan_crps_mean, carbonplan_rps_2011_mean,
            usfs_covered, usfs_BuildingCount_sum, usfs_BuildingDensity_mean, usfs_HUCount_sum, usfs_WHP_mean, usfs_RPS_mean,
            epht_heat_days_summer, gehe_wbgt32_days_mean, usdm_summer_dsci, pmdi_mean
        FROM '{strata_path}'
    """).df()
    
    # 3. Census ACS housing
    print("Reading ACS housing...")
    acs_path = f"{BASE_S3}/reference/{region}/{region}-census-acs-housing.parquet"
    df_acs = con.sql(f"SELECT GEOID, housing_units FROM '{acs_path}'").df()
    
    # 4. POIs aggregation
    print("Aggregating POIs per tract...")
    t0 = time.time()
    tracts_geom = f"{BASE_S3}/strata/{region}/{region}-census-tracts.parquet"
    pois_path = f"{BASE_S3}/reference/{region}/{region}-overture-pois.parquet"
    
    df_pois = con.sql(f"""
        SELECT 
            t.GEOID,
            count(p.geometry) AS n_pois,
            count(CASE WHEN p.categories.primary = 'fire_department' THEN 1 END) AS n_fire,
            count(CASE WHEN p.categories.primary = 'ambulance_and_ems_services' THEN 1 END) AS n_ems,
            count(CASE WHEN p.categories.primary IN ('elementary_school', 'middle_school', 'high_school', 'school', 'private_school', 'public_school') THEN 1 END) AS n_schools
        FROM '{tracts_geom}' t
        LEFT JOIN '{pois_path}' p
          ON ST_Intersects(t.geometry, p.geometry)
        GROUP BY t.GEOID
    """).df()
    print(f"POIs aggregated in {time.time() - t0:.2f} s")
    
    # 5. Roads aggregation
    print("Aggregating Roads per tract...")
    t0 = time.time()
    roads_path = f"{BASE_S3}/reference/{region}/{region}-overture-roads.parquet"
    
    df_roads = con.sql(f"""
        WITH filtered_roads AS (
            SELECT 
                class,
                geometry
            FROM '{roads_path}'
        )
        SELECT 
            t.GEOID,
            COALESCE(sum(CASE WHEN r.class IN ('motorway', 'trunk', 'primary', 'secondary') 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_named_highway_km,
            COALESCE(sum(CASE WHEN r.class = 'motorway' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_motorway_km,
            COALESCE(sum(CASE WHEN r.class = 'trunk' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_trunk_km,
            COALESCE(sum(CASE WHEN r.class = 'primary' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_primary_km,
            COALESCE(sum(CASE WHEN r.class = 'secondary' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_secondary_km,
            COALESCE(sum(CASE WHEN r.class = 'tertiary' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_tertiary_km,
            COALESCE(sum(CASE WHEN r.class = 'residential' 
                              THEN ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0 END), 0.0) AS overture_residential_km,
            COALESCE(sum(ST_Length(ST_Transform(ST_Intersection(t.geometry, r.geometry), 'EPSG:4326', 'EPSG:5070', always_xy := true)) / 1000.0), 0.0) AS overture_total_road_km,
            count(CASE WHEN r.class IN ('motorway', 'trunk', 'primary', 'secondary') THEN 1 END) AS n_highway_segments,
            count(CASE WHEN r.class = 'motorway' THEN 1 END) AS n_motorway_segments,
            count(CASE WHEN r.class = 'trunk' THEN 1 END) AS n_trunk_segments,
            count(CASE WHEN r.class = 'primary' THEN 1 END) AS n_primary_segments,
            count(CASE WHEN r.class = 'secondary' THEN 1 END) AS n_secondary_segments
        FROM '{tracts_geom}' t
        LEFT JOIN filtered_roads r
          ON ST_Intersects(t.geometry, r.geometry)
        GROUP BY t.GEOID
    """).df()
    print(f"Roads aggregated in {time.time() - t0:.2f} s")
    
    # 6. Buildings aggregation
    print("Aggregating Buildings per tract...")
    t0 = time.time()
    bld_path = f"{BASE_S3}/reference/{region}/{region}-overture-buildings.parquet"
    df_bld = con.sql(f"""
        WITH bld_points AS (
            SELECT ST_Point((bbox.xmin + bbox.xmax)/2.0, (bbox.ymin + bbox.ymax)/2.0) AS pt
            FROM '{bld_path}'
        )
        SELECT 
            t.GEOID,
            count(b.pt) AS overture_buildings
        FROM '{tracts_geom}' t
        LEFT JOIN bld_points b
          ON ST_Intersects(t.geometry, b.pt)
        GROUP BY t.GEOID
    """).df()
    print(f"Buildings aggregated in {time.time() - t0:.2f} s")
    
    # Merge all components together on GEOID
    print("Merging extracted features...")
    if 'region' not in df_sub.columns:
        df_sub['region'] = region
    df_merged = df_sub[['GEOID', 'region']].merge(df_strata, on='GEOID', how='left')
    df_merged = df_merged.merge(df_acs, on='GEOID', how='left')
    df_merged = df_merged.merge(df_pois, on='GEOID', how='left')
    df_merged = df_merged.merge(df_roads, on='GEOID', how='left')
    df_merged = df_merged.merge(df_bld, on='GEOID', how='left')
    
    out_path = f"data_cache/{region}_features.parquet"
    df_merged.to_parquet(out_path, index=False)
    print(f"Successfully saved {len(df_merged)} rows to {out_path} in {time.time() - t_start:.2f} s total.")
    return df_merged

if __name__ == "__main__":
    reg = sys.argv[1] if len(sys.argv) > 1 else "northern-ca"
    extract_features_for_region(reg)
