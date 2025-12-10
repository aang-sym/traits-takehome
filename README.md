# Traits Insights Take-Home – SkillCorner ETL

This repo contains a small ETL pipeline built on SkillCorner’s open A-League tracking + events data.  
The goal is to load the ten matches, run some light EDA, define three sets of player‑level metrics (sprints, off‑ball runs, pressing), and output a single `player_metrics` table for analysis.

It’s a local prototype designed for clarity. The notebooks show the full process end‑to‑end, and the helper functions make it easy to see how this would map into a script or Spark job.

---

## Setup

### Requirements
- Python 3.12+
- Git LFS  
- ~16 GB RAM recommended when running Spark on the tracking files.

### Installation

```bash
git clone https://github.com/aang-sym/traits-takehome.git
cd traits-takehome

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Download SkillCorner Open Data:

```bash
git lfs install
mkdir -p data
cd data
git clone https://github.com/SkillCorner/opendata.git
git lfs pull
cd ..
```

You should now see ten match directories under:

```
data/opendata/data/matches/
```
### Selecting the Python environment for notebooks

If VS Code or Jupyter doesn't automatically detect the virtual environment, register it as a Jupyter kernel:
```bash
python -m ipykernel install --user --name traits-takehome --display-name "Python (traits-takehome)"
```

After registering the kernel:

* Restart VS Code (or Reload Window)
* Open any notebook and click Select Kernel
* Choose Python (traits-takehome)
(or select ./venv/bin/python via "Enter interpreter path" if it doesn't appear)

---

## Running the pipeline

Run the notebooks in order:

1. **01_data_loading.ipynb**  
   Load tracking, dynamic events, phases and metadata for each match.  
   Write out consolidated CSVs.

2. **02_eda.ipynb**  
   Quick sanity checks to make sure basic distributions look correct.

3. **03_sprint_quality.ipynb**  
   Detect sprints from tracking, smooth speeds, join to phases, compute sprint metrics.

4. **04_off_ball_run_value.ipynb**  
   Aggregate off‑ball runs using SkillCorner’s xThreat fields and the most reliable run subtypes.

5. **05_pressing_effectiveness.ipynb**  
   Aggregate pressing and counter‑pressing actions, compute simple volume/effectiveness measures.

6. **06_combining_metrics.ipynb**  
   Merge metric families with player metadata to form the final `player_metrics` table.

7. **07_validation.ipynb**  
   Basic sanity checks on ranges, counts and consistency.

8. **08_visualisation.ipynb**  
   A few lightweight plots for comparing players or position groups.

### Key outputs (in `output/`)

- `player_sprints.csv`  
- `player_runs.csv`  
- `player_pressing.csv`  
- `player_metadata.csv`  
- **`player_metrics.csv`** — final player‑match table  

The final `player_metrics.csv` and its matching `player_metrics_schema.json` are included in the repository so reviewers can inspect the final table without running the full pipeline.

Schemas documenting these outputs are in `schemas/`.

All other output csv files and schema jsons are loaded into `output/` and `schemas/` respectively through running the notebooks.

---

## What the metrics cover

### Sprints  
Using tracking data:
- detect sprints from smoothed speeds and a threshold in the mid‑20s km/h  
- count sprints per 90  
- measure distances and basic speed profile  
- tag each sprint with the phase of play it mostly sits in  

**Intent:** distinguish between players who sprint frequently and players who sprint in more valuable attacking moments.

### Off‑ball runs  
Using SkillCorner’s run events:
- aggregate the more frequent, tactically meaningful run types  
- use SkillCorner’s xThreat and “dangerous” flags  
- compute per‑90 volume and simple run‑value metrics  

**Intent:** highlight players who make more threatening movements, not just more movements.

### Pressing  
From pressing/counter‑pressing events:
- compute volume per 90  
- measure simple success rates based on regain/disruption outcomes  
- keep high‑level territorial context where available  

**Intent:** separate pressing frequency from pressing effectiveness.

### Visualisations – spider comparison and scatter plots

The main visual layer lives in `08_visualisation.ipynb` and is split into:

#### Spider (radar) comparison

The spider plot is used for **player vs comparison** views within a single metric family:

- **Metric families:** `Sprints`, `Off-ball runs`, `Pressing`.
- **Axes:** the family-specific metrics defined in `METRIC_FAMILIES`  
  - Sprints: high-value sprint %, attacking/defensive sprint %, high-value sprints per 90, sprint distance per 90  
  - Off-ball runs: average xThreat, threat per 90, high-value run %, high-value runs per 90, average opponents beaten  
  - Pressing: press success rate, regain rate, disruption rate, shot creation rate, successful presses per 90, pressing actions per 90
- **Values:** each axis shows a **0–100 percentile** for the chosen player, computed within a selected cohort  
  (`All players`, `Same position_group`, `Same team`, or `Same team and position_group`).

The radar always compares **Player 1** against either:
- another named player, or  
- a baseline average (e.g. team, position-group, or team+position-group) from the same cohort.

Alongside the radar, a small bar chart shows the family’s `primary_rate` for both entities  
(e.g. `high_value_sprints_per_90`, `threat_per_90`, or `successful_presses_per_90`).  
This keeps the spider focused on profile shape, while the bar chart anchors it in an absolute per-90 value.

#### Scatter plots
The scatter plots show how a player’s activity connects to impact within each family:

- **Sprints:**  
  `high_value_sprints_per_90` (y) vs `sprint_distance_per_90` (x)  
  → separates empty running from sprinting that repeatedly shows up in valuable moments.

- **Off-ball runs:**  
  `threat_per_90` (y) vs `high_value_runs_per_90` (x)  
  → shows who produces actual threat, not just movement volume.

- **Pressing:**  
  `successful_presses_per_90` (y) vs `pressing_actions_per_90` (x)  
 → shows whether a player is both active and effective in the press.

For more detail on why these particular metrics and pairings were chosen, see the visualisation section in `decisions.md`.

---

## Technical decisions (summary)

This is a small, local prototype, so I kept the architecture simple but made choices that would still translate cleanly to a larger setup.

### Notebooks + small helpers

I use Jupyter notebooks for the main steps (load → explore → build metrics → validate → visualise), and a few small modules under `src/` for shared logic like data loading and metric calculations.

**Why:** the task explicitly asks for notebooks, and this makes the analysis easy to follow, but I still avoid copy‑pasting logic everywhere.

### Data flow

The pipeline always follows the same pattern:

1. Read tracking, events, phases and metadata for each match.
2. Do light EDA to sanity‑check ranges and volumes.
3. Build separate metric tables for sprints, off‑ball runs and pressing.
4. Join everything back to a player‑match metadata table (`player_metrics`).
5. Run a few checks and simple visualisations on the final table.

**Why:** keeping a single, well‑defined final table makes it clear what the downstream "product" is for this exercise.

### PySpark vs pandas

For the heavier aggregations I use PySpark since it mirrors how this would scale in a real Glue setup. For lighter EDA and formatting, pandas keeps the code shorter.

**Why:** the groupby/aggregation logic is the same shape you would use in Glue, so it demonstrates how this could scale to more matches without rewriting everything. For lighter EDA and final formatting I still use pandas where it keeps the code shorter.

### Outputs and schemas

Outputs are written as CSVs into `output/` with matching JSON schemas under `schemas/`.

**Why:** CSVs are easy to inspect for a take‑home, and the schemas give a clear, machine‑readable contract for the structure of the main tables.

For more detail on these choices and how they’d look in a bigger environment, see `decisions.md`.

---

## Validation

`07_validation.ipynb` runs a small set of checks:

- all ten matches load correctly  
- aggregated tables match raw event counts  
- sprint/run/press metrics sit in realistic ranges  
- simple cross‑metric consistency checks  

This is enough to catch obvious issues in a small prototype.  
In a fuller codebase I’d add unit tests for core helpers, a small end‑to‑end test on synthetic data, and a few data‑quality checks that run automatically.

For this prototype, logging is intentionally simple — each notebook prints out row counts, distribution summaries, merge diagnostics, and any basic warnings. This keeps things transparent when stepping through the workflow.  

In a production environment (Glue) I’d switch to structured logging (logger.info with JSON payloads) and emit CloudWatch metrics for match‑ingestion counts, event volumes per match, empty or malformed inputs, success/failure of each metric‑aggregation stage, and simple timings for the sprint/run/pressing steps.

---

## Prototype vs production (brief notes)

This project stays local and notebook‑driven for clarity. In a production setup I’d move to:

- partitioned Parquet in S3 instead of local CSVs  
- Spark jobs (Glue/EMR/Databricks) instead of notebooks  
- simple orchestration (Airflow or Step Functions) to process new matches daily  
- structured logs + a handful of monitoring metrics  
- automated schema and data‑quality checks before publishing outputs  

The logic doesn’t change much — mainly the I/O, scaling, and orchestration.

For more detail, see **docs/decisions.md**.

---

## Project structure

```
├── data/                     # SkillCorner OpenData (via Git LFS)
│
├── notebooks/                # All analysis + metric notebooks
│   ├── 01_data_loading.ipynb
│   ├── 02_eda.ipynb
│   ├── 03_sprint_quality.ipynb
│   ├── 04_off_ball_run_value.ipynb
│   ├── 05_pressing_effectiveness.ipynb
│   ├── 06_combining_metrics.ipynb
│   ├── 07_validation.ipynb
│   └── 08_visualisation.ipynb
│
├── output/                   # Generated tables (created after running notebooks)
│                             # includes final player_metrics.csv
│
├── schemas/                  # Generated JSON schemas (created after running notebooks)
│                             # includes final schema for player_metrics
│
├── src/                      # Small helper modules
│   ├── loaders.py
│   ├── eda.py
│   ├── metrics.py
│   └── visualisation.py
│
├── infra/                    # Mock IaC file (AWS CDK)
│   └── traits_pipeline_stack.py
│
├── docs/                     # System design + decisions
│   ├── system_design.md
│   └── decisions.md
│
└── README.md
```

---

## Data source

This pipeline uses the 10‑match A‑League sample from  
https://github.com/SkillCorner/opendata

It includes:
- tracking (10fps),  
- dynamic events,  
- phases of play,  
- match metadata.

---</file>