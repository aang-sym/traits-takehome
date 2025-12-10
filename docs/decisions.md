# Technical Decisions & Rationale

**Project:** SkillCorner A-League Tracking Data ETL  
**Scope:** Local prototype for 10 matches

The brief suggested 4–6 hours. I spent closer to 10–12 to build something coherent end‑to‑end, with clear metric definitions, validation, and visual examples. The aim is not to mimic a full production platform. It is a structured prototype that shows how I reason about modelling, transforming, and interpreting tracking data, and what the pipeline would look like if it were taken further.

---

## 1. Overview

The goal was to take SkillCorner’s tracking, phases, and events data and produce a single player‑match table covering:

- Sprint metrics  
- Off‑ball run metrics  
- Pressing metrics  

My focus was on:

- A clean, readable pipeline in notebooks  
- Metric definitions that make sense tactically  
- Leveraging SkillCorner’s own model outputs rather than rebuilding ML that already exists  
- Producing a final `player_metrics` dataset that could slot into downstream analysis or modelling

---

## 2. Pipeline Structure

### 2.1 Notebooks with small reusable helpers

The pipeline is structured around notebooks for the main steps:

- Data loading  
- EDA  
- Metric extraction (sprints, runs, pressing)  
- Validation  
- Visualisation  

Common logic (speed smoothing, sprint detection, basic aggregations) lives in small helpers under `src/`. The goal is not to build a framework. It is to keep the notebooks readable and make the metric logic easy to lift into a script or Spark job.

**Why this approach**

The task explicitly wants `.ipynb` deliverables, which naturally lends itself to step‑wise exploration. Pulling repeated logic into helpers keeps the notebooks readable and makes it clearer how this work could transition into a script or Spark job.

### 2.2 Data Flow

1. Load tracking, events, phases, and metadata.  
2. Sanity‑check distributions and ranges.  
3. Build metrics:
   - Detect sprints from tracking.
   - Aggregate off‑ball run events and SkillCorner xThreat / dangerous flags.
   - Aggregate pressing events and their outcomes.
4. Merge everything back onto player‑match metadata.  
5. Run simple validation checks.  
6. Produce visual summaries (spider profiles + activity/impact scatter views).

The final deliverable is a single CSV ready for downstream use.

---

## 3. Metric Choices

I focused on three areas: sprints, off‑ball runs, and pressing. Each metric is defined at player–match level, normalised where appropriate.

### 3.1 Sprints

**What I calculate**

- Sprint counts and distances per 90  
- Average and max sprint speed  
- Location / tactical context of sprints (attacking third, shot possessions, goal possessions, etc.)

**Key decisions**

- A speed threshold of 25 km/h, applied after smoothing raw speeds, avoids single‑frame spikes caused by tracking noise.  
- Sprint start and end detection is intentionally simple but stable enough for the sample size.  
- Each sprint is joined to the phase it mostly sits in. This helps identify whether a player is sprinting in meaningful attacking moments or just covering ground.

Although I calculate sprints directly from tracking for the take‑home, in production I’d lean on SkillCorner’s Physical Aggregates. They already handle COD detection and TIP/OTIP normalisation, which avoids rebuilding low‑level movement inference and keeps the work focused on combining physical, tactical, and value dimensions.

### 3.2 Off-ball Runs

**What I calculate**

- Runs per 90  
- xThreat metrics (average + per 90)  
- High-value run share (`dangerous` flag)  
- Simple directional context (ahead / behind)  

**Key decisions**

- SkillCorner already provides run detection, subtypes, xThreat, and a `dangerous` flag. Re-deriving those in a take-home isn’t useful — a real pipeline would use the model outputs directly.
- The metric is kept phase-agnostic. I initially explored joining runs to phase-of-play, but for a single-match sample it didn’t add enough signal over the model’s own threat outputs. In a multi-match setting you’d re-introduce phase context.
- The aggregation focuses on signals that actually separate players: effort (volume), value creation (xThreat), how often their runs are dangerous, and simple subtype patterns that show how a player actually moves off the ball.

### 3.3 Pressing

**What I calculate**

- Pressing actions per 90  
- Success, regain, and disruption rates  
- Successful presses per 90  
- Block‑zone context (high / mid / low)  
- Counter‑press volume

**Key decisions**

- A press is “successful” if it leads to a regain or disruption, using SkillCorner’s outcome fields.  
- Volume and effectiveness are kept separate - they reflect different behaviours.  

I avoid rebuilding SkillCorner’s ML models here - their Receiver, Threat, and defensive-structure outputs already give stable tactical context. The useful work here is aggregating and contextualising those fields so they tell a clear story about player behaviour, not recreating the underlying models.

---

## 4. Validation

The validation here aims to catch obvious errors rather than form a full test suite.

**Implemented checks**

- Every player‑match appears in `player_metrics` where minutes > 0.  
- Sprint speeds sit in realistic ranges for professional players.  
- per‑90 metrics are non‑negative and not extreme outliers.  
- Percentages fall within [0, 1].  
- Derived counts (e.g. “successful_presses_per_90”) map cleanly back to raw counts.

The validation follows SkillCorner’s own specifications: Dynamic Events defines valid event_type/subtype combinations, the Physical Glossary defines speed bands, and the Phases spec defines frame‑coverage rules. Using these as the source of truth keeps the checks aligned with expected data guarantees.

**What I’d add in a real project**

- Unit tests for helper functions (smoothing, sprint detection, phase joins).  
- A small synthetic end‑to‑end dataset to validate shapes and invariants.  
- Automated DQ checks (non‑null IDs, positive minutes, percentile ranges) that run on each batch.  
The point is not exhaustive validation. It is catching structural issues early so the metric tables stay trustworthy as the pipeline grows.

---

## 5. Visualisation Choices

The visual layer is deliberately small but serves two different purposes:

1. **Spider profiles** - a quick way to compare shapes within a metric family.  
2. **Scatter views** - showing how a player’s activity level relates to the value they generate.

Both rely on the same `METRIC_FAMILIES` configuration and percentile calculations.

### 5.1 Spider Profiles

The spider plots let you see how a player’s profile within a metric family compares to either another player or a cohort baseline (e.g., position group or team).

Each family uses the metrics defined in `METRIC_FAMILIES["<family>"]["metrics"]`.  
Percentiles are computed relative to a chosen cohort.

### 5.2 Scatter Plots

The scatter plots are meant to show how activity connects to value for each family. The pairings are:

**Sprints:**  
`high_value_sprints_per_90` vs `sprint_distance_per_90`  
Shows whether sprinting volume translates into sprints that matter tactically.

**Off‑ball runs:**  
`threat_per_90` vs `high_value_runs_per_90`  
A straightforward volume versus value read - who runs a lot, and who generates actual threat.

**Pressing:**  
`successful_presses_per_90` vs `pressing_actions_per_90`  
Separates high‑volume/high‑impact pressers from players who press a lot without outcomes.

There’s no need for quoted questions - the charts stand on their own with clear intent.

### 5.3 How Both Views Fit Together

- Spider plots help compare players or compare a player to their cohort.  
- Scatter plots help explain *why* that profile looks the way it does.  

Together they give a compact read on role, behaviour, and value creation.

---

## 6. Prototype vs Production

This is a notebook‑driven prototype. A real implementation would use the same conceptual logic but different infrastructure.

### 6.1 Data + Compute

**Prototype**

- Local CSVs.  
- Notebook execution.  
- Outputs written to `output/`.

**Production**

- A scheduled Lambda (triggered by EventBridge) calls the SkillCorner API and writes the raw match files into an ingestion bucket (bronze).
- A Glue job loads bronze data, applies the first-pass cleaning/normalisation, and writes structured tables into a processed bucket (silver).
- A second Glue/Spark step computes the player-level metrics and writes the final analytical tables into a curated bucket (gold).
- Cleaned tables are registered in the Glue Data Catalog so they can be queried in Athena or loaded into Redshift.
- The core logic stays straightforward — the main differences in production are around orchestration, batching, and the bronze/silver/gold separation.

The conceptual logic stays the same. Production formalises it with clearer boundaries, scheduling, and observability.

Normalising per‑90 works for physical output, but tactical opportunities vary by style and match state. In production I’d use TIP‑based normalisation (e.g., P30 TIP) for possession‑linked actions so comparisons are fair across roles and team contexts.

### 6.2 Orchestration

**Prototype:** manual, run in notebook order.  
**Production:** Step Functions or Airflow controlling steps like:

1. Detect new matches in S3 after Lambda ingestion.  
2. Process tracking + events to extract metrics.  
3. Update downstream tables.  
4. Trigger DQ checks and alerts on failurem utilise DLQ if needed.

### 6.3 Monitoring

In a real system I’d add:

- Structured logging with match IDs, row counts, timings.  
- Metrics like number of matches processed or avg runtime per stage.  
- Alerts for unusual volumes or runtime spikes.

---

## 7. Limitations & Next Steps

A few things I’d refine with more time:

- Sprint detection could be made more robust with better gap handling and clearer start/end criteria.  
- Off‑ball run analysis could incorporate linking runs to outcomes beyond xThreat (shots, chances).  
- Pressing is measured at the player level - modelling pressing chains or collective behaviour would require sequence logic.  
- A test suite around helpers would make the pipeline easier to productionise.

Overall, the prototype covers the core modelling decisions. The next step would be turning the metric logic into a small, testable library ready to run at scale.

If I extended this codebase, I’d prioritise:

1. Moving metric logic into a small, testable module ready for Spark.  
2. Improving sprint/run definitions with domain input.  
3. Adding lightweight orchestration and monitoring examples to tie it all together.

---</file>