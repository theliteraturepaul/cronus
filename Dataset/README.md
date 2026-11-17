# Cronus dataset

## Source and integrity

| Item | Value |
| --- | --- |
| Original local source | `telecom_churn.csv` (repository root, gitignored) |
| Canonical committed copy | `Dataset/project_dataset.csv` |
| SHA-256 (both files) | `a1c3992fcb8da9523aa0f8074f87ce0c2247cac551e3a4fdee02c2690aa2f048` |
| Size | 842,073 bytes |
| Shape | 10,000 data rows × 14 source columns |
| Snapshot date | 2023-05-04 |
| Registration date range | 2020-01-01 to 2023-05-04 |
| Missing values | None |
| Exact duplicate rows | None |

The two files are byte-identical. The root file is kept as the untouched local
original; `Dataset/project_dataset.csv` is the file committed to the
repository and uploaded through Streamlit.

## Dataset grain

One row is one **customer-provider relationship**, not one unique customer.

- 10,000 customer-provider relationships
- 8,860 unique `customer_id` values
- 1,020 customers have more than one provider relationship:
  - 7,840 customers have 1 relationship
  - 900 customers have 2 relationships
  - 120 customers have 3 relationships
- 33 customer-provider pairs recur at a later date (for example A → B → A).
  These are legitimate return/re-entry relationships, not duplicates.
- 1,140 relationships are historical (non-latest) and all 1,140 are churned
  by dataset construction.
- 8,860 relationships are each customer's latest relationship.

`customer_id` is intentionally non-unique. Do not deduplicate the file, reject
multi-provider customers, or warn that a returning customer-provider pair is a
duplicate.

## Churn semantics

| Measure | Definition | Count | Rate |
| --- | --- | --- | --- |
| Relationship churn | All 10,000 relationships with `churn = 1` | 1,987 | 19.87% |
| Current customer churn | Latest relationship per customer with `churn = 1` | 847 | 9.56% |

Relationship churn covers the full history and must never be presented as the
current customer churn rate. Current churn is computed only from each
customer's latest provider relationship.

## Columns

| Column | Type in source | Description |
| --- | --- | --- |
| `customer_id` | text | Customer identifier; repeats across provider relationships |
| `telecom_partner` | text | Provider: Airtel, BSNL, Reliance Jio, or Vodafone |
| `gender` | text | `M` or `F` (source values are already normalised) |
| `age` | integer | Customer age, 15–100 |
| `state` | text | State name (32 states) |
| `city` | text | City name (81 cities) |
| `pincode` | text | Six-digit pincode; synthetic and not a reliable geographic key |
| `date_of_registration` | date | Provider registration date in `DD-MM-YYYY` format |
| `num_dependents` | integer | Number of dependents, 0–20 |
| `estimated_salary` | integer | Estimated salary, greater than zero |
| `calls_made` | integer | Calls made, non-negative |
| `sms_sent` | integer | SMS sent, non-negative |
| `data_used` | integer | Data used, non-negative |
| `churn` | integer | Provider-specific churn flag: 1 = churned, 0 = retained |

## Derived fields created during ingestion

| Field | Description |
| --- | --- |
| `record_id` | Surrogate primary key for the relationship row |
| `dataset_id` | Uploaded snapshot that owns the row |
| `source_row_number` | 1-based data row in the original CSV, excluding the header |
| `relationship_seq` | 1-based order by `(registration_date, source_row_number)` within `customer_id` |
| `relationship_count` | Total relationships for that customer in the dataset |
| `is_latest_relationship` | True only when `relationship_seq = relationship_count` |
| `tenure_days` | Historical: next registration date minus current date. Latest: snapshot date minus current date |
| `created_at` | Database insertion timestamp (UTC) |

The next registration date is used as a proxy for the switch date because the
dataset contains no explicit churn date. Latest-relationship tenure is measured
to the snapshot date, 2023-05-04.

## Data-quality notes

- Gender is stable within a customer in this snapshot. The validator warns if a
  future file contains inconsistent gender values for the same customer.
- Age changes in 722 multi-provider groups and state in 157.
- Pincode changes in all 1,020 multi-provider groups. It is synthetic noise,
  so do not use it as a stable geographic key.
- The validator normalises gender to `M`/`F`, trims text, parses dates, and
  zero-pads short pincodes. These are warnings, not rejection reasons.
- Multi-provider records, re-entry pairs, and churned historical relationships
  are valid observations and are never treated as duplicates.

## Use in Phase 2

The executed notebook at `Python/analysis.ipynb` reads this canonical file
directly through `cronus.validation.validate_csv`. It checks the SHA-256 hash
and file size before analysis. The notebook needs no Neon connection, `.env`
file, or credentials.

It keeps the relationship grain and reports relationship churn (19.87%) and
current customer churn (9.56%) separately. It also uses the derived fields from
the validation service, including `relationship_seq`, `relationship_count`,
`is_latest_relationship`, and `tenure_days`.

To re-execute the notebook:

```bash
uv sync --group notebook
uv run --group notebook jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=900 \
  Python/analysis.ipynb
```

## Use in Phase 3

Machine-learning work models current/latest relationships only. Including
historical relationships would leak the dataset construction rule that every
non-latest relationship is churned.

The executed notebook at `Python/modeling.ipynb` follows this rule. It trains on
the 8,860 latest relationships and excludes the 1,140 historical rows. It reads
the canonical CSV through `cronus.modeling.load_current_frame`.

## Use in Phase 4

The Streamlit application reads the active dataset from Neon. It uses only rows
with `is_latest_relationship = TRUE` for analytics and scoring. Historical rows
never enter a page, a model fit, or a scored export. The repository read raises
an error if a customer appears twice on the current grain, so it never
deduplicates the frame.

The Phase 4 app does not change this CSV. It does not add a model artifact or a
prediction table. The final Phase 3 logistic model is refitted on the active
current frame and cached in the Streamlit process. The decision threshold stays
fixed at 0.1840 for the default policy and 0.0981 for the 70% recall policy.
Every score display and CSV export carries the applied threshold.

The app keeps the two churn measures separate:

- **Relationship churn (all history):** 19.87% in the baseline snapshot
- **Current customer churn (latest only):** 9.56% in the baseline snapshot

Pages that compare segments or score relationships use only the current
customer churn grain. The Overview and Admin pages show both measures with
explicit labels.
