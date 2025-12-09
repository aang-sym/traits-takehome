# Traits Insights Take-Home Assessment

ETL pipeline for SkillCorner A-League tracking data analysis.

## Setup

**Prerequisites:**
- Python 3.12+
- Git LFS

**Installation:**

```bash
# Clone repo
git clone https://github.com/aang-sym/traits-takehome.git
cd traits-takehome

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or on windows: venv\Scripts\activate
pip install -r requirements.txt

# Get the SkillCorner data
git lfs install
mkdir -p data
cd data
git clone https://github.com/SkillCorner/opendata.git
git lfs pull
cd ..
```

**Verify setup:**
```bash
ls data/opendata/data/matches/
# Should see 10 match directories
```

## Running

Run notebooks in order:

1. `01_data_loading.ipynb` — Load and inspect SkillCorner raw data  
2. `02_eda.ipynb` — Exploratory data analysis  
3. `03_sprint_quality.ipynb` — Metric 1: Sprint quality and phase context  
4. `04_off_ball_run_value.ipynb` — Metric 2: Off-ball run value  
5. `05_pressing_effectiveness.ipynb` — Metric 3: Pressing effectiveness  
6. `06_combining_metrics.ipynb` — Final player metric unification  
7. `07_validation.ipynb` — Checks and validation of outputs  

## Validation & Testing

I've included basic validation tests in `07_validation.ipynb` that cover:

1. **Source data availability** - Check all 10 matches have required files
2. **Preprocessing consistency** - Verify aggregated CSVs match source data  
3. **Metric range validation** - Sprint/run/press metrics fall within realistic bounds
4. **Cross-metric consistency** - Related metrics correlate as expected

All tests pass for the current dataset.

### Additional Testing for Production Coverage

For a production system, I'd add:

**Data Quality:**
- Null pattern validation and expected missingness checks
- Outlier detection (IQR/z-score) with flagging rather than rejection
- Duplicate detection across match files
- Temporal consistency (same player across matches)
- Join integrity (no orphaned records between tables)

**Schema Validation:**
- Automated checks using `pandera` or `great_expectations`
- Type constraints for all columns
- Range validation for physical measurements (speed/distance/position)
- Enum validation for categorical fields (event types, phases, positions)

**Metric Logic:**
- Unit tests for sprint detection edge cases (frame gaps, speed artifacts)
- Property-based tests for aggregations (e.g., per-90 always positive)
- Benchmark comparisons against published research
- Regression tests to catch algorithm changes

**Performance:**
- Processing time per match (<5 min target)
- Memory profiling for scalability
- Parallel processing validation
- End-to-end pipeline tests with synthetic data

**Integration:**
- Full pipeline tests on new match data
- Output schema validation
- Clean environment notebook execution
- PySpark vs pandas result comparison

These would run as `pytest` suites in CI/CD pipelines.

## Project Structure

```
├── data/                     # Raw SkillCorner OpenData (cloned via Git LFS)
├── docs/                     # PDF docs from SkillCorner + project notes
├── notebooks/                # Analysis notebooks (source of all metric logic)
│   ├── 01_data_loading.ipynb
│   ├── 02_eda.ipynb
│   ├── 03_sprint_quality.ipynb
│   ├── 04_off_ball_run_value.ipynb
│   ├── 05_pressing_effectiveness.ipynb
│   ├── 06_combining_metrics.ipynb
│   └── 07_validation.ipynb
├── output/                   # All intermediate + final aggregated CSVs
│   ├── all_events.csv
│   ├── all_phases.csv
│   ├── player_metadata.csv
│   ├── player_sprints.csv
│   ├── player_runs.csv
│   ├── player_pressing.csv
│   └── player_metrics.csv
├── schemas/                  # Auto-generated JSON schema files for outputs
│   ├── all_events_schema.json
│   ├── all_phases_schema.json
│   ├── player_metadata_schema.json
│   ├── player_sprints_schema.json
│   ├── player_runs_schema.json
│   ├── player_pressing_schema.json
│   └── player_metrics_schema.json
├── src/                      # Python helper modules
│   ├── loaders.py            # Data loading utilities
│   ├── eda.py                # Reusable EDA helpers
│   └── metrics.py            # Metric aggregation functions (Spark)
└── README.md
```

## Data

Uses [SkillCorner Open Data](https://github.com/SkillCorner/opendata) - 10 A-League matches with:
- Match metadata and lineups
- 10fps tracking data (player/ball positions)
- Pre-computed dynamic events
- Game phase classifications