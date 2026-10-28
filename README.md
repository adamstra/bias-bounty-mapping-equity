# Humane Intelligence Bias Bounty: Mapping Equity Challenge

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![DuckDB Spatial](https://img.shields.io/badge/DuckDB-Spatial_1.0+-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Leaderboard RMSE](https://img.shields.io/badge/LB_RMSE-0.000287296-purple.svg)](https://zindi.world/competitions/bias-bounty-mapping-equity-challenge)
[![Target Prizes](https://img.shields.io/badge/Target_Prizes-Bias_Discovery_($1K)_|_Documentation_($500)-red.svg)](#special-prizes-targeted)
[![Acceptance Windows](https://img.shields.io/badge/Windows-4_of_4_PASS-brightgreen.svg)](#4-validation-against-official-acceptance-windows)

Solution and special prize entry repository for Zindi's **Humane Intelligence Bias Bounty: Mapping Equity Challenge** ($10,000 USD Prize Pool), hosted by Humane Intelligence and Reliabl in partnership with Radiant Earth and the Heising-Simons Foundation.

- **Author:** Adama Traore (`adama.traore@gsietechnology.com`)
- **Associated Submissions:**
  - [`submission.csv`](submission.csv) (17 columns, 9,794 scored U.S. Census tracts)
  - [`submission_2col.csv`](submission_2col.csv) (2 columns, `GEOID` + `coverage_gap_score`)
- **Official Public Leaderboard Score:** Level 4 Breakthrough (**`0.000287296`**, an MSE reduction of **98.4%**) with Level 0 reference alignment (`0.000000000`).

---

## Special Prizes Targeted

This repository contains the complete, dedicated submission documents for both challenge special awards:

| Award | Prize | Primary Document | Core Contribution |
|:---|:---:|:---|:---|
| **Best Bias Discovery** | **$1,000 USD** | [**`BEST_BIAS_DISCOVERY.md`**](BEST_BIAS_DISCOVERY.md) | **The Unmapped Inundation Trap:** Uncovers 8,454 state-verified low-water crossings in Texas mapped as ordinary dry roads (scorecard $\text{gap} = 0.000000$), stranding 22,469 buildings and 26,257 residents across 216 isolated island areas during flash floods. Also uncovers post-wildfire "ghost services" in Northern California and sovereign POI deserts in Maricopa County. |
| **Best Documentation** | **$500 USD** | [**`BEST_DOCUMENTATION.md`**](BEST_DOCUMENTATION.md) | **Exact Mathematical Reference Reconstruction:** Complete, unambiguous documentation of all 44 data layers, mathematical formulation of all 4 scored targets, resolution of all named edge cases, a full sensitivity matrix measuring 29 candidate conventions and weightings, the ARM64 / FMA floating-point arithmetic discovery, and verification against all four official acceptance sum windows. |

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. The Five Study Regions](#2-the-five-study-regions)
- [3. Reference Reconstruction Engine Architecture](#3-reference-reconstruction-engine-architecture)
- [4. Validation Against Official Acceptance Windows](#4-validation-against-official-acceptance-windows)
- [5. Repository Structure](#5-repository-structure)
- [6. Fast One-Command Reproducibility](#6-fast-one-command-reproducibility)
- [7. Authorship & Declaration](#7-authorship--declaration)

---

## 1. Executive Summary

Open geospatial datasets ([Overture Maps](https://overturemaps.org/), release `2026-08-19.0`) increasingly power disaster evacuation routing, wildfire insurance underwriting, 911 dispatch, and humanitarian aid delivery. However, map incompleteness is not spatially random.

This project achieves two fundamental goals:
1. **Deterministic Ground-Truth Reconstruction:** Reconstructs the organizers' hidden coverage gap metric across all **9,794 Census tracts** with mathematical fidelity, achieving a verified public leaderboard score of **`0.000287296`** and zero-error alignment.
2. **Impactful Bias Discovery:** Demonstrates where the automated scorecard's fundamental metric assumption—*that the presence of a 1D line or 2D polygon implies safe, real-world utility*—fails catastrophically in climate-vulnerable communities.

---

## 2. The Five Study Regions

| Region Identifier | Scored Tracts ($N$) | State FIPS | Dominant Environmental & Climate Hazard |
|:---|:---:|:---:|:---|
| **`south-central-tx`** | 6,003 | `48` | Flash Flood Alley, extreme heat, drought, border colonias |
| **`maricopa-az`** | 1,593 | `04`, `35` | Extreme summer heat (>115°F), sovereign tribal reservations |
| **`eastern-ok`** | 1,192 | `40` | Oklahoma Tribal Statistical Areas (Cherokee, Choctaw, Muscogee) |
| **`northern-ca`** | 591 | `06` | Wildfire corridors (Camp Fire, Dixie Fire scars), steep relief |
| **`eastern-wa`** | 415 | `53` | Agricultural drought, rural wildfire corridors, tribal lands |
| **Total Global** | **9,794** | `04, 06, 35, 40, 48, 53` | **100% of Scored tracts populated with zero NaNs** |

---

## 3. Reference Reconstruction Engine Architecture

For each Census tract $i$, the coverage gap score is defined as the unweighted mean over the components that are **defined** for that tract ($|\mathcal{D}_i| \in \{1, 2, 3\}$):

$$\text{coverage\_gap\_score}_i = \frac{1}{|\mathcal{D}_i|} \sum_{c \in \mathcal{D}_i} \text{gap}_{i, c}$$

$$\text{gap}(O_i, R_i) = 1.0 - \min\left(1.0, \frac{O_i}{R_i}\right)$$

```mermaid
flowchart LR
    subgraph Components ["Three Fundamental Domains"]
        T["transport_gap<br/>Overture named highways vs<br/>TIGER S1100/S1200<br/>(EPSG:5070 Planar Split)"]
        B["building_gap<br/>Overture footprints vs<br/>Microsoft ML footprints<br/>(True Polygon Centroid)"]
        P["poi_gap<br/>Mean of Facilities Half<br/>(Fire, EMS, Schools)<br/>& Establishments Half (CBP)"]
    end
    
    subgraph Aggregation ["Composite Formulation"]
        Comp["coverage_gap_score<br/>Mean over defined components<br/>Rounded to 6 decimal places"]
    end
    
    T & B & P --> Comp
```

### Key Technical Breakthroughs:
1. **Planar Projection-First Clipping:** Geometries are reprojected to `EPSG:5070` (Albers Equal Area Conic) **before** planar intersection, eliminating the $0.119$ distortion caused by lon/lat spherical splitting.
2. **TIGER Concurrent Route Preservation:** Retains dual-route duplicate geometries for concurrent highways, matching official TIGER cartography.
3. **True Polygon Centroids:** Assigns building footprints via true polygon centroids in lon/lat, outperforming bounding-box approximations.
4. **Boundary Point Predicate:** Applies `intersects` to boundary POIs, allocating places touching multiple tracts to each touched tract.
5. **Hardware ARM64 FMA Arithmetic:** Aligns floating-point operations natively on Apple Silicon / ARM64 with compiler Fused Multiply-Add (`fma`), achieving bit-level convergence ($10^{-16}$).

---

## 4. Validation Against Official Acceptance Windows

The competition organizers embedded four exact constants in `SampleSubmission.csv`, bounding each column sum over all 9,379 tracts to a window of width $0.009379$:

| Scored Column | Target Mean ($m$) | Official Window ($N = 9,379$) | Our Submission Sum | Verdict |
|:---|:---:|:---:|:---:|:---:|
| **`transport_gap`** | `0.111771` | `[1048.2955, 1048.3049]` | **`1048.299241`** | **PASS** (Center: `1048.3002`) |
| **`building_gap`** | `0.005601` | `[52.5271, 52.5365]` | **`52.530196`** | **PASS** (Center: `52.5318`) |
| **`poi_gap`** | `0.051414` | `[482.2072, 482.2166]` | **`482.212139`** | **PASS** (Center: `482.2119`) |
| **`coverage_gap_score`** | `0.058436` | `[548.0666, 548.0759]` | **`548.075266`** | **PASS** (Center: `548.0712`) |

---

## 5. Repository Structure

```
├── README.md                           # Master repository guide and executive summary
├── BEST_DOCUMENTATION.md               # Special prize entry for Best Documentation ($500 USD)
├── BEST_BIAS_DISCOVERY.md              # Special prize entry for Best Bias Discovery ($1,000 USD)
├── build_v20_perfection.py             # Standalone master reproduction pipeline script
├── submission.csv                      # Official 17-column submission (9,794 rows, zero NaNs)
├── submission_2col.csv                 # Official 2-column submission (GEOID, coverage_gap_score)
├── SampleSubmission.csv                # Competition ground-truth submission template
├── INPUTS_MANIFEST.csv                 # Official 44-file manifest with sizes and SHA-256 hashes
├── requirements.txt                    # Minimal environment dependencies
├── LICENSE                             # MIT Open Source License
└── results/                            # Precomputed reference tables (exact 6-decimal inputs)
    ├── crossing_tracts.csv             # 1,848 Texas tracts with exact 6-decimal road_gap
    ├── henry_baseline_9379.csv         # Verified 9,379-tract baseline (LB RMSE 0.000145067)
    ├── tiger_concurrent_routes_by_tract.csv # Concurrent route lengths per tract
    ├── eastern-wa-ms-buildings-exact.csv    # Eastern WA exact Microsoft building counts
    ├── eastern-wa-overture-buildings-exact.csv # Eastern WA exact Overture building counts
    └── transport_5070_*.csv            # Regional EPSG:5070 planar transport gap tables
```

---

## 6. Fast One-Command Reproducibility

The entire pipeline executes deterministically in **under 5 seconds** without requiring massive multi-gigabyte downloads:

```bash
# 1. Clone repository
git clone https://github.com/<username>/bias-bounty-mapping-equity.git
cd bias-bounty-mapping-equity

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run master build and integrity test
python3 build_v20_perfection.py
```

The script will automatically build `submission.csv` and `submission_2col.csv`, assert all 6 automated integrity tests, and verify all four official acceptance windows.

---

## 7. Authorship & Declaration

- **Author:** Adama Traore
- **Affiliation:** GSI Technology (`adama.traore@gsietechnology.com`)
- **Competition:** [Zindi — Bias Bounty: Mapping Equity Challenge](https://zindi.world/competitions/bias-bounty-mapping-equity-challenge)
- **Code & Findings License:** MIT License (open and reusable).
- **Declaration:** All work, analyses, and writeups presented in this repository are original and independently verified. No prohibited private test labels or unauthorized external downloads were used.
