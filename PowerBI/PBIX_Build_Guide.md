# Power BI Dashboard Build Guide (Option A: score in Power Query)

## Overview

This guide builds `PowerBI/project_dashboard.pbix` in **Import mode**. Power
Query reads the active dataset from Neon, keeps the latest relationship for
each customer, reproduces the Phase 3 preprocessing, and applies the fixed
logistic regression coefficients. Power BI computes every score. The PBIX does
not read a scored CSV and does not call Python at view time.

The report has five pages:

1. Overview
2. Providers and segments
3. Usage and tenure
4. Model performance
5. Churn predictions

---

## Prerequisites

- Power BI Desktop, current version.
- Network access to Neon Postgres. Neon uses port 5432 and requires SSL.
- The Neon user name and password. Do not put the password in a file.
- One active dataset in Neon. The Streamlit Admin page sets the active dataset.
- PostgreSQL connectivity from the Power BI Service for scheduled refresh. No
  gateway is necessary for Neon.

---

## Data Model

| Query | Load | Grain | Rows (baseline) |
| --- | --- | --- | --- |
| `Config` | Disabled | One record of fixed parameters | 1 |
| `ActiveDataset` | Enabled | One active snapshot | 1 |
| `CurrentRelationships` | Disabled | Latest relationship per customer | 8,860 |
| `DateTable` | Enabled | One row per calendar date | 1,461 |
| `ScoredRelationships` | Enabled | Same grain as `CurrentRelationships` plus scores | 8,860 |

`Config` returns a record, not a table, so disable its load. `CurrentRelationships`
is an intermediate query. `ScoredRelationships` consumes it, so the model needs
only the scored table.

### Relationships

Do not create relationships between these tables.

- `ActiveDataset` has one row of constants. Every measure reads it with `MAX`,
  so no filter relationship is necessary.
- `ScoredRelationships` is the only fact table. All current-grain measures and
  visuals use it.
- `DateTable` is a disconnected calendar. The required pages use the
  `Registration Year`, `Tenure Band`, and `Age Band` calculated columns.
- The evidence tables on the Model performance page are disconnected fixed
  values.

A relationship from `ActiveDataset` to `ScoredRelationships` is impossible:
`ScoredRelationships` has no `dataset_id` column. A relationship from
`CurrentRelationships` to `ScoredRelationships` duplicates one grain. Do not add
either one.

---

## Build Steps

### 1. Create the queries

1. Open Power BI Desktop.
2. Select **Home > Transform Data** to open Power Query Editor.
3. Select **Home > New Source > Blank Query**.
4. Select **Home > Advanced Editor**. Delete the default text.
5. Open `PowerBI/PowerQuery_M_Scoring.txt`. Copy the **Query 1 of 5: Config**
   block from `let` to `in Config`. Paste it.
6. Select **Done**. Rename the query `Config`.
7. Right-click `Config` and clear **Enable load**.
8. Repeat steps 3 to 6 for the other four queries, in this order:
   `ActiveDataset`, `CurrentRelationships`, `DateTable`,
   `ScoredRelationships`.
9. Rename each query exactly as the block header says.
10. Right-click `CurrentRelationships` and clear **Enable load**.
11. Set `PG_Server` and `PG_Database` in `Config`:
    - `PG_Server`: the Neon pooled host, for example
      `ep-xxxx-pooler.region.aws.neon.tech`. Do not add `https://` or a port.
    - `PG_Database`: `neondb` for this project.

Power BI prompts for the database credentials on the first connection. Choose
**Database** authentication, enter the Neon user name and password, and select
**Connect**. The credential cache keeps the password. The script contains no
password.

If Power BI shows a privacy-level prompt, set the file to **Ignore privacy
levels** for this project. The queries read one database and do not combine
sources.

### 2. Check the load

| Query | Expected |
| --- | --- |
| `Config` | Not loaded |
| `ActiveDataset` | 1 row, 15 columns |
| `CurrentRelationships` | 8,860 rows, 15 columns |
| `ScoredRelationships` | 8,860 rows, 22 columns |
| `DateTable` | 1,461 rows, 6 columns |

The M script already sets the column types. Do not change them. If Power BI
prompts to add a step after a type change, remove the extra step.

### 3. Add the DAX objects

Open `PowerBI/DAX_Measures.txt`. Add each block in this order:

1. Calculated columns on `ScoredRelationships`: `Age Band`, `Tenure Band`,
   `Registration Year`, `Calls Quartile`, `SMS Quartile`, `Data Quartile`.
2. Measures for `ActiveDataset` constants.
3. Measures for current customer churn and the Wilson interval.
4. Measures for the scored queue.
5. The disconnected `ThresholdSelector` table and its measures.
6. The fixed evidence tables: `ModelMetrics`, `ConfusionMatrix`,
   `ThresholdPolicies`, `PermutationImportance`, `SubgroupRecall`,
   `CalibrationBins`, `TemporalCheck`.

Format these measures as percentages with two decimals:
`[Relationship Churn Rate]`, `[Current Churn Rate]`, `[Multi-Provider %]`,
`[Provider Churn Rate]`, `[Provider Share of Base]`, `[Flagged Rate Default]`,
`[Flagged Rate Recall70]`, `[Flagged Rate Selected]`, `[Wilson Lower]`,
`[Wilson Upper]`, `[Mean Score Default]`, `[Mean Score Recall70]`.

Format `[Mean Score Default]` as a percentage with four decimals. Format
scoring columns as percentages with two decimals.

### 4. Add the report pages

Create five pages and use the exact names from the Overview list. Add a text box
with the report title, the snapshot date (`[Snapshot Date]`), and the dataset
name on the Overview page.

---

## Page 1: Overview

| Visual | Configuration |
| --- | --- |
| Card | `[Total Relationships]` = 10,000 |
| Card | `[Unique Customers]` = 8,860 |
| Card | `[Relationship Churn Rate]` = 19.87% |
| Card | `[Current Churn Rate]` = 9.56% |
| Card | `[Multi-Provider %]` = 11.51% |
| Card | `[Re-Entry Pairs]` = 33 |
| Card | `[Partner Count]` = 4 |
| Card | `[Snapshot Date]` = 2023-05-04 |
| Card | `[Registration Window]` = 2020-01-01 to 2023-05-04 |
| Table | Rows: `ScoredRelationships[relationship_count]`. Values: `DISTINCTCOUNT(ScoredRelationships[customer_id])`, `[Provider Churn Rate]` |
| Text box | Dual-grain warning (below) |

Text box:

> Two rates, two grains. Relationship churn counts every churn event in the
> history: 1,987 of 10,000 relationships (19.87%). Current customer churn counts
> churned customers on the latest relationship only: 847 of 8,860 (9.56%).
> Never present one rate as the other.

Label the cards with the full names. Do not label 19.87% as "churn rate" alone.

---

## Page 2: Providers and segments

| Visual | Configuration |
| --- | --- |
| Clustered bar chart | Axis: `ScoredRelationships[telecom_partner]`. Values: `[Provider Churn Rate]`. Data labels: on. Error bars: `[Wilson Lower]` and `[Wilson Upper]` |
| Matrix | Rows: `ScoredRelationships[telecom_partner]`, `ScoredRelationships[Age Band]`. Values: `[Provider N]`, `[Provider Churned]`, `[Provider Churn Rate]`, `[Wilson Lower]`, `[Wilson Upper]`, `[Provider Share of Base]`, `[Provider Small Sample]` |
| Table | Rows: `ScoredRelationships[state]`. Values: `[Provider N]`, `[Provider Churned]`, `[Provider Churn Rate]`, `[Wilson Lower]`, `[Wilson Upper]`, `[Provider Small Sample]` |
| Slicer | `ScoredRelationships[telecom_partner]` |
| Slicer | `ScoredRelationships[gender]` |
| Slicer | `ScoredRelationships[state]` |
| Slicer | `ScoredRelationships[age]` as a range |

Use `ScoredRelationships`, not `ActiveDataset`. Every value on this page is
current customer churn. Add a page subtitle: "Current customers only. Latest
relationship per customer."

The provider chart uses the same denominator as the Streamlit page. The overall
rate on this page must equal `[Provider Churn Rate]` with no filter: 9.56%. It
must not equal 19.87%.

Sort the provider chart by `[Provider Churn Rate]` from high to low.

---

## Page 3: Usage and tenure

| Visual | Configuration |
| --- | --- |
| Clustered bar chart | Axis: `ScoredRelationships[Tenure Band]`. Values: `[Provider Churn Rate]`, `[Provider N]` |
| Clustered bar chart | Axis: `ScoredRelationships[Calls Quartile]`. Values: `[Provider Churn Rate]`, `[Provider N]` |
| Clustered bar chart | Axis: `ScoredRelationships[SMS Quartile]`. Values: `[Provider Churn Rate]`, `[Provider N]` |
| Clustered bar chart | Axis: `ScoredRelationships[Data Quartile]`. Values: `[Provider Churn Rate]`, `[Provider N]` |
| Column chart | Axis: `ScoredRelationships[Registration Year]`. Values: `[Provider Churn Rate]`, `[Provider N]` |
| Slicer | `ScoredRelationships[telecom_partner]` |
| Slicer | `ScoredRelationships[age]` as a range |
| Slicer | `ScoredRelationships[tenure_days]` as a range |
| Text box | Association warning (below) |

Text box:

> These charts show observed associations in the active snapshot. They do not
> show causal effects. A higher churn rate in a segment does not prove that the
> segment feature causes churn.

Keep the `N` label on every chart. A rate on a small segment is unstable. Do
not add a correlation table. The Phase 2 notebook owns the correlation evidence.

---

## Page 4: Model performance

This page shows the fixed Phase 3 evidence. Do not recompute these values from
the current frame. Use the disconnected tables from `DAX_Measures.txt`.

| Visual | Configuration |
| --- | --- |
| Table | `ModelMetrics`: Metric, Value, Note |
| Matrix | `ConfusionMatrix`: Rows: Outcome. Values: Sum of Count |
| Table | `ThresholdPolicies`: Policy, Threshold, Precision, Recall, F1, Note |
| Bar chart | `PermutationImportance`: Axis: Feature. Values: PR-AUC drop |
| Bar chart | `SubgroupRecall`: Axis: Group. Values: Recall |
| Table | `CalibrationBins`: Bin, N, Mean predicted, Observed rate, Gap |
| Table | `TemporalCheck`: Metric, Value |
| Text box | Claim warning (below) |

Text box:

> Fixed Phase 3 evidence. Holdout: PR-AUC 0.2312, ROC-AUC 0.7295, Brier 0.0806.
> Confusion matrix at threshold 0.1840: 1,423 true negatives, 180 false
> positives, 112 false negatives, 57 true positives. Temporal check: threshold
> 0.1410, PR-AUC 0.2776, ROC-AUC 0.7450, Brier 0.0941, prevalence 11.55%.
> The model is observational and not production-ready. Subgroup recall is
> uneven: BSNL 0.577, Airtel 0.375, Vodafone 0.178, Reliance Jio 0.125, and
> 0.000 for the highest calls quartile. These results do not show fairness or
> causal effects.

The confusion matrix is the holdout matrix, not the current queue. Label it
"Holdout evaluation at 0.1840". Do not connect it to `ScoredRelationships`.

---

## Page 5: Churn predictions

| Visual | Configuration |
| --- | --- |
| Slicer | `ThresholdSelector[Label]` |
| Card | `[Selected Policy Label]` |
| Card | `[Scored Count]` = 8,860 |
| Card | `[Flagged Count Selected]` = 1,180 or 3,286 |
| Card | `[Flagged Rate Selected]` = 13.32% or 37.09% |
| Card | `[Elevated or High Count Selected]` |
| Card | `[Mean Score Default]` |
| Table | Rank, customer, provider, state, tenure, calls, SMS, data, score, both flags, both thresholds, both priorities (below) |
| Slicer | `ScoredRelationships[telecom_partner]` |
| Slicer | `ScoredRelationships[state]` |
| Slicer | `ScoredRelationships[review_priority_default]` |
| Text box | Decision warning (below) |

Table columns, in order:

1. `score_rank`
2. `customer_id`
3. `telecom_partner`
4. `state`
5. `tenure_days`
6. `calls_made`
7. `sms_sent`
8. `data_used`
9. `churn_probability`
10. `predicted_churn_default`
11. `threshold_default`
12. `predicted_churn_recall70`
13. `threshold_recall70`
14. `review_priority_default`
15. `review_priority_recall70`

Rename the columns so each one shows its threshold:

- `predicted_churn_default` becomes `Flagged at 0.1840`
- `threshold_default` becomes `Threshold (default)`
- `predicted_churn_recall70` becomes `Flagged at 0.0981`
- `threshold_recall70` becomes `Threshold (recall-70)`
- `churn_probability` becomes `Churn probability`

Set a visual-level advanced filter on `score_rank` to `is less than or equal
to 100`. The full table remains exportable. The 100-row view is a display
limit, not a model limit.

Text box:

> Every row carries its threshold. A flag is a model decision, not an observed
> churn event. The default policy flags 1,180 of 8,860 relationships (13.32%).
> The recall-70 policy flags 3,286 (37.09%). Select one policy in the slicer and
> read the flag that matches it.

Do not show a single unlabeled "Flagged" column. The two policies disagree by
design.

---

## Validation Checklist

| Check | Expected |
| --- | --- |
| `Config` load is disabled | Yes |
| `CurrentRelationships` load is disabled | Yes |
| `ActiveDataset` rows | 1 |
| `ScoredRelationships` rows | 8,860 |
| `DateTable` rows | 1,461 |
| `ScoredRelationships[churn_probability]` range | 0 to 1 |
| `[Flagged Count Default]` | 1,180 |
| `[Flagged Rate Default]` | 13.32% |
| `[Flagged Count Recall70]` | 3,286 |
| `[Flagged Rate Recall70]` | 37.09% |
| `[Flagged Count Selected]` at Max-F1 | 1,180 |
| `[Flagged Count Selected]` at Recall-70 | 3,286 |
| Overview shows 19.87% and 9.56% with different labels | Yes |
| Provider page overall rate | 9.56% |
| Model performance page shows the fixed numbers | Yes |
| No causal, production-readiness, or fairness claim | Yes |

If `[Flagged Count Default]` is not 1,180, stop. Compare the M script with
`powerbi_model_export.json`. The unit test `tests/test_powerbi_export.py` checks
that the two files agree. The likely causes are a stale coefficient, a wrong
state category, or a changed numeric mean.

---

## Parity Check With the Streamlit App

1. Build the PBIX and refresh it.
2. Open the **Data** view. Right-click `ScoredRelationships` and select
   **Export data** as CSV. Keep the raw column names.
3. Run:

   ```bash
   uv run python PowerBI/verify_scores.py path/to/exported_scores.csv
   ```

4. Require `max_probability_diff <= 1e-6` and both flag columns true. A correct
   build shows about `3.9e-16`, because both paths use the same 43 coefficients.

The script refits the fixed Phase 3 pipeline on the active current frame and
compares every customer. It reads the database. Set `DATABASE_URL` in `.env`
first.

The comparison holds while the active dataset is the baseline snapshot. A new
active dataset changes the Python refit, and the PBIX keeps the fixed
coefficients in `powerbi_model_export.json`. Regenerate the export before you
compare scores on a different dataset.

---

## Publish and Refresh

1. Select **Publish** and choose the workspace.
2. Open the dataset settings and edit the data source credentials. Use the Neon
   user name and password.
3. Set **Scheduled refresh** to daily at 06:00 UTC.
4. Set the privacy level to **Organizational** or **Ignore privacy levels**.
5. Run **Refresh now** and check the refresh history.
6. Open the report and repeat the validation checklist.

No gateway is necessary for a cloud Neon database. If the Power BI Service
cannot reach the pooled host, use the direct Neon host for refresh and keep the
pooled host for the Streamlit app.

---

## Troubleshooting

| Issue | Resolution |
| --- | --- |
| "The name 'PostgreSQL.Database' was not recognized" | Use a current Power BI Desktop version. The connector is built in. |
| Credential prompt repeats | Delete the data source permission in **File > Options and settings > Data source settings** and connect again. |
| SSL error | Neon requires SSL. Use the host name only. Do not include `sslmode` in `PG_Server`. |
| `Value.NativeQuery` returns an error | Confirm the active dataset exists. The Streamlit Admin page sets it. |
| The Config query cannot load | This is expected. Disable load on `Config`. |
| The CurrentRelationships query cannot load | This is expected. Disable load. `ScoredRelationships` still reads it. |
| Flag counts differ | Run `uv run pytest tests/test_powerbi_export.py -q`. Compare the M constants with the JSON export. |
| Refresh is slow | The M scoring loop runs on 8,860 rows. It should finish in seconds. Check the query diagnostics before you change the logic. |
| New state appears | The M script maps an unseen state to all zeros, which matches `handle_unknown="ignore"`. It does not map the new state to `state_infrequent_sklearn`. |

---

## Files in This Directory

| File | Purpose |
| --- | --- |
| `PowerQuery_M_Scoring.txt` | Five Power Query queries: Config, ActiveDataset, CurrentRelationships, DateTable, ScoredRelationships |
| `DAX_Measures.txt` | Calculated columns, measures, threshold selector, fixed evidence tables |
| `powerbi_model_export.json` | Model parameters: intercept, 43 coefficients, scaler, categories, thresholds |
| `verify_scores.py` | Build-time parity check against the Streamlit scoring path |
| `PBIX_Build_Guide.md` | This guide |
| `project_dashboard.pbix` | Output. Build it on Windows with Power BI Desktop. |

---

## Submission

The deliverable is `PowerBI/project_dashboard.pbix`. It satisfies submission
item `05_PowerBI/project_dashboard.pbix`.

The report makes no causal claim, no production-readiness claim, and no
fairness claim. It reports observed associations and fixed holdout evidence.
