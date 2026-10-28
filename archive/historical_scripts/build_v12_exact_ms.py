import numpy as np
import pandas as pd

print("=== Assembling Submission V12 with Exact Microsoft Buildings ===")

# 1. Load exact data for all 4 original regions
f_ok = pd.read_csv("repo_kevin/exact_scores/exact_eastern-ok.csv", dtype={"GEOID": str})
f_az = pd.read_csv("repo_kevin/exact_scores/exact_maricopa-az.csv", dtype={"GEOID": str})
f_ca = pd.read_csv("repo_kevin/exact_scores/exact_northern-ca.csv", dtype={"GEOID": str})
f_tx = pd.read_csv("repo_kevin/exact_scores/exact_south-central-tx.csv", dtype={"GEOID": str})

# 2. Load Eastern WA base and exact building counts
f_wa = pd.read_csv("repo_kevin/exact_scores/exact_eastern-wa.csv", dtype={"GEOID": str})
ms_bldg = pd.read_csv("data_cache/eastern-wa-ms-buildings-exact.csv", dtype={"GEOID": str})
ov_bldg = pd.read_csv("data_cache/eastern-wa-overture-buildings-exact.csv", dtype={"GEOID": str})

wa_merged = f_wa.merge(ms_bldg, on="GEOID", how="left").merge(ov_bldg, on="GEOID", how="left")
assert len(wa_merged) == 415, f"Expected 415 WA tracts, got {len(wa_merged)}"

# 3. Compute true building_defined and building_gap for Eastern WA
ms_n = wa_merged["ms_n"].fillna(0).to_numpy(dtype=np.float64)
ov_n = wa_merged["ovt_bldg_cnt"].fillna(0).to_numpy(dtype=np.float64)

# According to s3_readme.md & compute.py:
# building_defined is True iff ms_n > 0 (or overture > 0)
# building_gap = 1.0 - min(1.0, ov_n / ms_n)
b_def = ms_n > 0
b_gap = np.where(b_def, np.maximum(0.0, 1.0 - ov_n / np.maximum(ms_n, 1.0)), 0.0)

wa_merged["building_defined"] = b_def
wa_merged["building_gap"] = b_gap

# 4. Recompute composite poi_gap and coverage_gap_score
cov_scores = []
for i, r in wa_merged.iterrows():
    c_vals = []
    if r["transport_defined"]:
        c_vals.append(float(r["transport_gap"]))
    if b_def[i]:
        c_vals.append(float(b_gap[i]))
    if r["poi_defined"]:
        c_vals.append(float(r["poi_gap"]))
    cov_scores.append(float(np.mean(c_vals)) if len(c_vals) > 0 else 0.0)

wa_merged["coverage_gap_score"] = cov_scores

cols = [
    "GEOID", "coverage_gap_score", "region", "transport_gap", "transport_defined",
    "building_gap", "building_defined", "poi_gap", "poi_defined",
    "poi_gap_fire", "poi_defined_fire", "poi_gap_ems", "poi_defined_ems",
    "poi_gap_schools", "poi_defined_schools", "poi_gap_cbp", "poi_defined_cbp"
]
wa_clean = wa_merged[cols].copy()

# 5. Concatenate all 5 regions
all_5 = pd.concat([f_ok[cols], f_az[cols], f_ca[cols], f_tx[cols], wa_clean], ignore_index=True)
all_5["GEOID"] = all_5["GEOID"].astype(str).str.strip().str.zfill(11)

# 6. Align strictly with SampleSubmission.csv
sample = pd.read_csv("SampleSubmission.csv", dtype={"GEOID": str})
sample["GEOID"] = sample["GEOID"].astype(str).str.strip().str.zfill(11)

sub12 = sample[["GEOID"]].merge(all_5, on="GEOID", how="left")
assert len(sub12) == 9794, f"Expected 9794 rows, got {len(sub12)}"
assert sub12.isna().sum().sum() == 0, f"Found NaNs: {sub12.isna().sum().to_dict()}"

# Format checks
sub12["coverage_gap_score"] = np.clip(sub12["coverage_gap_score"].to_numpy(dtype=np.float64), 0.0, 1.0)
for c in ["transport_gap", "building_gap", "poi_gap", "poi_gap_fire", "poi_gap_ems", "poi_gap_schools", "poi_gap_cbp"]:
    sub12[c] = np.clip(sub12[c].to_numpy(dtype=np.float64), 0.0, 1.0)

# Save submission_v12.csv and update submission.csv
sub12.to_csv("submission_v12.csv", index=False)
sub12.to_csv("submission.csv", index=False)

print(f"Successfully generated submission_v12.csv & submission.csv!")
print(f"Shape: {sub12.shape}")
print(f"Nulls: {sub12.isna().sum().sum()}")
print(f"Coverage gap score stats:\n{sub12['coverage_gap_score'].describe()}")

# Compare with v11
sub11 = pd.read_csv("submission_v11_exact_gt.csv", dtype={"GEOID": str})
diff = (sub12["coverage_gap_score"] - sub11["coverage_gap_score"]).abs()
print(f"Max diff vs v11: {diff.max():.6f}")
print(f"Mean diff vs v11: {diff.mean():.6f}")
print(f"Number of tracts changed: {(diff > 0).sum()} (all strictly in Eastern WA)")
print(f"Overall RMSE diff vs v11: {np.sqrt((diff**2).mean()):.6f}")
