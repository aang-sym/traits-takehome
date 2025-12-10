# System Design: Production ETL Pipeline for SkillCorner Tracking Data

This document describes how to run the local notebook prototype as a production ETL pipeline on AWS. It covers:

- A straightforward architecture using S3, Glue, and Athena  
- A medallion layout with bronze, silver, and gold layers to organise data  
- A small number of Glue jobs managed by Step Functions  
- Enough detail to explain the design clearly

---

## 1. Goals and constraints

**Goals**

- Convert raw SkillCorner tracking and event data into player-level metrics for sprint quality, off-ball run value, and pressing effectiveness.  
- Keep the pipeline simple and maintainable for a small data team (1–3 engineers).  
- Make it easy to scale from a 10-match sample to hundreds of matches weekly.

**Non-goals for v1**

- Real-time or in-match updates  
- Complex machine learning infrastructure  
- Multi-region or multi-tenant isolation beyond basic partitioning

---

## 2. High-level architecture (bronze / silver / gold)

The pipeline uses a medallion layout to organise data by processing stage. This helps separate raw input, cleaned tables, and aggregated metrics for easier management and querying.

Data is stored in one analytics S3 bucket with three main folders:

- **Bronze** – Raw match data ingested from SkillCorner, stored as-is to allow reprocessing later.  
- **Silver** – Cleaned and normalized Parquet tables derived from bronze data, ready for analysis.  
- **Gold** – Aggregated player-level metrics computed from silver tables.

```text
SkillCorner source (API)
    ↓ EventBridge schedule
┌───────────────────────────────────────┐
│ Lambda: Fetch from SkillCorner API    │
│  - tracking_extrapolated.jsonl        │
│  - dynamic_events.csv                 │
│  - phases_of_play.csv                 │
│  - match.json                         │
└───────────────────────────────────────┘
    ↓ writes to ingestion bucket
┌───────────────────────────────────────┐
│ S3 ingestion bucket                   │
│ s3://skillcorner-ingestion/matches/   │
│   partition_date=YYYY-MM-DD/          │
│     match_id=*/                       │
│       tracking_extrapolated.jsonl     │
│       dynamic_events.csv              │
│       phases_of_play.csv              │
│       match.json                       │
└───────────────────────────────────────┘
            │
            ↓ Triggered on schedule or when new match files land
┌───────────────────────────────────────┐
│ Step Functions: TraitsETLPipeline     │
│ [Start]                               │
│   → Run Bronze/Silver Job             │
│   → Run Gold Job                      │
│   → Update Catalog                    │
│   → Notify                            │
└───────────────────────────────────────┘
            │ invokes Glue Job 1
            ↓
┌───────────────────────────────────────┐
│ Glue Job 1: Bronze/Silver (PySpark)   │
│   1. Copy into bronze/                │
│   2. Normalise → silver/ (Parquet)    │
└───────────────────────────────────────┘
            │ writes                     │
            ↓
┌───────────────────────────────────────┐
│ S3 analytics bucket (medallion)       │
│   bronze/ – raw-ish match files       │
│   silver/ – normalised Parquet tables │
└───────────────────────────────────────┘
            │ Step Functions continues
            ↓ invokes Glue Job 2
┌───────────────────────────────────────┐
│ Glue Job 2: Gold Metrics (PySpark)    │
│   - Read silver/                      │
│   - Compute sprint / run / pressing   │
│   - Write gold/player_* , player_metrics │
└───────────────────────────────────────┘
            │ writes
            ↓
┌───────────────────────────────────────┐
│ S3 analytics bucket (gold layer)      │
│   gold/ – player-level metric tables  │
└───────────────────────────────────────┘
            │ crawled
            ↓
┌───────────────────────────────────────┐
│ AWS Glue Data Catalog                 │
│   Database: traits_etl                │
│   Tables: bronze.*, silver.*, gold.*  │
└───────────────────────────────────────┘
            │ queried by
            ↓
┌───────────────────────────────────────┐
│ Query & Analytics Layer               │
│   - Amazon Athena                     │
│   - Optional: Redshift/BI tools       │
└───────────────────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│ Monitoring & Alerting                 │
│   - CloudWatch logs & metrics         │
│   - SNS notifications                 │
└───────────────────────────────────────┘
```

This setup fits in one AWS account and region.

---

## 3. ETL data flow

The pipeline uses two Glue Spark jobs, following the same logic as the local notebooks for consistency.

1. **Glue Job 1 – Raw → Bronze/Silver**  
   - Copies new match files into the analytics bucket under `bronze/` without modification.  
   - Converts JSONL and CSV files into cleaned Parquet tables under `silver/`.

2. **Glue Job 2 – Silver → Gold**  
   - Reads the silver tables for the given date, calculates player-level metrics, and writes them to `gold/`.

### 3.1 Ingestion and bronze layer

**Trigger**

- A scheduled EventBridge rule (e.g., daily at 2am UTC) invokes a small ingestion Lambda.  
- The Lambda authenticates with the SkillCorner API, fetches tracking, events, phases, and match metadata for the target date, and writes them to the S3 ingestion bucket under `partition_date=YYYY-MM-DD/match_id=.../`.
- Once the files land in the ingestion bucket, an S3 event or the same EventBridge workflow triggers the Step Functions state machine with the relevant `partition_date`.

**Glue Job 1 tasks**

- Confirm each match folder includes all expected files: `tracking.jsonl`, `dynamic_events.csv`, `phases_of_play.csv`, `match.json`.  
- Copy these files to `bronze/partition_date=YYYY-MM-DD/match_id=…/` in the analytics bucket.  
- Perform basic checks like file non-emptiness and row counts, failing early if something’s off.

Keeping bronze data close to raw source makes it easy to fix or reprocess data later.

### 3.2 Silver layer: normalized tables

In the same Glue job, the data is transformed into cleaned, typed Parquet tables:

- `silver/tracking/partition_date=…/match_id=…`  
  Flattened frame-by-frame player positions from `tracking.jsonl`.  
- `silver/events/partition_date=…/match_id=…`  
  Typed and normalized rows from `dynamic_events.csv`.  
- `silver/phases/partition_date=…/match_id=…`  
  Phases of play data for context in metrics.  
- `silver/metadata/partition_date=…/match_id=…`  
  Player, team, and lineup metadata from `match.json`.

These tables are partitioned by `partition_date` and `match_id` where helpful, making queries efficient.

### 3.3 Gold layer: player-level metrics

**Glue Job 2 – Silver → Gold**

This job reads the silver tables for a date and calculates:

- `gold/player_sprints` – sprint counts, speeds, and context per player-match  
- `gold/player_runs` – off-ball run volume, average xThreat, high-value run percentages  
- `gold/player_pressing` – pressing counts, success, and regain rates  
- `gold/player_metrics` – a combined view joining metadata with the three metric groups  

The implementation follows the notebook logic but uses batch-friendly operations like window functions and joins.

Gold tables are partitioned by `partition_date` and `competition_id` to keep queries focused.

---

## 4. Orchestration with Step Functions

Here’s a minimal ASL definition — enough to show the structure without overcomplicating it.

```json
{
  "Comment": "Traits ETL Pipeline - Daily Batch",
  "StartAt": "RunBronzeAndSilver",
  "States": {
    "RunBronzeAndSilver": {
      "Type": "Task",
      "Resource": "arn:aws:states:::glue:startJobRun.sync",
      "Parameters": {
        "JobName": "TraitsETL-BronzeSilver",
        "Arguments": {
          "--partition_date.$": "$.partition_date"
        }
      },
      "Next": "RunGoldMetrics"
    },
    "RunGoldMetrics": {
      "Type": "Task",
      "Resource": "arn:aws:states:::glue:startJobRun.sync",
      "Parameters": {
        "JobName": "TraitsETL-GoldMetrics",
        "Arguments": {
          "--partition_date.$": "$.partition_date"
        }
      },
      "Next": "UpdateCatalog"
    },
    "UpdateCatalog": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:glue:startCrawler",
      "Parameters": {
        "Name": "TraitsETL-Crawler"
      },
      "Next": "NotifySuccess"
    },
    "NotifySuccess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:REGION:ACCOUNT:TraitsETL-Notifications",
        "Subject": "Traits ETL Succeeded",
        "Message.$": "States.Format('Completed for {}', $.partition_date)"
      },
      "End": true
    }
  }
}
```

This state machine runs the two Glue jobs in sequence, triggers a Glue crawler to update the catalog, and sends a success notification. In production, you’d add error handling and retries, but this covers the essentials.

Triggers can be:

- **Scheduled batch** – EventBridge runs daily at 2am UTC, passing the previous day’s date.  
- **Object-based** – S3 event triggers when new match files arrive.

---

## 5. Query and access layer

- The Glue Data Catalog holds bronze, silver, and gold tables in the `traits_etl` database.  
- Athena is the main tool for analysts and data scientists to query gold tables like `player_metrics`.  
- If preferred, Redshift Spectrum can query the same S3 data without changing the ETL.

Example Athena query:

```sql
SELECT
  player_short_name,
  position_group,
  AVG(sprints_per_90) AS avg_sprints,
  AVG(threat_per_90) AS avg_threat
FROM traits_etl.player_metrics
WHERE partition_date BETWEEN '2024-11-01' AND '2024-11-30'
  AND competition_id = 'aus1'
  AND minutes_played >= 45
GROUP BY player_short_name, position_group
ORDER BY avg_threat DESC
LIMIT 10;
```

---

## 6. Logging, monitoring, and data quality

Keep monitoring simple and effective:

- Glue jobs write structured logs to CloudWatch, one log group per job.  
- Basic custom metrics track rows processed, match counts, and job duration.  
- A validation step (either inside Glue Job 2 or a follow-up Lambda) checks that:  
  - `player_metrics` has at least one row per starting player per match  
  - Key metrics are within reasonable ranges (e.g., sprint speeds, xThreat values)  

If validation fails, the job should fail quickly so issues are clear. Logs and Step Functions history help with debugging.

---

## 7. Scaling and future work

The design is simple but flexible:

- **Scale up volume** – Increase Glue worker resources and rely on partitioned Parquet tables to handle more matches.  
- **Refine medallion layers** – If needed, split bronze, silver, and gold into separate Glue jobs or workflows without changing the overall flow.  
- **Schema evolution** – Add new metrics as columns in gold tables; existing queries can ignore or adapt.  
- **Streaming later** – If real-time insights become important, add a streaming bronze layer and structured streaming jobs alongside the batch pipeline.

This approach keeps the production pipeline aligned with the local notebooks and provides a clear path to a scalable, maintainable ETL on AWS.
