import pandas as pd
import numpy as np

print("=== Building Submission V15 ===")

# 1. Load base exact ground truth (v11)
v11 = pd.read_csv("submission_v11_exact_gt.csv", dtype={"GEOID": str})
v11["GEOID"] = v11["GEOID"].str.strip().str.zfill(11)

# 2. Load newly computed EPSG:5070 exact transport (with restored concurrent routes)
tr = pd.read_csv("data_cache/all_transport_epsg5070_exact.csv", dtype={"GEOID": str})
tr["GEOID"] = tr["GEOID"].str.strip().str.zfill(11)

# Merge transport
df = v11.merge(tr[["GEOID", "transport_gap", "transport_defined"]], on="GEOID", suffixes=("_old", "_new"), how="left")

# Check where transport changed
diff_t = (df["transport_gap_new"] - df["transport_gap_old"]).abs()
print(f"Tracts with modified transport_gap: {(diff_t > 1e-6).sum()} / {len(df)}")
print(f"Max abs diff on transport_gap: {diff_t.max():.6f}")

# Update transport
df["transport_gap"] = df["transport_gap_new"]
df["transport_defined"] = df["transport_defined_new"]

# 3. Update Eastern Washington building gap with exact MS buildings
ms_b = pd.read_csv("data_cache/eastern-wa-ms-buildings-exact.csv", dtype={"GEOID": str})
ov_b = pd.read_csv("data_cache/eastern-wa-overture-buildings-exact.csv", dtype={"GEOID": str})
ms_b["GEOID"] = ms_b["GEOID"].str.zfill(11)
ov_b["GEOID"] = ov_b["GEOID"].str.zfill(11)

ewa_mask = df["region"] == "eastern-wa"
ewa_df = df[ewa_mask].merge(ms_b, on="GEOID", how="left").merge(ov_b, on="GEOID", how="left")
ms_n = ewa_df["ms_n"].fillna(0).to_numpy(dtype=np.float64)
ov_n = ewa_df["ovt_bldg_cnt"].fillna(0).to_numpy(dtype=np.float64)
b_def = ms_n > 0
b_gap = np.where(b_def, np.maximum(0.0, 1.0 - ov_n / np.maximum(ms_n, 1.0)), 0.0)

df.loc[ewa_mask, "building_defined"] = b_def
df.loc[ewa_mask, "building_gap"] = np.round(b_gap, 6)

# 4. Recompute exact composite coverage_gap_score
new_cov = []
for idx, r in df.iterrows():
    c = []
    if r["transport_defined"]: c.append(float(r["transport_gap"]))
    if r["building_defined"]: c.append(float(r["building_gap"]))
    if r["poi_defined"]: c.append(float(r["poi_gap"]))
    new_cov.append(round(float(np.mean(c)), 6) if len(c) > 0 else 0.0)

df["coverage_gap_score"] = new_cov

# 5. Check 4-region statistics
orig = df[df["region"] != "eastern-wa"]
N = len(orig)
assert N == 9379

print("\n=== V15 4-Region Validation ===")
print(f"Count: {N}")
print(f"coverage_gap_score mean: {orig['coverage_gap_score'].mean():.6f} (Target: 0.058436, sum = {orig['coverage_gap_score'].sum():.4f})")
print(f"transport_gap mean:       {orig['transport_gap'].mean():.6f} (Target: 0.111771, sum = {orig['transport_gap'].sum():.4f})")
print(f"building_gap mean:        {orig['building_gap'].mean():.6f} (Target: 0.005601, sum = {orig['building_gap'].sum():.4f})")
print(f"poi_gap mean:             {orig['poi_gap'].mean():.6f} (Target: 0.051414, sum = {orig['poi_gap'].sum():.4f})")

# 6. Format check against SampleSubmission.csv
sample = pd.read_csv("SampleSubmission.csv", dtype={"GEOID": str})
sample["GEOID"] = sample["GEOID"].str.strip().str.zfill(11)

sub15 = sample[["GEOID"]].merge(df, on="GEOID", how="left")
assert len(sub15) == 9794
assert sub15.isna().sum().sum() == 0

# Clip numeric columns to [0, 1]
cols_to_clip = ["coverage_gap_score", "transport_gap", "building_gap", "poi_gap",
                "poi_gap_fire", "poi_gap_ems", "poi_gap_schools", "poi_gap_cbp"]
for col in cols_to_clip:
    sub15[col] = np.clip(sub15[col].to_numpy(dtype=np.float64), 0.0, 1.0)

# Save both 17-column and 2-column versions
cols_17 = list(sample.columns)
sub15[cols_17].to_csv("submission_v15_17col.csv", index=False)

# Also create the 2-column version (Peter / Thibaud format)
sub15_2col = sub15[["GEOID", "coverage_gap_score"]].copy()
sub15_2col.to_csv("submission_v15_2col.csv", index=False)

# By default, update submission.csv with 17-column format (matching SampleSubmission exactly)
sub15[cols_17].to_csv("submission_v15.csv", index=False)
sub15[cols_17].to_csv("submission.csv", index=False)

print("\nSuccessfully wrote submission_v15.csv, submission_v15_2col.csv, and updated submission.csv!")

# Check difference vs v11 and v14
diff_v11 = (sub15["coverage_gap_score"] - pd.read_csv("submission_v11_exact_gt.csv")["coverage_gap_score"]).abs()
diff_v14 = (sub15["coverage_gap_score"] - pd.read_csv("submission_v14.csv")["coverage_gap_score"]).abs()
print(f"Tracts modified vs v11: {(diff_v11 > 1e-6).sum()} / 9794 (mean abs diff: {diff_v11.mean():.6f}, max: {diff_v11.max():.6f})")
print(f"Tracts modified vs v14: {(diff_v14 > 1e-6).sum()} / 9794 (mean abs diff: {diff_v14.mean():.6f}, max: {diff_v14.max():.6f})")
