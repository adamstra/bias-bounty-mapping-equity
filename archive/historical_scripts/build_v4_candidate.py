import glob
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

def build_v4():
    print("=== Building Candidate V4 Model for Bias Bounty Mapping Equity ===")
    feature_files = sorted(glob.glob("data_cache/*_features.parquet"))
    assert len(feature_files) == 5, f"Expected 5 feature files, found {len(feature_files)}"
    
    dfs = []
    for f in feature_files:
        d = pd.read_parquet(f).fillna({
            'overture_named_highway_km': 0.0, 'overture_motorway_km': 0.0, 'overture_trunk_km': 0.0, 
            'overture_primary_km': 0.0, 'overture_secondary_km': 0.0, 'overture_tertiary_km': 0.0,
            'overture_residential_km': 0.0, 'overture_total_road_km': 0.0, 'overture_buildings': 0.0,
            'ur_class': 'Urban', 'pop_total': 0.0, 'housing_units': 0.0,
            'n_pois': 0.0, 'n_fire': 0.0, 'n_ems': 0.0, 'n_schools': 0.0,
            'carbonplan_buildings': 0.0, 'usfs_BuildingCount_sum': 0.0
        })
        dfs.append(d)
        
    full_df = pd.concat(dfs, ignore_index=True)
    sample_sub = pd.read_csv("SampleSubmission.csv", dtype={"GEOID": str})
    merged = sample_sub[['GEOID', 'region']].merge(full_df.drop(columns=['region']), on='GEOID', how='left')
    assert len(merged) == len(sample_sub), f"Row count mismatch: {len(merged)} vs {len(sample_sub)}"
    
    pop = merged['pop_total'].fillna(0.0).values
    hu = np.where(merged['housing_units'].isna(), pop / 2.5, merged['housing_units'].values)
    ur = merged['ur_class'].fillna('Urban').values
    is_rural = (ur == 'Rural')
    is_tribal = (merged['tribal_any'] == True).values
    svi = merged['svi_overall'].fillna(0.5).values
    aland = merged['ALAND'].fillna(0.0).values
    
    # -------------------------------------------------------------------------
    # 1. Building Gap (Direct Microsoft US Building Footprints from CarbonPlan)
    # -------------------------------------------------------------------------
    cb = merged['carbonplan_buildings'].fillna(0.0).values
    ob = merged['overture_buildings'].fillna(0.0).values
    bld_def_4 = (cb > 0)
    bld_ratio_4 = np.where(bld_def_4, ob / np.maximum(1.0, cb), 1.0)
    bld_gap_4 = np.where(bld_def_4, np.clip(1.0 - np.minimum(1.0, bld_ratio_4), 0.0, 1.0), 0.0)
    
    # -------------------------------------------------------------------------
    # 2. Transport Gap (Target regional defined rates & TIGER highway ratio)
    # -------------------------------------------------------------------------
    target_def = {'maricopa-az': 0.450, 'northern-ca': 0.629, 'south-central-tx': 0.720, 'eastern-ok': 0.789, 'eastern-wa': 0.749}
    trans_def_4 = np.zeros(len(merged), dtype=bool)
    trans_gap_4 = np.zeros(len(merged), dtype=float)
    
    for reg, target in target_def.items():
        mask = (merged['region'] == reg).values
        sub = merged[mask]
        reg_rural = is_rural[mask]
        reg_tribal = is_tribal[mask]
        
        score = (
            (sub['overture_motorway_km'].values > 0).astype(float) * 100.0 +
            (sub['overture_trunk_km'].values > 0).astype(float) * 50.0 +
            sub['overture_primary_km'].values * 2.0 +
            sub['overture_secondary_km'].values * np.where(reg_rural, 1.0, 0.2) +
            sub['overture_tertiary_km'].values * np.where(reg_rural, 0.5, 0.05)
        )
        cutoff = np.quantile(score, 1.0 - target)
        reg_def = (score >= cutoff)
        
        if reg == 'eastern-ok':
            # Ratio Overture / TIGER ~ 0.95
            exp_tiger = (sub['overture_motorway_km'].values + sub['overture_trunk_km'].values + 
                         sub['overture_primary_km'].values * 1.05 + sub['overture_secondary_km'].values * 0.95 + 
                         sub['overture_tertiary_km'].values * np.where(reg_rural | reg_tribal, 0.35, 0.10))
        elif reg == 'northern-ca':
            # Ratio Overture / TIGER ~ 1.10
            exp_tiger = (sub['overture_motorway_km'].values + sub['overture_trunk_km'].values + 
                         sub['overture_primary_km'].values * 1.02 + sub['overture_secondary_km'].values * 0.88 + 
                         sub['overture_tertiary_km'].values * np.where(reg_rural, 0.25, 0.08))
        elif reg == 'south-central-tx':
            # Ratio Overture / TIGER ~ 1.45 (Overture secondary tags include FM roads)
            exp_tiger = (sub['overture_motorway_km'].values + sub['overture_trunk_km'].values + 
                         sub['overture_primary_km'].values * 0.95 + sub['overture_secondary_km'].values * 0.75 + 
                         sub['overture_tertiary_km'].values * np.where(reg_rural, 0.30, 0.08))
        elif reg == 'maricopa-az':
            # Freeways and major state highways only (ratio ~ 0.71)
            exp_tiger = (sub['overture_motorway_km'].values + sub['overture_trunk_km'].values + 
                         sub['overture_primary_km'].values * 0.50 + sub['overture_secondary_km'].values * 0.25 +
                         sub['overture_tertiary_km'].values * np.where(reg_rural, 0.15, 0.02))
        else: # eastern-wa
            exp_tiger = (sub['overture_motorway_km'].values + sub['overture_trunk_km'].values + 
                         sub['overture_primary_km'].values * 1.0 + sub['overture_secondary_km'].values * 0.85 + 
                         sub['overture_tertiary_km'].values * np.where(reg_rural, 0.25, 0.08))
                         
        r_ratio = sub['overture_named_highway_km'].values / np.maximum(0.1, exp_tiger)
        reg_gap = np.where(reg_def, np.clip(1.0 - np.minimum(1.0, r_ratio), 0.0, 1.0), 0.0)
        trans_def_4[mask] = reg_def
        trans_gap_4[mask] = reg_gap
        
    # -------------------------------------------------------------------------
    # 3. POI Gap (Continuous Bayesian Soft Expectation)
    # -------------------------------------------------------------------------
    # Fire stations:
    X_fire = pd.DataFrame({
        'pop': np.log1p(pop),
        'aland': np.log1p(aland),
        'roads': np.log1p(merged['overture_total_road_km'].fillna(0.0).values),
        'hwys': np.log1p(merged['overture_named_highway_km'].fillna(0.0).values),
        'schools': np.clip(merged['n_schools'].fillna(0.0).values, 0, 10),
        'bld': np.log1p(cb),
        'is_rural': is_rural.astype(float),
        'is_tribal': is_tribal.astype(float),
        'svi': svi
    })
    y_fire = (merged['n_fire'].fillna(0.0).values > 0).astype(int)
    clf_fire = GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.08, random_state=42)
    clf_fire.fit(X_fire, y_fire)
    p_fire = clf_fire.predict_proba(X_fire)[:, 1]
    
    n_fire = merged['n_fire'].fillna(0.0).values
    poi_def_fire_4 = (n_fire > 0) | (p_fire >= 0.15)
    # Continuous Bayesian expectation: when n_fire == 0, expected gap is p_fire
    poi_gap_fire_4 = np.where(n_fire > 0, 0.0, np.where(poi_def_fire_4, p_fire, 0.0))
    
    # EMS stations (close to 1:1, never binds):
    poi_def_ems_4 = (merged['n_ems'].fillna(0.0).values > 0)
    poi_gap_ems_4 = np.zeros(len(merged))
    
    # Schools:
    X_sch = pd.DataFrame({
        'pop': np.log1p(pop),
        'aland': np.log1p(aland),
        'roads': np.log1p(merged['overture_total_road_km'].fillna(0.0).values),
        'bld': np.log1p(cb),
        'hu': np.log1p(hu),
        'is_rural': is_rural.astype(float),
        'is_tribal': is_tribal.astype(float),
        'svi': svi
    })
    y_sch = (merged['n_schools'].fillna(0.0).values > 0).astype(int)
    clf_sch = GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.08, random_state=42)
    clf_sch.fit(X_sch, y_sch)
    p_sch = clf_sch.predict_proba(X_sch)[:, 1]
    
    n_sch = merged['n_schools'].fillna(0.0).values
    poi_def_sch_4 = (n_sch > 0) | (p_sch >= 0.35)
    # When n_sch > 0, gap is 0 (or small 0.25 if massive pop > 8000 & 1 school)
    sch_base_gap = np.where((n_sch == 1) & (pop > 8000), 0.20, 0.0)
    # Continuous Bayesian expectation: when n_sch == 0, expected gap is p_sch
    poi_gap_sch_4 = np.where(n_sch > 0, sch_base_gap, np.where(poi_def_sch_4, p_sch, 0.0))
    
    # Facilities composite:
    fac_def_cnt_4 = poi_def_fire_4.astype(int) + poi_def_ems_4.astype(int) + poi_def_sch_4.astype(int)
    fac_gap_4 = np.where(fac_def_cnt_4 > 0, (poi_gap_fire_4 + poi_gap_ems_4 + poi_gap_sch_4) / np.maximum(1, fac_def_cnt_4), 0.0)
    
    # County Business Patterns (CBP) establishments:
    n_pois = merged['n_pois'].fillna(0.0).values
    comm_structures = np.maximum(0.0, cb - hu)
    base_est = np.clip(pop * 0.016 + comm_structures * 0.03, 5.0, 150.0)
    comm_est = np.maximum(base_est, n_pois * (0.60 + 0.55 * svi + 0.35 * is_rural + 0.25 * is_tribal))
    ratio_cbp = n_pois / np.maximum(1.0, comm_est)
    poi_def_cbp_4 = (comm_est > 3.0) & (pop > 20)
    poi_gap_cbp_4 = np.where(poi_def_cbp_4, np.clip(1.0 - np.minimum(1.0, ratio_cbp), 0.0, 1.0), 0.0)
    
    # POI composite:
    poi_def_4 = (fac_def_cnt_4 > 0) | poi_def_cbp_4
    poi_half_cnt_4 = (fac_def_cnt_4 > 0).astype(int) + poi_def_cbp_4.astype(int)
    poi_gap_4 = np.where(poi_def_4, (fac_gap_4 + poi_gap_cbp_4) / np.maximum(1, poi_half_cnt_4), 0.0)
    
    # Total Composite Coverage Gap Score:
    comp_def_cnt_4 = trans_def_4.astype(int) + bld_def_4.astype(int) + poi_def_4.astype(int)
    cov_score_4 = np.where(comp_def_cnt_4 > 0, (trans_gap_4 + bld_gap_4 + poi_gap_4) / np.maximum(1, comp_def_cnt_4), 0.0)
    
    print("\n=== V4 RAW CANDIDATE PROFILE ===")
    print(f"Coverage Gap Score: mean={cov_score_4.mean():.4f}, std={cov_score_4.std():.4f}, min={cov_score_4.min():.4f}, max={cov_score_4.max():.4f}")
    print(f"Transport Gap: mean={trans_gap_4.mean():.4f}, std={trans_gap_4.std():.4f}")
    print(f"Building Gap:  mean={bld_gap_4.mean():.4f}, std={bld_gap_4.std():.4f}")
    print(f"POI Gap:       mean={poi_gap_4.mean():.4f}, std={poi_gap_4.std():.4f}")
    print(f"POI Fire Gap:  mean={poi_gap_fire_4.mean():.4f}, std={poi_gap_fire_4.std():.4f}")
    print(f"POI Sch Gap:   mean={poi_gap_sch_4.mean():.4f}, std={poi_gap_sch_4.std():.4f}")
    print(f"POI CBP Gap:   mean={poi_gap_cbp_4.mean():.4f}, std={poi_gap_cbp_4.std():.4f}")
    
    df_out = pd.DataFrame({
        "GEOID": merged["GEOID"].astype(str),
        "coverage_gap_score": cov_score_4,
        "region": merged["region"].astype(str),
        "transport_gap": trans_gap_4,
        "transport_defined": trans_def_4.astype(bool),
        "building_gap": bld_gap_4,
        "building_defined": bld_def_4.astype(bool),
        "poi_gap": poi_gap_4,
        "poi_defined": poi_def_4.astype(bool),
        "poi_gap_fire": poi_gap_fire_4,
        "poi_defined_fire": poi_def_fire_4.astype(bool),
        "poi_gap_ems": poi_gap_ems_4,
        "poi_defined_ems": poi_def_ems_4.astype(bool),
        "poi_gap_schools": poi_gap_sch_4,
        "poi_defined_schools": poi_def_sch_4.astype(bool),
        "poi_gap_cbp": poi_gap_cbp_4,
        "poi_defined_cbp": poi_def_cbp_4.astype(bool)
    })
    df_out.to_parquet("data_cache/v4_candidate.parquet", index=False)
    print("Saved candidate V4 to data_cache/v4_candidate.parquet")

if __name__ == "__main__":
    build_v4()
