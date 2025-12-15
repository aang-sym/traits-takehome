# Interview Preparation Plan - Traits Insights Senior Data Engineer
**Interview Date:** Wednesday, 10:00 AM
**Preparation Time:** Monday-Tuesday (12-16 hours total)
**Role:** Senior Data Engineer at Traits Insights

---

## Context & Goals

### About the Interview
- **4th round interview** - likely the final technical deep-dive
- **60-90 minutes** focused on your takehome submission
- **Format:** Questions about your code, design decisions, and productionization approach
- **Success Criteria:** Demonstrate deep understanding of your implementation and ability to scale it

### What They're Looking For (from JD)
1. **Data Engineering Excellence:** Clean pipelines, good architectural decisions
2. **AWS/Infrastructure:** Glue, Spark, Step Functions, IaC
3. **Problem-Solving:** How you approached tracking data and metrics
4. **Productionization Thinking:** How to take this from prototype to production
5. **Communication:** Explaining technical decisions clearly

### Your Prep Goals
1. **Master every helper function** - especially sprint detection algorithm
2. **Understand the tactical reasoning** behind each metric
3. **Explain productionization strategy** confidently
4. **Anticipate and prepare for tough questions**

---

## Repository Overview (Quick Reference)

### Project Stats
- **Total lines of code:** ~1,500 lines in src/
- **Notebooks:** 8 notebooks covering full ETL pipeline
- **Metrics:** 3 metric families (Sprints, Off-ball Runs, Pressing)
- **Data:** 10 A-League matches, 237 unique players, 360 player-match records
- **Output:** Single `player_metrics.csv` with 39 columns

### Architecture Summary
```
Data Flow:
1. Raw SkillCorner data (tracking JSONL, events CSV, phases CSV)
2. Load & EDA → understand distributions
3. Compute metrics → sprints (from tracking), runs & pressing (from events)
4. Combine → single player_metrics table
5. Validate → sanity checks
6. Visualize → radar charts, scatter plots
```

### Key Technical Decisions
1. **Notebooks over scripts** - exploratory nature of task
2. **PySpark for aggregations** - scales to production
3. **Heavy smoothing in sprint detection** - remove tracking artifacts
4. **Phase enrichment** - adds tactical context to physical events
5. **Percentile-based visualizations** - fair cross-player comparisons

---

## MONDAY PLAN (6-8 hours)

### Morning Session (3-4 hours): Deep Code Understanding

#### Block 1: Sprint Detection Algorithm (90 mins)
**File:** `src/metrics.py:22-132` (detect_sprints function)

**Goal:** Explain this function line-by-line like you wrote it yesterday

**Tasks:**
1. Read the function completely (10 mins)
2. Draw the algorithm flow on paper:
   ```
   For each player:
   → Calculate distances between frames
   → Remove teleports (>1m per frame)
   → Convert to km/h
   → Cap speeds at 32 km/h
   → Heavy smoothing (rolling median + mean)
   → Detect sprint frames (>24.5 km/h)
   → Group consecutive frames
   → Validate sprint characteristics
   → Extract sprint metrics
   ```

3. **Deep dive on smoothing logic (lines 62-70):**
   - Why rolling median THEN rolling mean?
     → Median removes outliers, mean smooths the result
   - Why window=11 frames?
     → At 10 fps, that's 1.1 seconds - removes single-frame spikes while preserving real acceleration
   - Practice explaining: "We use a two-stage smoothing approach: first a rolling median with an 11-frame window to remove tracking artifacts and outliers, then a 7-frame rolling mean to further smooth the speed profile. This is aggressive but necessary because tracking data at 10 Hz can have single-frame position errors that create unrealistic speed spikes."

4. **Deep dive on validation (lines 106-114):**
   - Why these specific thresholds?
     - avg_speed: 24.5-29 km/h → sustained sprint effort range
     - max_speed: 26-33 km/h → brief peak speed
     - distance: >7m → SkillCorner defines sprint velocity as 7 m/s
   - Practice explaining: "These validation thresholds are based on SkillCorner's physical glossary and PSV99 data from professional football. We reject sprints with unrealistic characteristics - if average speed is too low it's not really a sprint, if it's too high it's likely a tracking error."

5. **Write out answers to these questions:**
   - Q: "Why not just use SkillCorner's physical aggregates instead of detecting sprints yourself?"
   - A: [Write your answer based on decisions.md lines 79-80]

   - Q: "What happens if a player has a legitimate acceleration that looks like a teleport?"
   - A: [Think through the teleport threshold - is 1.5m per frame (36 km/h) reasonable?]

   - Q: "How would you test this function?"
   - A: [Unit tests with synthetic data, validation against known sprint counts, edge cases]

**Deliverable:** A one-page summary of the sprint detection algorithm you can reference during the interview

---

#### Block 2: Phase Enrichment Logic (45 mins)
**File:** `src/metrics.py:135-203` (enrich_sprints_with_phases)

**Goal:** Understand how tactical context is added to physical events

**Tasks:**
1. Understand the join logic:
   - Uses **mid_frame** of sprint, not start/end
   - Why? → Avoids edge cases where sprint spans multiple phases
   - Finds phase where: `frame_start <= mid_frame <= frame_end`

2. Understand what gets attached:
   - `team_in_possession_phase_type` → create, finish, build_up, etc.
   - `possession_lead_to_shot` → outcome flag
   - `third_end` → spatial context

3. Understand derived flags (lines 194-198):
   - `is_high_value_phase` → create/finish/quick_break/transition
   - Why these four? → Most likely to produce threat

4. Practice explaining: "After detecting sprints from raw tracking, we enrich each sprint with tactical context by joining to the phases-of-play data. We use the midpoint frame of each sprint to avoid edge cases. This allows us to distinguish between sprints in high-value attacking phases versus sprints during slow build-up or chaotic play."

**Deliverable:** Clear mental model of how physical → tactical context works

---

#### Block 3: PySpark Aggregations (60 mins)
**Files:**
- `src/metrics.py:223-302` (aggregate_player_sprints)
- `src/metrics.py:304-395` (aggregate_off_ball_runs)
- `src/metrics.py:397-506` (aggregate_pressing_impact)

**Goal:** Explain the PySpark aggregation pattern

**Tasks:**
1. Identify the common pattern across all three functions:
   ```python
   # Pattern:
   1. groupBy(['match_id', 'player_id'])
   2. agg() with multiple metrics
   3. join with player_metadata for minutes_played
   4. calculate per_90 metrics
   5. filter minimum thresholds
   6. select output columns
   ```

2. Deep dive on one example - aggregate_player_sprints:
   - Line 252: Converting boolean to int for mean → why?
     → Can't average booleans directly, need numeric
   - Line 274: Per-90 calculation → `(count * 90) / minutes_played`
   - Line 284: Composite metric → `sprints_per_90 * high_value_sprint_pct`

3. **Why PySpark instead of pandas?**
   - Practice answer: "PySpark mirrors production environment (Glue). The groupBy/agg logic is identical whether processing 10 matches or 1000 matches. For this prototype, pandas would be simpler, but using Spark shows how this would scale and makes the transition to production seamless."

4. Compare to pandas approach - when would you use each?
   - Prototype/EDA: pandas (faster iteration)
   - Production batch: PySpark (horizontal scaling)
   - Streaming: Spark Structured Streaming

**Deliverable:** Confidence explaining why PySpark was chosen and how aggregations work

---

### Afternoon Session (3-4 hours): Tactical Reasoning & Production Design

#### Block 4: Metric Design Rationale (90 mins)
**File:** `docs/decisions.md`

**Goal:** Explain WHY each metric exists and what it measures

**Tasks:**
1. **Sprint Metrics** (30 mins)
   - Read decisions.md lines 63-80
   - Key insight: "Not all sprints are equal - separating volume from value"
   - Metrics capture:
     - Volume: sprints_per_90, sprint_distance_per_90
     - Context: high_value_sprint_pct, attacking_sprint_pct
     - Outcomes: sprints_in_shot_possessions_pct
   - Practice explaining to a non-technical person: "We measure both HOW MUCH players sprint and WHEN they sprint. A winger who sprints 15 times in meaningless moments is different from one who sprints 10 times but mostly during attacking chances."

2. **Off-ball Run Metrics** (30 mins)
   - Read decisions.md lines 82-95
   - Key decision: Use SkillCorner's xThreat, don't rebuild it
   - Why? → They have the ML model, focus on aggregation
   - Metrics capture:
     - Volume: runs_per_90
     - Value: avg_xthreat, threat_per_90
     - Quality: high_value_run_pct (dangerous flag)
   - Practice explaining: "We leverage SkillCorner's xThreat model rather than rebuilding threat calculation. Our value is in aggregating these events to show which players consistently make high-threat movements, not just high-volume movements."

3. **Pressing Metrics** (30 mins)
   - Read decisions.md lines 97-111
   - Key insight: Volume ≠ effectiveness
   - Metrics capture:
     - Volume: pressing_actions_per_90
     - Effectiveness: press_success_rate, regain_rate
     - Context: block zones (high/mid/low)
   - Practice explaining: "Pressing is measured on two dimensions: frequency and success. A player who presses 20 times per match with 20% success rate is very different from one who presses 12 times with 60% success rate."

**Deliverable:** Concise 1-paragraph explanation for each metric family

---

#### Block 5: Production Architecture Deep Dive (90 mins)
**Files:** `infra/system_design.md`, `docs/decisions.md:183-244`

**Goal:** Confidently explain production implementation

**Tasks:**
1. **Medallion Architecture** (30 mins)
   - Read system_design.md lines 27-96
   - Draw the architecture on paper:
     ```
     Lambda (Ingestion) → Bronze (Raw) → Silver (Normalized) → Gold (Metrics)
     ```
   - Bronze: Why keep raw data?
     → Enables reprocessing if logic changes
   - Silver: Why normalized Parquet?
     → Type safety, compression, query performance
   - Gold: Why separate layer?
     → Business-ready aggregations, stable schema

2. **ETL Jobs Design** (30 mins)
   - Read system_design.md lines 124-180
   - Job 1: Bronze → Silver
     - Converts JSONL → Parquet
     - Normalizes types
     - Partitions by match_id and partition_date
   - Job 2: Silver → Gold
     - Runs sprint detection
     - Aggregates metrics
     - Combines into player_metrics

3. **Orchestration** (30 mins)
   - Read system_design.md lines 182-243
   - Step Functions state machine:
     1. Run Bronze/Silver job
     2. Run Gold job (depends on #1)
     3. Update Glue Catalog
     4. Notify on success
   - Triggers: EventBridge schedule (daily) or S3 event (new matches)

**Practice Questions:**
- Q: "How would you handle schema evolution?"
- A: Keep bronze flexible, design silver/gold for additive changes, use Glue Catalog versioning

- Q: "What if SkillCorner adds new event types?"
- A: Bronze captures them automatically, silver job needs update to parse, gold may or may not need new metrics

- Q: "How do you ensure idempotency?"
- A: Partition by match_id and date, rerunning same partition overwrites, use unique sprint_id for deduplication

**Deliverable:** Draw the architecture diagram you'll reference in the interview

---

### Evening Session: First Mock Interview (60 mins)

**Goal:** Practice answering questions out loud

**Setup:** Use a voice recorder or practice with a friend/AI

**Questions to Answer:**
1. "Walk me through your sprint detection algorithm."
2. "Why did you use PySpark for such a small dataset?"
3. "How would you scale this to 1000 matches per week?"
4. "What's the biggest technical challenge you faced?"
5. "If you had another week, what would you improve?"

**Self-Critique:**
- Did you ramble or stay concise?
- Did you use jargon appropriately?
- Could you draw diagrams to support your points?

---

## TUESDAY PLAN (6-8 hours)

### Morning Session (3-4 hours): Code Walkthrough Mastery

#### Block 6: Notebook Flow Understanding (90 mins)
**Goal:** Explain the entire pipeline from data → insights

**Tasks:**
1. Create a flowchart of all 8 notebooks:
   ```
   01_data_loading → Load + consolidate matches
   02_eda → Sanity checks on distributions
   03_sprint_quality → Detect sprints from tracking
   04_off_ball_run_value → Aggregate run events
   05_pressing_effectiveness → Aggregate pressing events
   06_combining_metrics → Merge into player_metrics
   07_validation → Data quality checks
   08_visualisation → Radar + scatter plots
   ```

2. For each notebook, memorize:
   - Primary goal
   - Key output
   - Most important code block
   - One interesting finding

3. Practice the "elevator pitch":
   - "This pipeline takes raw SkillCorner tracking and events data, detects sprints from 10 Hz tracking, enriches them with tactical context from phases-of-play, aggregates three metric families at player-match level, validates the outputs, and visualizes them with percentile-based radar charts."
   - Time yourself - can you say it in 30 seconds?

**Deliverable:** One-page notebook summary sheet

---

#### Block 7: Helper Functions - EDA & Loaders (60 mins)
**Files:** `src/eda.py`, `src/loaders.py`, `src/visualisation.py`

**Goal:** Quickly explain supporting functions if asked

**Tasks:**
1. **src/loaders.py** (20 mins)
   - Straightforward file loading functions
   - Key design: Consistent error handling
   - Practice: "Loaders are simple file I/O with clear error messages. In production these would be replaced by S3 reads with retry logic."

2. **src/eda.py** (20 mins)
   - `explode_player_tracking` → flattens nested JSONL
   - `calculate_distances` → Euclidean distance between frames
   - `calculate_speeds` → distance / time_delta
   - Key pattern: These are building blocks for sprint detection
   - Practice: "EDA functions handle the low-level tracking data transformations - flattening nested structures, calculating frame-to-frame distances and speeds. They're intentionally simple and testable."

3. **src/visualisation.py** (20 mins)
   - Radar charts: percentile-based comparison
   - Scatter plots: activity vs impact
   - Widget-based interactivity
   - Practice: "Visualizations use percentiles for fair comparison across positions and cohorts. The radar shows profile shape, the scatter shows activity-impact relationship."

**Deliverable:** Quick reference notes on each module

---

#### Block 8: Validation & Edge Cases (90 mins)
**Notebook:** `07_validation.ipynb`
**Goal:** Explain how you ensure data quality

**Tasks:**
1. Review validation checks:
   - All matches loaded correctly
   - Sprint speeds in realistic ranges (24-33 km/h)
   - Per-90 metrics are non-negative
   - Percentages in [0, 1]
   - Player-match coverage is complete

2. **Think through edge cases:**
   - Q: "What if a player only plays 5 minutes?"
     → Filtered by min_minutes threshold (30 mins for sprints)

   - Q: "What if tracking data has gaps?"
     → Smoothing handles short gaps, longer gaps create separate sprints

   - Q: "What if a sprint spans halftime?"
     → Sprint detection works per-period, won't cross periods

   - Q: "What about substitute players?"
     → Metrics are per-90, so normalized fairly

3. **Production validation you'd add:**
   - Schema validation (Great Expectations, dbt tests)
   - Row count alerts (CloudWatch metric)
   - Distribution monitoring (are speeds suddenly different?)
   - Completeness checks (all matches processed?)

**Deliverable:** List of 10 edge cases and how you handle them

---

### Afternoon Session (3-4 hours): Production Deep Dive & Interview Prep

#### Block 9: AWS Services Deep Dive (90 mins)
**Goal:** Confidently discuss AWS implementation

**Tasks:**
1. **AWS Glue** (30 mins)
   - Review Glue job structure
   - Understand Glue Data Catalog
   - Partitioning strategy for Parquet
   - Practice: "Glue runs PySpark jobs on managed infrastructure. We use it for both bronze→silver normalization and silver→gold metric aggregation. The Data Catalog provides a Hive-compatible metastore that Athena can query."

2. **Step Functions** (30 mins)
   - Review ASL definition (system_design.md:187-234)
   - Understand state machine flow
   - Error handling strategy
   - Practice: "Step Functions orchestrates the two Glue jobs in sequence, then triggers a crawler to update the catalog and sends an SNS notification. We use .sync integration to wait for job completion before proceeding."

3. **S3 + Partitioning** (30 mins)
   - Medallion layout in S3
   - Partition keys: partition_date, match_id, competition_id
   - Why this partitioning?
     → Enables efficient queries by date or competition
   - Parquet benefits: compression, columnar, schema evolution
   - Practice: "We partition gold tables by partition_date and competition_id to keep scans small. When analysts query for a specific date range or competition, Athena only reads the relevant partitions, which dramatically reduces query time and cost."

**Deliverable:** AWS architecture diagram with all services

---

#### Block 10: Scaling & Trade-offs Discussion (60 mins)
**File:** `docs/decisions.md:227-244`

**Goal:** Thoughtful answers about scaling decisions

**Tasks:**
1. **Scaling dimensions to discuss:**
   - Match volume: 10 → 1000+ matches/week
   - Historical depth: 1 season → 5 seasons
   - Leagues: 1 league → 20 leagues
   - Latency: Daily batch → Near real-time

2. **For each dimension, prepare:**
   - Current approach
   - Bottlenecks
   - How to scale
   - Trade-offs

   Example for Match Volume:
   - Current: Sequential processing per match
   - Bottleneck: Single Glue job
   - Solution: Partition Glue job by match_id, run parallel
   - Trade-off: More complex orchestration, higher cost

3. **Prepare answers for:**
   - Q: "How would you handle real-time requirements?"
     → Streaming: Kinesis → Spark Structured Streaming → DynamoDB
     → Still keep batch for historical recalculation

   - Q: "What about cost optimization?"
     → Spot instances for Glue
     → S3 lifecycle policies (bronze → Glacier after 1 year)
     → Partition pruning in queries
     → Pre-aggregate hot paths

   - Q: "How do you handle different tracking data formats?"
     → Bronze captures anything, silver normalization handles differences
     → Use schema registry for validation

**Deliverable:** Scaling decision matrix

---

#### Block 11: Final Mock Interview (90 mins)

**Goal:** Full interview simulation

**Setup:**
- Set a timer for 60 minutes
- Record yourself answering (audio or video)
- Have your code open but try not to reference it

**Interview Script:**

**Part 1: Code Walkthrough (20 mins)**
1. "Walk me through your entire pipeline at a high level."
2. "Let's dive into sprint detection. How does that work?"
3. "Why PySpark instead of pandas?"
4. "Show me your most complex function."

**Part 2: Design Decisions (20 mins)**
5. "Why did you choose these three metric families?"
6. "How do you ensure metrics are comparable across positions?"
7. "What's the difference between high_value_sprint_pct and sprints_in_shot_possessions_pct?"
8. "Why enrich sprints with phases instead of just using physical metrics?"

**Part 3: Production (20 mins)**
9. "How would you deploy this to production?"
10. "Walk me through the AWS architecture."
11. "How does data flow through bronze/silver/gold?"
12. "What happens when SkillCorner releases a new API version?"
13. "How do you monitor this pipeline in production?"

**Self-Review:**
- Which questions did you struggle with?
- Did you use specific examples from your code?
- Were you concise or rambling?
- Did you demonstrate senior-level thinking?

---

### Evening: Refinement & Relaxation (60 mins)

#### Final Prep Tasks:
1. **Create your "cheat sheet"** (30 mins)
   - One page with key facts, diagrams, metrics
   - Formulae for per-90 calculations
   - Architecture diagram
   - Top 5 design decisions

2. **Review common mistakes** (15 mins)
   - Don't over-explain simple things
   - Don't under-explain complex things
   - Use specific numbers from your analysis
   - Connect answers back to business value

3. **Relaxation** (15 mins)
   - Review your strengths
   - Remind yourself: you built this, you understand it
   - Get good sleep

---

## KEY TALKING POINTS TO MEMORIZE

### Technical Decisions
1. **"Why PySpark?"** → "Mirrors production environment. The groupBy/agg logic is identical whether processing 10 or 10,000 matches. Demonstrates production-ready thinking."

2. **"Why heavy smoothing?"** → "10 Hz tracking has single-frame errors that create unrealistic speed spikes. Rolling median removes outliers, rolling mean smooths the result. This is conservative but necessary."

3. **"Why not use SkillCorner's sprint data?"** → "For the takehome, detecting sprints from tracking demonstrates end-to-end data engineering. In production, I'd evaluate SkillCorner's Physical Aggregates against custom detection based on business requirements."

4. **"Why these three metric families?"** → "They span physical (sprints), tactical (runs), and defensive (pressing) dimensions. Together they give a complete view of off-ball contribution, which is hard to capture in traditional stats."

5. **"Why medallion architecture?"** → "Bronze preserves raw data for reprocessing. Silver provides normalized, queryable tables. Gold contains business-ready aggregations. This separation makes the pipeline maintainable and scalable."

### Business Value
1. "These metrics help scouts and analysts identify players who excel off-ball - players who create value through movement, positioning, and work rate, not just touches."

2. "The percentile-based approach enables fair comparison across leagues, positions, and playing styles. A striker and a center back can't be compared on raw sprint counts, but we can compare their sprint context quality within their position cohort."

3. "By separating volume from value, we avoid the trap of rewarding empty running. A player with moderate sprint volume but high shot-possession linkage is more valuable than one with high volume but no context."

### Production Readiness
1. "The prototype uses local CSVs and notebooks. Production would use S3 Parquet, Glue jobs, and Step Functions orchestration. The core logic - PySpark aggregations - is production-ready."

2. "I'd add structured logging, CloudWatch metrics for job duration and match counts, and automated data quality checks using Great Expectations or dbt tests."

3. "Schema evolution is handled by keeping bronze flexible and designing silver/gold for additive changes. The Glue Catalog tracks schema versions."

---

## MOST LIKELY QUESTIONS (Prepare 30-second answers)

### Code Understanding
1. Walk me through your sprint detection algorithm
2. Explain the phase enrichment logic
3. Why did you choose PySpark?
4. Show me your most complex function
5. How do you handle edge cases?

### Design Decisions
6. Why these three metric families?
7. How do you ensure fair comparison across positions?
8. What trade-offs did you make?
9. If you had more time, what would you improve?
10. Why did you use phase-of-play context?

### Production
11. How would you deploy this to production?
12. Walk me through the AWS architecture
13. How do you handle schema evolution?
14. What monitoring would you add?
15. How would you scale to 1000 matches/week?

### Data Quality
16. How do you validate your metrics?
17. What assumptions does your code make?
18. How do you handle missing data?
19. What happens if tracking data quality is poor?
20. How do you test this pipeline?

### Domain Knowledge
21. What is xThreat and why use it?
22. Why normalize per-90?
23. What's a realistic sprint speed for a professional player?
24. Why separate attacking and defensive sprints?
25. What's the difference between pressing volume and effectiveness?

---

## TROUBLESHOOTING GUIDE

### If You Blank on a Question:
1. **Ask for clarification:** "That's a great question. Just to make sure I understand, are you asking about X or Y?"
2. **Think out loud:** "Let me think through this step by step..."
3. **Reference your code:** "I can show you the specific implementation..."
4. **Be honest:** "I haven't thought deeply about that trade-off, but here's how I'd approach it..."

### If You Don't Know:
- ✅ "I haven't implemented that, but here's how I'd approach it..."
- ✅ "That's a gap in my current design. In production I'd..."
- ❌ Don't make up technical details
- ❌ Don't dismiss the question

### If They Push Back on a Decision:
- ✅ Listen to their reasoning
- ✅ "That's a valid point. The trade-off I was considering was..."
- ✅ "You're right, an alternative approach would be..."
- ❌ Don't get defensive

---

## DAY-OF CHECKLIST

### Morning of Interview:
- [ ] Review your one-page cheat sheet
- [ ] Open your codebase in VS Code
- [ ] Test that you can run a notebook (have it ready to share screen)
- [ ] Have your architecture diagram ready
- [ ] Review this plan's key talking points
- [ ] Do a 5-minute breathing exercise

### During Interview:
- [ ] Have water nearby
- [ ] Close all other applications
- [ ] Share screen confidently
- [ ] Take brief notes on questions you struggle with
- [ ] Ask clarifying questions
- [ ] End with 1-2 thoughtful questions for them

### Questions to Ask Them:
1. "What does the current data pipeline look like at Traits?"
2. "What's the biggest scaling challenge you're facing?"
3. "How does the team balance custom metrics vs vendor-provided data?"
4. "What does success look like for this role in the first 6 months?"

---

## CONFIDENCE BUILDERS

### You Already Know:
✅ You built a complete ETL pipeline
✅ You made thoughtful technical decisions
✅ Your code is well-structured and documented
✅ You understand the business context
✅ You can explain every line of code

### They're Evaluating:
- Can you explain your work clearly? → YES, after this prep
- Do you think like a senior engineer? → YES, you considered productionization
- Can you handle feedback? → YES, be open and thoughtful
- Will you fit the team? → YES, show collaboration and curiosity

### Remember:
- **You built this** - you're the expert on your code
- **Gaps are OK** - senior engineers don't know everything
- **Thinking matters more than memorization** - reason through unknowns
- **They want you to succeed** - they've invested 4 interviews already

---

## POST-INTERVIEW

### Immediately After:
- Write down what went well
- Write down what you'd improve
- Send a thank-you email within 24 hours

### Thank You Email Template:
```
Subject: Thank you - Senior Data Engineer Discussion

Hi [Name],

Thank you for the thoughtful discussion today about the SkillCorner ETL pipeline.

I particularly enjoyed diving into [specific topic they asked about] and discussing [something they mentioned about Traits].

[If you realized something after:] After our conversation, I reflected on [question you struggled with] and wanted to share my thoughts: [brief insight].

I'm excited about the opportunity to contribute to Traits' data platform and help deliver insights that drive real impact for football clubs.

Looking forward to hearing from you.

Best regards,
Angus
```

---

## FINAL THOUGHTS

You've built a solid, well-documented ETL pipeline that demonstrates:
- Strong data engineering fundamentals
- Production-oriented thinking
- Clear communication through documentation
- Thoughtful metric design

This prep plan gives you the structure to master every detail. Trust your preparation, think out loud, and remember: **you're interviewing them too** - make sure this is a team you want to join.

Good luck! 🚀
