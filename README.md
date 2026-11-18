# Cronus — Telecom Churn Intelligence

**Deployed app:** https://churn-lab.streamlit.app/

Cronus is a customer-provider relationship analytics system for telecom churn.
It combines a Python data platform, a scikit-learn churn model, a Streamlit
interface, Neon Postgres, and a later Power BI dashboard. The project is being
built for a Data Analytics with Python and Power BI internship.

The canonical dataset is [`Dataset/project_dataset.csv`](Dataset/project_dataset.csv).
One row is one customer-provider relationship; `customer_id` is intentionally
non-unique. See [`Dataset/README.md`](Dataset/README.md) for the full data
contract and integrity details.

## Status

Phase 1 — foundation and data platform — is implemented and verified:

- Python 3.13 project managed by uv
- SQLAlchemy 2.0 models and Alembic migration for Neon Postgres
- Robust CSV validation and transactional ingestion
- Streamlit page for connection status, active-dataset summary, upload, and
  dataset activation
- Unit tests, a DB-test suite, Ruff, mypy, and GitHub Actions CI
- Baseline snapshot loaded and verified:
  - 10,000 relationships
  - 8,860 unique customers
  - 19.87% relationship churn (1,987 relationships)
  - 9.56% current customer churn (847 latest relationships)
  - 1,020 multi-provider customers and 33 re-entry pairs

Phase 2 — exploratory data analysis — is implemented and verified:

- Executed notebook at [`Python/analysis.ipynb`](Python/analysis.ipynb) with 55
  cells (25 markdown, 30 code) and 12 figures
- Reads the canonical CSV through `cronus.validation.validate_csv`; it needs no
  database, `.env` file, or credentials
- Reports relationship churn and current customer churn separately
- Adds Wilson 95% confidence intervals and descriptive tables
- Trains no model and makes no causal claims
- Runs end to end with all outputs embedded

Phase 3 — current-relationship churn model — is implemented and verified:

- Reusable package at `src/cronus/modeling/` for features, pipelines, evaluation,
  and training
- Executed notebook at [`Python/modeling.ipynb`](Python/modeling.ipynb) with 43
  cells (15 markdown, 28 code) and 10 figures
- Trains on the 8,860 latest relationships only and never on historical rows
- Compares logistic regression with a gradient-boosted tree under five-fold
  stratified cross-validation
- Final model: logistic regression with 10 features and no
  `relationship_count`
- Holdout PR-AUC 0.231, ROC-AUC 0.729, Brier 0.081
- Max-F1 threshold 0.184 gives 0.241 precision and 0.337 recall
- Includes calibration, permutation importance, subgroup recall, and a temporal
  check
- No model artifact, database write, or prediction UI

Phase 4 — analytics UI and admin workflow — is implemented:

- Multipage Streamlit application under `app/` with Overview, Providers and
  segments, Usage and tenure, Model performance, Churn predictions, Admin, and
  Account pages
- Current-relationship reads only: analytics and scoring never use historical
  rows and never deduplicate the current grain
- The fixed Phase 3 logistic model is refitted on the active current frame and
  cached in the Streamlit process with `st.cache_resource`
- Every score display and CSV export carries its decision threshold
- A seeded administrator account and a password gate protect upload,
  replacement, and activation, and the gate fails closed when no password is
  configured
- No model artifact, prediction table, or new runtime dependency

Phase 4 addendum (2026-11-18): the app now has local email/password accounts and
site-wide visitor analytics. Every dashboard page requires a signed-in account,
and the Admin page keeps its separate password gate for viewer accounts. The
visitor strip shows unique visitors, seven-day visitors, seven-day page views,
and account count. Migration `0002` adds `app_users` and `visitor_events`.
Migration `0003` adds the seeded administrator username and role flag, so one
fixed login opens the dashboard and the Admin page.

Phase 5 is complete. Phase 6 is in progress: the Power Query scoring, the DAX
objects, and the build guide are ready, and the PBIX build is pending. Phase 7
is not started.

## Architecture

```mermaid
flowchart LR
    analyst[Analyst] -->|admin sign-in<br/>uploads CSV| streamlit[Streamlit app<br/>app/main.py]
    csv[Dataset/project_dataset.csv] --> streamlit
    csv -->|validation service| notebook[Python/analysis.ipynb<br/>Phase 2]
    csv -->|modeling modules| modeling[Python/modeling.ipynb<br/>Phase 3]
    streamlit -->|SQLAlchemy 2.0<br/>psycopg 3| neon[(Neon Postgres)]
    neon -->|Import mode<br/>Phase 6| powerbi[Power BI dashboard]
    streamlit -->|validated ingestion| neon
```

- The Streamlit application is the only data-loading interface and the only
  application interface. There is no custom CLI or console entry point. The
  administrator account is seeded at application start-up.
- The app has seven pages. The Admin page is the only place that uploads,
  replaces, or activates a dataset, and it requires the seeded administrator
  account or the admin password.
- The Phase 2 and Phase 3 notebooks read the canonical CSV through the
  validation service. They do not connect to Neon.
- Alembic is the only command-line tool used to change the database schema.
- The application uses the pooled Neon URL; Alembic uses the direct URL.

## Stack

| Layer | Choice |
| --- | --- |
| Runtime | Python 3.13 (`>=3.13,<3.14`), managed by uv |
| UI | Streamlit 1.66+ |
| Data | pandas, NumPy |
| Modeling | scikit-learn 1.9 (logistic regression, gradient-boosted tree) |
| Database | Neon Postgres |
| ORM / SQL | SQLAlchemy 2.0, psycopg 3 |
| Migrations | Alembic |
| Validation / config | Pydantic v2, pydantic-settings |
| Notebook / EDA | JupyterLab, ipykernel, matplotlib, seaborn, nbconvert |
| Quality | Ruff, mypy, pytest, pytest-cov |
| CI | GitHub Actions |

## Repository layout

```text
.
├── Dataset/
│   ├── project_dataset.csv        # byte-identical committed dataset
│   └── README.md                  # source, SHA-256, shape, semantics
├── Python/analysis.ipynb          # executed Phase 2 EDA notebook
├── Python/modeling.ipynb          # executed Phase 3 modeling notebook
├── PowerBI/
│   ├── PowerQuery_M_Scoring.txt   # five Power Query queries for scoring
│   ├── DAX_Measures.txt           # measures, columns, fixed evidence tables
│   ├── PBIX_Build_Guide.md        # build steps for the five report pages
│   ├── powerbi_model_export.json  # intercept, 43 coefficients, scaler
│   └── verify_scores.py           # PBIX vs Streamlit parity check
├── GitHub/README.md               # copy of the root README (Phase 7)
├── app/
│   ├── main.py                    # navigation shell and page registration
│   ├── shared.py                  # cached reads, sidebar, and UI helpers
│   └── views/
│       ├── overview.py            # dual-grain snapshot summary
│       ├── providers.py           # provider and segment comparisons
│       ├── usage.py               # tenure, usage, cohorts, correlations
│       ├── performance.py         # Phase 3 model card and checks
│       ├── predictions.py         # scored review queue and CSV export
│       ├── account.py             # sign-up, sign-in, session, and sign-out
│       └── admin.py               # administrator gate, upload, activation
├── src/cronus/
│   ├── __init__.py
│   ├── accounts.py                # account persistence and authentication
│   ├── auth.py                    # scrypt hashing, policy, admin password check
│   ├── config.py                  # settings and URL normalisation
│   ├── db.py                      # pooled engine, sessions, status
│   ├── logging.py
│   ├── models.py                  # SQLAlchemy models
│   ├── repository.py              # typed read/activation queries
│   ├── schemas.py                 # Pydantic contracts and errors
│   ├── validation.py              # CSV normalisation and derivation
│   ├── ingest.py                  # transactional ingestion service
│   ├── analytics.py               # current-grain descriptive tables
│   ├── visitors.py                # anonymous page views and counts
│   └── modeling/
│       ├── __init__.py            # public modeling API
│       ├── features.py            # feature contract, current frame, splits
│       ├── pipelines.py           # preprocessing, logistic and tree pipelines
│       ├── evaluation.py          # metrics, thresholds, calibration
│       ├── serving.py             # final model contract and batch scoring
│       └── training.py            # CV, tuning, final fit, prediction
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_accounts_and_visitors.py
│       └── 0003_admin_account.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_auth.py
│   ├── test_accounts.py
│   ├── test_visitors.py
│   ├── test_analytics.py
│   ├── test_serving.py
│   ├── test_validation.py
│   ├── test_modeling.py
│   ├── test_powerbi_export.py
│   ├── test_ingest_db.py
│   └── test_accounts_db.py
├── .github/workflows/ci.yml
├── .streamlit/config.toml
├── .editorconfig
├── .gitattributes
├── .gitignore
├── .env.example
├── .python-version
├── alembic.ini
├── pyproject.toml
├── uv.lock
└── README.md
```

The untouched local original `telecom_churn.csv` stays at the repository root
and is gitignored. `Dataset/project_dataset.csv` is the canonical committed
copy.

## Quickstart

### 1. Prerequisites

- A Neon project. Copy the pooled and direct connection strings from the Neon
  console.
- [uv](https://docs.astral.sh/uv/) installed. The project prepares `uv` at
  `~/.local/bin` during development:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  ```

### 2. Configure the environment

```bash
cp .env.example .env
# Edit .env and fill DATABASE_URL and DIRECT_URL.
# Set ADMIN_PASSWORD to a non-empty value.
```

Never commit `.env`. `DATABASE_URL` must be the pooled Neon URL (its host
contains `-pooler`). `DIRECT_URL` must be the direct, unpooled URL used only by
Alembic. Connection strings are normalised to
`postgresql+psycopg://` with `sslmode=require`; passwords are masked in any
display.

Set the seeded administrator account in `.env`:

```bash
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@cronus.local
ADMIN_DISPLAY_NAME=Administrator
ADMIN_PASSWORD=choose-a-long-password
```

The app creates or updates this account at start-up. It has no self-service
sign-up and no separate Admin page password prompt. Use a long password. The
seed accepts any non-empty value because the operator owns this credential. The
repository never contains the value.

The app also accepts a Streamlit secret. Create `.streamlit/secrets.toml`
(gitignored) when you prefer that route:

```toml
admin_password = "choose-a-long-password"
```

The Streamlit secret has priority over `ADMIN_PASSWORD`. If neither value is
set, the seed is skipped and the Admin page stays locked. Upload, replacement,
and activation are then unavailable.

Set the visitor hash salt in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Copy the output into .env:
VISITOR_HASH_SALT=the-generated-value
```

The salt is a secret. A blank value disables visitor recording.

### 3. Install and migrate

```bash
uv sync --frozen
uv run alembic upgrade head
```

The migration creates the `datasets`, `customer_relationships`, `app_users`, and
`visitor_events` tables. The application never runs migrations at startup.

### 4. Run the app

```bash
uv run streamlit run app/main.py
```

Open the local Streamlit URL. The first page is **Account**. Sign in with
`admin` and the `ADMIN_PASSWORD` value. The seven sidebar pages appear. A new
viewer can use the **Create account** tab instead, and the admin account then
opens every page. To load the baseline snapshot, open **Admin**, upload
`Dataset/project_dataset.csv`, give the dataset a name, keep **Activate after
load** checked, and click **Load dataset**.

The app builds the model when you first open **Churn predictions**. The fit runs
in the Streamlit process on the active current-relationship frame. No model file
is written. The pages are:

1. **Overview** — active snapshot and dual-grain churn
2. **Providers and segments** — provider, gender, age-band, and state tables
3. **Usage and tenure** — tenure bands, usage quartiles, cohorts, and rank
   correlations
4. **Model performance** — fixed Phase 3 model card, thresholds, confusion
   matrix, calibration, subgroup recall, and temporal check
5. **Churn predictions** — scored review queue with filtered and full CSV
   downloads
6. **Admin** — administrator account or password gate, upload, replacement, and
   activation
7. **Account** — sign-up, sign-in, session details, and sign-out

### 5. Run the analysis notebook

The notebook needs no database and no `.env` file. It reads
`Dataset/project_dataset.csv` directly.

```bash
uv sync --group notebook
uv run --group notebook jupyter lab Python/analysis.ipynb
```

To re-execute the notebook in place and refresh every output:

```bash
uv run --group notebook jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=900 \
  Python/analysis.ipynb
```

### 6. Run the modeling notebook

The Phase 3 notebook needs no database and no `.env` file. It trains on the
current relationships in `Dataset/project_dataset.csv`.

```bash
uv run --group notebook jupyter lab Python/modeling.ipynb
```

To re-execute it in place:

```bash
uv run --group notebook jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=1800 \
  Python/modeling.ipynb
```

### 7. Run quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not db" -q
```

DB tests are opt-in because they write to a dedicated test database:

```bash
# Set TEST_DATABASE_URL to a separate Neon database or branch first.
uv run pytest -m db -q
```

Database tests refuse to run when `TEST_DATABASE_URL` equals `DATABASE_URL`.

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | — | Pooled Neon URL used by the Streamlit app |
| `DIRECT_URL` | no | `DATABASE_URL` | Direct URL used by Alembic; recommended |
| `TEST_DATABASE_URL` | no | — | Separate database/branch for `-m db` tests |
| `APP_ENV` | no | `development` | `development`, `test`, or `production` |
| `LOG_LEVEL` | no | `INFO` | Python logging level |
| `ADMIN_USERNAME` | no | `admin` | Seeded administrator sign-in name |
| `ADMIN_EMAIL` | no | `admin@cronus.local` | Seeded administrator email address |
| `ADMIN_DISPLAY_NAME` | no | `Administrator` | Seeded administrator display name |
| `ADMIN_PASSWORD` | no | — | Seed password and Admin page gate. Blank skips the seed and keeps the gate locked |
| `VISITOR_HASH_SALT` | no | — | Secret salt for the anonymous visitor HMAC. Blank disables visitor recording |
| `ALLOW_SIGNUP` | no | `true` | Show the create-account form on the Account page |
| `SESSION_MAX_HOURS` | no | `12` | Signed-in session lifetime in hours |
| `MAX_UPLOAD_MB` | no | `25` | Upload size guard |
| `MAX_UPLOAD_ROWS` | no | `200000` | Upload row guard |

Settings are loaded from the repository-root `.env`, independent of the current
working directory. Environment variables take precedence over the file.

## Using the Streamlit app

The app registers seven pages with `st.navigation` and `st.Page` in
`app/main.py` after sign-in. A signed-out visitor gets only the Account page.
`app/shared.py` owns cached database reads, the sidebar, the visitor strip, and
reusable display helpers. Page modules live in `app/views/`.

A bordered visitor strip sits above every page, including the sign-in page. It
shows unique visitors, seven-day visitors, seven-day page views, and the active
account count. The strip never blocks the page, and it renders nothing when the
database read fails.

- **Overview**: active dataset name, snapshot date, registration window,
  unique customers, relationship counts, partner count, multi-provider
  customers, re-entry pairs, and the two churn measures side by side.
- **Providers and segments**: current churn by provider, gender, age band, and
  state. Filters cover provider, gender, state, and age. Tables show counts,
  rates, Wilson 95% intervals, and a small-sample flag.
- **Usage and tenure**: current churn by tenure band, calls/SMS/data quartile,
  and registration year. A Spearman table shows rank associations.
- **Model performance**: the fixed Phase 3 model card, holdout and
  cross-validation metrics, threshold policies, confusion matrix at 0.1840,
  permutation importance, subgroup recall, calibration bins, and the temporal
  check.
- **Churn predictions**: a ranked review queue for the active current frame.
  The page offers the two fixed Phase 3 policies. Every metric label, table
  column, filename, and CSV export carries the selected threshold.
- **Admin**: administrator account or password gate, upload, replacement, and
  activation. The seeded `is_admin` account opens the tools after its Account
  page sign-in. A viewer account uses the separate password gate. The gate
  resolves `st.secrets["admin_password"]` first, then `Settings.admin_password`
  from `ADMIN_PASSWORD`. When both are blank, the page fails closed.
- **Account**: create an account, sign in with an email or username, and sign
  out. The page shows the display name, username, email address, and
  member-since date. An administrator badge marks the seeded account. Sign-in
  locks for 60 seconds after five failed attempts in one session.

Every page except Account requires a signed-in account. Admin actions need the
administrator account or a viewer session that passed the separate password
gate.

Cached reads have a 60-second TTL. The sidebar **Refresh data** button clears
both the data cache and the fitted-model cache. Uploads and activations also
clear both caches. The app does not contain SQL; it calls repository, account,
visitor, and ingestion services only.

The model is fitted once per active dataset version and cached with
`st.cache_resource`. It uses the Phase 3 `fit_final_model` and `predict_churn`
functions with fixed hyperparameters, 10 features, and no
`relationship_count`. The app never retunes, changes the feature set, or
reselects a threshold.

Every export includes a `threshold` column, the policy label, the dataset name,
and the snapshot date. Predictions are not written to the database.

## Exploratory analysis

The Phase 2 notebook keeps the relationship grain and reports two churn
measures side by side:

- **Relationship churn (all history):** 1,987 / 10,000 = 19.87%
- **Current customer churn (latest only):** 847 / 8,860 = 9.56%

These rates answer different questions. The notebook never uses 19.87% as the
current customer churn rate.

The notebook covers:

1. Snapshot verification against the Phase 1 contract
2. Grain, duplicate checks, and attribute stability across relationships
3. Univariate distributions
4. Provider, gender, age, dependents, and state comparisons
5. Tenure bands and usage quartiles
6. Spearman correlations and segment interaction
7. Registration cohorts and a Phase 3 feature contract

Main descriptive findings:

- Usage intensity has the strongest association with current churn. Churn
  falls from about 16–18% in the lowest calls, SMS, or data quartile to about 3%
  in the highest quartile.
- BSNL has the highest current churn at 16.0% (266 of 1,664). Reliance Jio has
  the lowest at 5.9% (154 of 2,603).
- Current churn falls from 12.1% for 0–90 days of tenure to 6.6% after two
  years.
- Older age bands and fewer dependents associate with higher current churn.
  Gender shows no material difference.
- Recent registration cohorts show higher current churn, which is consistent
  with their shorter tenure at the snapshot.

All findings are descriptive. The notebook makes no causal claim. The 1,140
historical relationships are churned by dataset construction, so Phase 3 must
model the 8,860 current relationships only.

## Churn modeling

Phase 3 trains and evaluates the churn model on the 8,860 current relationships.
It never uses the 1,140 historical rows. The package is in
`src/cronus/modeling/`, and the executed notebook is `Python/modeling.ipynb`.

### Model card

| Item | Value |
| --- | --- |
| Model | Logistic regression with L2 penalty |
| Grain | One current customer-provider relationship |
| Target | `churn` |
| Training rows | 8,860 |
| Churn events | 847 (9.56%) |
| Features | 10 |
| Validation | Stratified 5-fold CV plus an 80/20 holdout |
| Threshold | 0.184 (max-F1 on out-of-fold predictions) |
| Holdout PR-AUC | 0.231 (95% CI 0.191–0.293) |
| Holdout ROC-AUC | 0.729 (95% CI 0.688–0.765) |
| Holdout Brier | 0.081 (95% CI 0.078–0.083) |
| Artifact | None. Phase 4 refits and caches the pipeline. |

### Scope and feature contract

The loader filters to `is_latest_relationship` and raises an error if a customer
appears twice on that grain. It never deduplicates rows. The target is `churn`
for the latest relationship. The final model uses 10 features:

- Categorical: `telecom_partner`, `gender`, `state`
- Numeric: `age`, `num_dependents`, `estimated_salary`, `calls_made`,
  `sms_sent`, `data_used`, `tenure_days`

The model excludes identifiers (`customer_id`, `record_id`, `dataset_id`,
`source_row_number`), unstable geography (`pincode`, `city`), bookkeeping fields
(`is_latest_relationship`, `relationship_seq`, `created_at`), and
`date_of_registration`. The registration date is used only for the temporal
check. `relationship_count` is tested and dropped after the ablation.

Rare states are grouped with `OneHotEncoder(min_frequency=50)`. Unseen
categories are ignored. All preprocessing is fitted inside the pipeline.

### Validation design

The notebook asserts the file SHA-256 and the 8,860-row current frame before
training. The primary split is stratified 80/20. The test frame has 1,772
relationships and 169 churn events (9.54%). Model selection uses five stratified
folds on the training frame only. PR-AUC is the primary metric because churn is
the minority class at 9.56%. ROC-AUC, Brier score, and log loss are secondary
checks.

| Candidate | Features | CV PR-AUC | CV ROC-AUC | CV Brier |
| --- | ---: | ---: | ---: | ---: |
| Logistic regression | 11 | 0.2676 ± 0.0532 | 0.7499 | 0.0794 |
| Gradient-boosted tree | 11 | 0.2400 ± 0.0475 | 0.7362 | 0.0810 |
| Logistic regression (final) | 10 | 0.2662 ± 0.0493 | 0.7497 | 0.0794 |

The tree loses on PR-AUC and Brier score. Dropping `relationship_count` changes
CV PR-AUC by −0.0014, which is small against the fold standard deviation. The
final model is the simpler 10-feature logistic regression.

### Threshold policy

The default 0.5 threshold is not usable. The model rarely predicts above 0.5,
so 0.5 catches only 2 of 169 holdout churners.

The notebook selects the threshold on out-of-fold training predictions:

- **Max-F1:** 0.1840. Holdout precision 0.241, recall 0.337, F1 0.281.
- **70% recall floor:** 0.0981. Holdout precision 0.172, recall 0.669, F1 0.273.

Max-F1 is the reported policy. The 70% alternative is available when contact
capacity is higher. Every score must travel with its threshold.

### Holdout results

| Metric | Estimate | 95% bootstrap interval |
| --- | ---: | ---: |
| PR-AUC | 0.2312 | 0.1909–0.2926 |
| ROC-AUC | 0.7295 | 0.6884–0.7654 |
| Brier | 0.0806 | 0.0778–0.0834 |

At the max-F1 threshold the confusion matrix is 1,423 true negatives, 180 false
positives, 112 false negatives, and 57 true positives.

### Interpretation and checks

- **Permutation importance:** `telecom_partner` (0.0434), `data_used` (0.0320),
  `calls_made` (0.0231), and `tenure_days` (0.0178) have the largest holdout
  drops. These are associations, not causal effects.
- **Calibration:** the largest quantile-bin gap is −0.036. The curve stays near
  the diagonal, but individual probabilities are not exact churn rates.
- **Subgroup recall:** at the selected threshold, provider recall is BSNL 0.577,
  Airtel 0.375, Vodafone 0.178, and Reliance Jio 0.125. The highest calls
  quartile has 0.000 recall, so high-usage churners are under-flagged.
- **Temporal check:** train on 2020–2021 and test on 2022–2023. Test PR-AUC is
  0.2776, ROC-AUC is 0.7450, and Brier is 0.0941. The newer period has 11.55%
  churn, so prevalence and calibration shift.

### Phase 4 handoff

The app refits the final pipeline on all current relationships of the active
dataset with the selected hyperparameters and threshold. No model artifact is
committed. Phase 4 imports `fit_final_model` and `predict_churn`, fits on the
active dataset, and caches the pipeline in the Streamlit process.

Phase 4 implements the multipage analytics interface, the scored review queue,
and the admin gate. Phase 5 owns public deployment. Phase 4 adds no database
write, schema change, model artifact, or prediction table.

All results are observational. This section reports descriptive and predictive
results only.

## Current-frame analytics and scoring

`get_current_relationships` reads only rows with
`is_latest_relationship = TRUE`. It aliases the database
`registration_date` column to `date_of_registration`, returns the stored
`tenure_days`, normalises dtypes, and raises an error if a customer appears
twice on the current grain. It never deduplicates rows.

`src/cronus/analytics.py` adds the descriptive table helpers used by the pages:

- Wilson 95% churn intervals
- Provider, gender, age-band, and state tables
- Tenure bands, usage quartiles, and registration cohorts
- Spearman rank correlations
- Current-frame filters that reject historical rows and duplicate customers

`src/cronus/modeling/serving.py` holds the fixed Phase 3 serving contract:

- Model: logistic regression with 10 features and `C=0.1`
- Default threshold: 0.1840
- Alternative threshold: 0.0981 at a 70% recall floor
- Model card, permutation importance, subgroup recall, calibration bins, and
  temporal check values
- `fit_scoring_model`, `score_current_relationships`, and `summarize_scores`

The scored queue contains one row per current customer-provider relationship.
It includes `score_rank`, `churn_probability`, `predicted_churn`,
`review_priority`, and a constant `threshold` column. It never includes the
observed `churn` target.

## Admin workflow

The Admin page is the only page with write controls.

1. When the signed-in account has `is_admin`, open the controls directly. The
   account already passed its password check on the Account page.
2. Otherwise, resolve the admin password from `st.secrets["admin_password"]`,
   then from `ADMIN_PASSWORD` through `Settings`.
3. Fail closed when both values are missing or blank.
4. Compare the candidate with `hmac.compare_digest`.
5. Lock the form for 60 seconds after five failed attempts in one session.
6. Show upload, replacement, and activation controls only after one of the two
   checks passes.

The password is never displayed, logged, stored in the database, or written to
an export. Sign-in lasts for the Streamlit browser session. The sidebar shows
the lock or administrator state and provides sign-out.

Uploads run the existing validation and ingestion services. Validation errors
leave the database unchanged. A byte-identical file offers activation of the
existing dataset or an explicit replacement. Activation is atomic, and a
successful upload or activation clears the data and model caches.

## Accounts and visitor analytics

Migration `0002_accounts_and_visitors.py` adds two tables, and migration
`0003_admin_account.py` extends `app_users`.

- `app_users` stores one row per account: case-folded unique email, optional
  unique lowercase username, display name, scrypt password hash, admin flag,
  active flag, created date, and last sign-in date.
- `visitor_events` stores one row per throttled page view: a 32-character
  visitor digest, the Streamlit session id, an optional account id, the page
  path, and the timestamp.

Accounts are local to the application. Sign-up asks for a display name, email,
password, and password confirmation. The password policy is 12 to 128
characters with no composition rules, and the password must not equal the email
address or the display name.

Passwords use `hashlib.scrypt` from the standard library with `n=16384`, `r=8`,
`p=1`, a random 16-byte salt, and a 64-byte digest. Each hash carries its own
parameters in `scrypt$n$r$p$salt$hash` form, so a future parameter change needs
no schema change. Verification uses `hmac.compare_digest`. An unknown email
still runs one hash against a dummy value, so a failed lookup takes the same
time as a wrong password.

### Seeded administrator

Migration `0003` adds `username` and `is_admin` to `app_users`. At start-up,
`app/main.py` calls `seed_admin_account()`, which runs once per process through
`st.cache_resource`. The seed reads `ADMIN_USERNAME`, `ADMIN_EMAIL`,
`ADMIN_DISPLAY_NAME`, and the password that `configured_admin_password()`
resolves.

- When no account matches the username or email, the seed creates one with
  `is_admin=true`.
- When the account exists, the seed sets `is_admin=true`, reactivates it, and
  updates the hash when the configured password changed.
- The seed catches database errors and logs them. The app still opens.
- The seed skips the 12-character self-service policy because the operator owns
  this credential. Use a long value anyway.

Sign-in accepts a username or an email. One password does two jobs for the
seeded account: the Account page sign-in and the Admin page gate. A viewer
account still uses the separate Admin page password. Change `ADMIN_PASSWORD` or
the `admin_password` secret and restart the process to rotate the password. The
username is a sign-in name only. A change to `ADMIN_USERNAME` creates a new
account and leaves the old row in place.

The signed-in session lives in `st.session_state` and ends after
`SESSION_MAX_HOURS`, or when the browser opens a new Streamlit session. Sign-out
clears the account, the admin gate, and any pending lock state. The app stores
no session cookie.

The visitor strip counts distinct `visitor_key` values. The key is
`HMAC-SHA256(salt, "<ip>|<user-agent>")`, truncated to 32 hexadecimal
characters. The application never stores the raw IP address or the raw user
agent. On localhost, where Streamlit reports no IP address, the session id
replaces the IP so local runs still produce counts. One session writes at most
one row per page per 30 minutes, and the throttle state lives in the Streamlit
session.

Set `VISITOR_HASH_SALT` to a long random string before you deploy. Generate one
with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

A blank salt disables recording. The banner then shows the stored counts and a
caption that explains the state. The salt is a secret because the digest is
pseudonymous, not anonymous. A person who knows the salt and guesses an IP
address and user agent can confirm a match.

Account sign-up is open by default and no verification email is sent. The gate
controls casual access and demonstrates authentication. It does not protect
sensitive data. Set `ALLOW_SIGNUP=false` after you create the accounts you need.

## Data dictionary

### Source columns

| Column | Description |
| --- | --- |
| `customer_id` | Customer identifier; repeats across provider relationships |
| `telecom_partner` | Telecom provider |
| `gender` | `M` or `F` |
| `age` | Age, 15–100 |
| `state` | State name |
| `city` | City name |
| `pincode` | Six-digit pincode; synthetic and not a reliable geographic key |
| `date_of_registration` | Registration date (`DD-MM-YYYY` in the source) |
| `num_dependents` | Dependents, 0–20 |
| `estimated_salary` | Estimated salary, greater than zero |
| `calls_made` | Calls made, non-negative |
| `sms_sent` | SMS sent, non-negative |
| `data_used` | Data used, non-negative |
| `churn` | Provider-specific churn flag, 0 or 1 |

### Derived columns

| Column | Meaning |
| --- | --- |
| `record_id` | Surrogate primary key |
| `dataset_id` | Owning uploaded snapshot |
| `source_row_number` | 1-based source data row, excluding the header |
| `relationship_seq` | 1-based order by `(registration_date, source_row_number)` within customer |
| `relationship_count` | Number of provider relationships for the customer |
| `is_latest_relationship` | True for exactly one relationship per customer |
| `tenure_days` | Historical: next registration minus current. Latest: snapshot date minus current |
| `created_at` | Insertion timestamp (UTC) |

## Grain and churn semantics

This section is the most important part of the data contract.

- **Relationships vs customers**: 10,000 rows are 10,000 customer-provider
  relationships, not 10,000 customers. There are 8,860 unique customers.
- **Multi-provider customers**: 1,020 customers have multiple relationships
  (900 with two, 120 with three). This is intentional. Never deduplicate them,
  reject them, or warn that they are duplicates.
- **Re-entry pairs**: 33 customer-provider pairs recur at a later date
  (for example A → B → A). They are legitimate return relationships.
- **Historical relationships**: 1,140 rows are non-latest relationships. All
  1,140 are churned by dataset construction. Do not treat that as independent
  evidence of churn behaviour.
- **Relationship churn**: 1,987 / 10,000 = **19.87%**. This covers all history.
- **Current customer churn**: 847 / 8,860 latest relationships = **9.56%**.
- **Never mix the two rates.** 19.87% is not the current customer churn rate.
- **Tenure**: the dataset has no explicit churn date. For a historical
  relationship, the next registration date is the proxy switch date. For the
  latest relationship, the snapshot date (`2023-05-04`) is the end of
  observation.
- **Pincode**: pincode changes across all 1,020 multi-provider groups and is
  synthetic noise. It is not a reliable geographic key.
- **ML implication**: Phase 3 models current/latest relationships only.
  Including historical rows would leak the construction rule that every
  non-latest relationship is churned.

## Database schema

### `datasets`

One row per uploaded CSV snapshot:

- UUID primary key, display name, original filename
- unique SHA-256 file hash
- relationship `row_count`, snapshot `as_of_date`
- JSONB `validation_report`
- `is_active` flag with a partial unique index enforcing at most one active
  dataset
- upload timestamp and optional notes

### `customer_relationships`

One row per customer-provider relationship:

- `record_id BIGSERIAL` primary key
- `dataset_id` foreign key with `ON DELETE CASCADE`
- all 14 source fields
- `source_row_number`, `relationship_seq`, `relationship_count`,
  `is_latest_relationship`, `tenure_days`
- check constraints for ranges, six-digit pincodes, sequence consistency, and
  tenure
- unique `(dataset_id, source_row_number)`; **no unique constraint on
  `customer_id`**
- indexes for dataset, churn, latest-churn, customer/date, partner, and state
  access paths

Constraint names follow a stable naming convention (`pk_`, `fk_`, `uq_`, `ck_`,
`ix_`). The initial Alembic revision is reversible.

## Validation and ingestion

`validate_csv` reads UTF-8 with BOM tolerance, keeps every source value as text
while parsing, and normalises:

- trimmed strings
- gender to `M`/`F`
- dates parsed as `DD-MM-YYYY`, then `YYYY-MM-DD`
- six-digit pincodes, including zero-padding and Excel `.0` artifacts
- churn to a boolean
- relationship sequence, latest flag, and tenure

Hard errors (nothing is written):

- empty file or no data rows
- missing or duplicate required columns
- missing values, unparseable dates, non-numeric numbers
- invalid churn values, invalid gender, bad pincodes
- out-of-range age/dependents/salary and negative metrics
- an `as_of_date` earlier than the latest registration date

Warnings (allowed):

- extra columns are dropped
- pincode normalisation
- gender inconsistency for the same customer
- duplicate registration dates that need source-row tie-breaking

Multi-provider records, re-entry pairs, and churned historical relationships are
never warnings.

`ingest_dataframe` recomputes all derived fields, checks the SHA-256 duplicate
hash, optionally replaces an existing dataset, deactivates other datasets when
activating, and inserts the snapshot and all relationships in one transaction.
The app calls this service; no SQL lives in `app/`.

## Testing

| Command | Purpose |
| --- | --- |
| `uv run ruff check .` | Lint all Python |
| `uv run ruff format --check .` | Formatting check |
| `uv run mypy src` | Strict typing for `src` |
| `uv run pytest -m "not db" -q` | Unit tests, no database required |
| `uv run pytest -m db -q` | DB tests against `TEST_DATABASE_URL` |

The unit suite covers the baseline metrics, relationship derivation, error and
warning rules, URL normalisation, password masking, upload limits, admin
password verification, scrypt hashing, account policy, visitor-key hashing,
the page-view throttle, username normalisation, current-frame analytics, and the
serving contract. The analytics tests check Wilson intervals, segment coverage,
ordered bands, usage quartiles, cohorts, filters, and rejection of historical or
duplicate current rows. The serving tests check the fixed constants, model fit
on the full current frame, score coverage, threshold flags, review-priority
bands, summary counts, and input immutability. DB tests create the schema in the
test database, ingest the baseline, verify dual-grain metrics, duplicate
rejection, replacement, and activation, then drop their tables. The account DB
tests also create and authenticate accounts, reject duplicate emails, set
`last_login_at`, seed the administrator account, update its password, and check
visitor distinct counts. They are excluded from CI.

The Phase 2 notebook verifies the snapshot before analysis. It asserts the file
SHA-256, file size, 10,000 rows, 8,860 customers, 1,987 relationship churn
events, 1,140 historical churned rows, and 847 current churn events. A full
`nbconvert` execution must produce 30 code cells with sequential execution
counts, no error output, and no stderr output.

The Phase 3 notebook retrains both candidates and the final model. A full
`nbconvert` execution must produce 28 code cells with sequential execution
counts, 10 figures, no error output, and no stderr output.

## Roadmap

| Phase | Scope | Output |
| --- | --- | --- |
| 1 | Foundation, schema, validation, ingestion, basic Streamlit page | Completed |
| 2 | Exploratory data analysis notebook | Completed — `Python/analysis.ipynb` |
| 3 | Current-relationship churn model and evaluation | Completed — `src/cronus/modeling/` and `Python/modeling.ipynb` |
| 4 | Full analytics UI and admin-gated upload workflow | Completed — `app/` multipage Streamlit application |
| 5 | Deployment and public Streamlit URL | Completed — https://churn-lab.streamlit.app/ (account sign-in required) |
| 6 | Power BI dashboard in Import mode | In progress — scoring queries, DAX, and build guide are ready; `project_dashboard.pbix` is pending a Windows build |
| 7 | Final documentation and submission README | `01_Project_Documentation.pdf`, `GitHub/README.md` |

Phase 4 addendum (2026-11-18): account sign-up and sign-in plus site-wide
visitor analytics. Migration `0002` adds the two tables. Migration `0003` adds
the seeded administrator username and role flag. The deployment needs
`ADMIN_PASSWORD`, `VISITOR_HASH_SALT`, and a completed `alembic upgrade head`
before the new pages and the fixed admin login work.

## Instructor submission mapping

| Submission item | Location | Phase |
| --- | --- | --- |
| `01_Project_Documentation.pdf` | Repository root | 7 |
| `02_Dataset/project_dataset.csv` | `Dataset/project_dataset.csv` | 1 |
| `03_Python/analysis.ipynb` | `Python/analysis.ipynb` | 2 |
| `05_PowerBI/project_dashboard.pbix` | `PowerBI/project_dashboard.pbix` | 6 |
| `06_GitHub/README.md` | `GitHub/README.md` (root `README.md` is canonical) | 7 |
| `07_Streamlit link` | This README and `GitHub/README.md` | 5 |

Phase 3 adds `Python/modeling.ipynb` as supporting evidence. It does not change
this submission mapping.

If the instructor requires the numbered folder names, the final submission can
map the unnumbered project folders to those item names without duplicating the
source tree.

## Power BI Dashboard (Phase 6)

The dashboard is built in **Import mode** against the Neon Postgres database.
Scoring is computed in **Power Query (M)**. The queries replicate the Phase 3
preprocessing (OneHotEncoder with `min_frequency=50`, StandardScaler) and apply
the fixed logistic regression coefficients. The PBIX does not read a scored CSV
and does not call Python at view time.

### Files
| File | Purpose |
|------|---------|
| `PowerBI/PowerQuery_M_Scoring.txt` | Five queries: Config, ActiveDataset, CurrentRelationships, DateTable, ScoredRelationships |
| `PowerBI/DAX_Measures.txt` | Calculated columns, measures, threshold selector, fixed evidence tables |
| `PowerBI/PBIX_Build_Guide.md` | Step-by-step build guide for the five report pages |
| `PowerBI/powerbi_model_export.json` | Model parameters (intercept, 43 coefficients, scaler, categories) |
| `PowerBI/verify_scores.py` | Build-time parity check against the Streamlit scores |
| `PowerBI/project_dashboard.pbix` | Output. The build is pending on Windows Power BI Desktop. |

### Data Model
- `Config` — one record of fixed parameters. Load is disabled.
- `ActiveDataset` — single active snapshot with the dual-grain summary.
- `CurrentRelationships` — latest relationships only. Intermediate query, load
  is disabled.
- `ScoredRelationships` — computed in M: adds `churn_probability`, both fixed
  flags, both priorities, both thresholds, and `score_rank`.
- `DateTable` — disconnected calendar.

The model has no relationships. `ActiveDataset` is a one-row constant table.
`ScoredRelationships` is the only fact table. The evidence tables on the Model
performance page are fixed and disconnected.

### Report Pages
1. **Overview** — dual-grain churn KPIs, snapshot context, dual-grain warning
2. **Providers and segments** — provider, gender, age band, and state tables with Wilson 95% CI
3. **Usage and tenure** — tenure bands, usage quartiles, registration cohorts
4. **Model performance** — fixed Phase 3 holdout metrics, confusion matrix, permutation importance, subgroup recall, calibration, temporal check
5. **Churn predictions** — threshold selector (0.1840 / 0.0981), ranked queue, both fixed flags

### Build Steps
1. Open Power BI Desktop → Transform Data → New Source → Blank Query.
2. Paste each of the five query blocks from `PowerQuery_M_Scoring.txt` into the
   Advanced Editor. Name each query as the block says.
3. Disable load for `Config` and `CurrentRelationships`.
4. Set `PG_Server` and `PG_Database` in `Config`. Enter the Neon credentials in
   the Power BI prompt. Do not put the password in a file.
5. Add the DAX objects from `DAX_Measures.txt`.
6. Build the five report pages per `PBIX_Build_Guide.md`.
7. Publish to Power BI Service and configure daily scheduled refresh.

### Verification
```bash
# After the PBIX refresh, export ScoredRelationships to CSV, then:
uv run python PowerBI/verify_scores.py path/to/exported_scores.csv
```

Require `max_probability_diff <= 1e-6` and both flag columns true. A correct
build reports about `3.9e-16`. The report must show 1,180 flagged at 0.1840
(13.32%) and 3,286 at 0.0981 (37.09%).

The repository does not commit a prediction table. `PowerBI/scored_latest.csv`
is gitignored. The project rule bans prediction tables.

## Security and credentials

- `.env` and `.streamlit/secrets.toml` are gitignored.
- Full connection URLs are never logged or displayed; passwords are masked.
- Database access is parameterised through SQLAlchemy.
- Account passwords use scrypt with a random 16-byte salt and
  `hmac.compare_digest`. No plaintext or reversible value is stored.
- Every dashboard page requires an active account session.
- Upload, replacement, and activation require the administrator account or the
  admin password.
- The admin password is compared with `hmac.compare_digest` and never displayed.
  The seeded hash is stored in `app_users`, never in the repository.
- Visitor keys are truncated HMAC-SHA256 digests. The application stores no raw
  IP address, raw user agent, or cookie value.
- `VISITOR_HASH_SALT` is a secret. Keep it out of the repository and rotate it
  only when you accept that the unique-visitor count restarts.
- `TEST_DATABASE_URL` must point to a separate database or branch. DB tests
  refuse to run against the app database.

## Known limitations

- The upload panel remains local to the Streamlit process. The Admin page
  requires a configured admin password or the seeded administrator account, and
  it fails closed when no password is set.
- The admin seed runs once per Streamlit process. A password change needs a
  restart, and a database outage at start-up skips the seed until the next run.
- A change to `ADMIN_USERNAME` creates a new account. The old row stays.
- Account sign-up is open and no verification email is sent. The gate
  demonstrates authentication and does not protect sensitive data.
- A full browser reload creates a new Streamlit session, so the viewer must sign
  in again. The app stores no persistent session cookie.
- Unique-visitor counts are approximate. NAT or a shared address can merge two
  people into one visitor, and a mobile IP change can split one person into two.
- The visitor strip shows stored counts when `VISITOR_HASH_SALT` is blank, and
  it records nothing in that state.
- The dataset has no explicit churn date. Tenure uses the documented
  next-registration/snapshot convention.
- The root source CSV is gitignored. The committed dataset is
  `Dataset/project_dataset.csv`.
- The Phase 2 and Phase 3 notebooks read the committed CSV, not Neon. This keeps
  the analysis reproducible without credentials.
- Phase 2 is descriptive and makes no causal claims. Phase 3 owns the model.
- Several states and segments have small samples, and the notebooks show the
  uncertainty with confidence intervals where possible.
- Phase 3 uses observational data and makes no causal claim. The model is not
  production-ready.
- The default 0.5 threshold is unusable. The selected max-F1 threshold is
  0.1840, and every score travels with it.
- Subgroup recall is uneven. Provider recall ranges from 0.125 to 0.577, and the
  highest calls quartile has near-zero recall.
- The temporal holdout has higher churn prevalence and a worse Brier score. The
  app keeps the fixed Phase 3 threshold.
- No model artifact is committed. The app refits and caches the pipeline.
- Power BI applies the fixed Phase 3 coefficients to the active frame. Streamlit
  refits on the active frame, so the two paths match only for the baseline
  snapshot that produced `powerbi_model_export.json`. Regenerate the export
  before you compare scores on a different dataset.
- `PowerBI/project_dashboard.pbix` is not built yet. Power BI Desktop runs on
  Windows, and this repository was prepared on Linux.
