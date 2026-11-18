# Cronus Agent Instructions

Cronus is a telecom churn project for an instructor submission. The submission map is in `README.md`.

## Current State

Last updated: 2026-11-18.

### Goal and acceptance criteria

Goal: complete Phases 1 to 7 and submit each mapped file.

Phase status:

- Phase 1: done.
- Phase 2: done locally.
- Phase 3: done locally.
- Phase 4: done, including accounts and visitor analytics.
- Phase 5: documents done. The deployment is not verified.
- Phase 6: in progress. All assets are ready. The PBIX is not built.
- Phase 7: not started.

Phase 6 acceptance criteria:

1. `PowerBI/project_dashboard.pbix` opens in Power BI Desktop in Import mode.
2. The report has five pages: Overview, Providers and segments, Usage and tenure, Model performance, and Churn predictions.
3. Every score display and every export shows its threshold.
4. Relationship churn (19.87%) and current customer churn (9.56%) stay separate on every page.
5. The Model performance page shows the fixed Phase 3 numbers.
6. The Predictions page matches the Streamlit queue at threshold 0.1840 and at threshold 0.0981.
7. The report makes no causal, production-readiness, or fairness claim.

Phase 7 acceptance criteria:

1. `01_Project_Documentation.pdf` is at the repository root.
2. `GitHub/README.md` matches the root `README.md`.
3. Each item in the submission map points to a real file.

### Done

- Phase 1 data platform, schema, validation, ingestion, and upload page. Commit `193ddc0`.
- Phase 2 exploratory notebook at `Python/analysis.ipynb`.
- Phase 3 model package under `src/cronus/modeling/` and evidence notebook at `Python/modeling.ipynb`.
- Phase 4 six-page Streamlit app under `app/`, shared helpers in `app/shared.py`, admin gate in `app/views/admin.py`.
- Phase 4 service layer: `config.admin_password`, `auth.verify_admin_password`, `analytics.py`, `repository.get_current_relationships`, `modeling/serving.py`.
- Phase 4 tests: `tests/test_auth.py`, `tests/test_analytics.py`, `tests/test_serving.py`, and the extended `tests/test_config.py`.
- Phase 4 local smoke test: six pages load, admin sign-in works, threshold switch works.
- Phase 4 addendum (2026-11-18): local accounts and visitor analytics. Migration `0002_accounts_and_visitors.py` applied to Neon. New `app_users` and `visitor_events` tables.
- Account service: `src/cronus/accounts.py` with scrypt hashing in `src/cronus/auth.py`, 12 to 128 character policy, duplicate-email rejection, and a dummy hash for unknown emails.
- Account page: `app/views/account.py`. Sign-up, sign-in, sign-out, five-attempt lock for 60 seconds, and `ALLOW_SIGNUP`.
- Gate: every dashboard page requires an account. `app/main.py` registers only the Account page when signed out. Admin keeps its password gate.
- Visitor analytics: `src/cronus/visitors.py` and the strip in `app/shared.py`. HMAC-SHA256 visitor key, no raw IP or user agent, 30-minute throttle per session and page.
- Addendum tests: `tests/test_accounts.py`, `tests/test_visitors.py`, `tests/test_accounts_db.py`, and the extended `tests/test_auth.py` and `tests/test_config.py`. Suite: 147 passed, 9 deselected.
- Addendum smoke tests: AppTest covers sign-up, sign-out, wrong password, sign-in, and the visitor strip. The strip writes one event on the first run and zero on the next run in the same session.
- `VISITOR_HASH_SALT` added to the local `.env` and `.env.example`. The value is not committed.
- Phase 5 root `README.md` with the public URL and `GitHub/README.md`. Commit `d2ba6ff` is on `origin/main`.
- Phase 6 model export: `PowerBI/powerbi_model_export.json`. The file moved from the repository root. It matches a fresh fit exactly.
- Phase 6 Power Query script: `PowerBI/PowerQuery_M_Scoring.txt`. It now contains five queries: Config, ActiveDataset, CurrentRelationships, DateTable, and ScoredRelationships.
- Phase 6 DAX objects: `PowerBI/DAX_Measures.txt`. It has the calculated columns, measures, threshold selector, and fixed evidence tables.
- Phase 6 build guide: `PowerBI/PBIX_Build_Guide.md`. It covers the five pages, the validation checklist, and the parity check.
- Phase 6 parity test: `tests/test_powerbi_export.py`. It checks the export against a fresh fit and checks the M constants against the export.
- Phase 6 verification helper: `PowerBI/verify_scores.py`. It compares a PBIX table export with the Streamlit scoring path. A simulated export gives `max_probability_diff = 3.9e-16`, 1,180 default flags, and 3,286 recall-70 flags.
- Option B removed: the scored CSV workflow, the CSV generator, and the local prediction table. `PowerBI/scored_latest.csv` is gitignored.
- Stale root `model_coefficients.json` deleted. It mapped 10 raw feature names to 43 coefficients.

### In progress

- Phase 6 PBIX. `PowerBI/project_dashboard.pbix` does not exist. Power BI Desktop does not run in this WSL environment.
- The accounts and visitor addendum is not committed. `git status` lists the new and changed paths.
- The deployment is not verified. `origin/main` is `bbf506f`, so the live app does not have the addendum files. The Neon schema is at `0002`, but the deployed app needs `VISITOR_HASH_SALT` in Streamlit secrets.

### Next steps

1. Build `PowerBI/project_dashboard.pbix` on Windows Power BI Desktop. Follow `PowerBI/PBIX_Build_Guide.md`.

   - Paste the five query blocks from `PowerQuery_M_Scoring.txt`.
   - Disable load on `Config` and `CurrentRelationships`.
   - Set `PG_Server` and `PG_Database` in `Config`. Enter the Neon credentials in the Power BI prompt.
   - Add the objects from `DAX_Measures.txt`.
   - Build the five pages.
   - Confirm `[Flagged Count Default] = 1,180` and `[Flagged Count Recall70] = 3,286`.

2. Export `ScoredRelationships` to CSV. Then run the parity check:

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   uv run python PowerBI/verify_scores.py path/to/exported_scores.csv
   ```

   Require `max_probability_diff <= 1e-6`. Require both flag columns to match.

3. Commit and push in small commits. Do not add a prediction table.

   ```bash
   cd "/mnt/e/VSCode Workspace/PROJECTS/cronus"
   export PATH="$HOME/.local/bin:$PATH"
   uv lock --check
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src
   uv run pytest -m "not db" -q
   git add .env.example AGENTS.md README.md GitHub/README.md app src tests alembic
   git commit -m "feat: add accounts and visitor analytics"
   git push origin main
   ```

   Then set `VISITOR_HASH_SALT` in the Streamlit Cloud secrets and redeploy. The
   migration already ran against Neon.

4. Update README row 6 from "In progress" to "Completed - `PowerBI/project_dashboard.pbix`" after the file exists. Copy the root README to `GitHub/README.md`.

5. Start Phase 7: final PDF and submission review.

### Decisions and why

- Import mode. The current frame has 8,860 rows and refresh is daily. DirectQuery adds no value.
- Option A is active: score in Power Query. The user selected it. The PBIX stays independent of Python at view time.
- No Option B. The project rule bans prediction tables. The refresh workflow and the CSV generator are removed. `PowerBI/scored_latest.csv` is gitignored.
- Fixed coefficient export. Streamlit refits on the active current frame. Power BI applies the fixed Phase 3 coefficients. The two paths match on the baseline snapshot. A different active dataset needs a new export before any parity check.
- No relationships in the Power BI model. `ActiveDataset` is a one-row constant table. `ScoredRelationships` is the only fact table. `DateTable` and the evidence tables are disconnected.
- Both thresholds are stored as columns. Every row carries its flag and its threshold. The Predictions page slicer uses a disconnected `ThresholdSelector` table and a dynamic filtered measure.
- No model artifact in the application. Streamlit refits on the active current frame and caches the result. The PBIX uses the one-time coefficient export.
- Dual grain. The 19.87% rate counts every relationship churn event in the history. The 9.56% rate counts current customers only. Never present one rate as the other.
- Current-frame contract. Use latest rows only. Never train on historical rows. Never deduplicate current rows.
- Admin gate fails closed. The gate allows 5 attempts and then locks for 60 seconds. The password is never displayed.
- Accounts stay local. No OAuth provider and no email service. Passwords use standard-library scrypt, so the addendum adds no runtime dependency.
- Every dashboard page requires an account. The user selected this scope. The Account page is the only public page, and the visitor strip stays public.
- The admin gate stays separate. Admin actions need the account session and the admin password.
- Visitor identity is a salted HMAC of the IP address and user agent. The app stores no raw IP, raw user agent, or cookie. Counts are approximate because NAT can merge visitors and mobile IP changes can split them.
- The visitor write is throttled in session state to one row per page per 30 minutes. This prevents a row on every Streamlit rerun.
- No schema change to the churn tables. Migration `0002` adds only `app_users` and `visitor_events`.
- No retune, no `class_weight` change, and no threshold reselection.
- No new runtime dependency. `scikit-learn` entered in Phase 3.
- Phase 5 and Phase 6 prompts keep full length. Do not compress them with the `asd-ste100` skill.
- Unnumbered folders stay. The README map handles the submission names.

### Fixed numbers

Use these values in the report and in tests.

- 10,000 relationships, 8,860 current relationships.
- 1,987 relationship churn events (19.87%) and 847 current churn events (9.56%).
- 1,020 multi-provider customers, 33 re-entry pairs, 4 partners.
- Holdout: PR-AUC 0.2312, ROC-AUC 0.7295, Brier 0.0806.
- Confusion at 0.1840: 1,423 TN, 180 FP, 112 FN, 57 TP.
- Cross-validation: PR-AUC 0.2662 ± 0.0493, ROC-AUC 0.7497, Brier 0.0794.
- Queue at 0.1840: 1,180 flagged (13.32%). Queue at 0.0981: 3,286 flagged (37.09%).
- Temporal check: threshold 0.1410, PR-AUC 0.2776, ROC-AUC 0.7450, Brier 0.0941, prevalence 11.55%, precision 0.2265, recall 0.6212.
- Provider recall at 0.1840: BSNL 0.577, Airtel 0.375, Vodafone 0.178, Reliance Jio 0.125.
- Highest calls quartile recall: 0.000.

### Files touched

- Configuration and services: `src/cronus/config.py`, `src/cronus/auth.py`, `src/cronus/accounts.py`, `src/cronus/visitors.py`, `src/cronus/analytics.py`, `src/cronus/repository.py`, `src/cronus/modeling/`.
- Data contracts and schema: `src/cronus/models.py`, `src/cronus/schemas.py`, `alembic/versions/0002_accounts_and_visitors.py`.
- Application: `app/main.py`, `app/shared.py`, `app/views/`.
- Tests: `tests/test_auth.py`, `tests/test_accounts.py`, `tests/test_visitors.py`, `tests/test_accounts_db.py`, `tests/test_analytics.py`, `tests/test_serving.py`, `tests/test_modeling.py`, `tests/test_config.py`, `tests/test_powerbi_export.py`.
- Notebooks: `Python/analysis.ipynb`, `Python/modeling.ipynb`.
- Power BI: `PowerBI/PowerQuery_M_Scoring.txt`, `PowerBI/DAX_Measures.txt`, `PowerBI/PBIX_Build_Guide.md`, `PowerBI/powerbi_model_export.json`, `PowerBI/verify_scores.py`.
- Documentation: `README.md`, `GitHub/README.md`, `AGENTS.md`, `Dataset/README.md`.
- Build: `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`.

### Known issues

- PBIX absent. Power BI Desktop does not run in this WSL environment. Build the file on Windows.
- Windows-only build. The guide assumes Power BI Desktop and the built-in PostgreSQL connector.
- Parity scope. The PBIX uses fixed coefficients. Streamlit refits. Parity holds for the baseline active dataset. Regenerate `powerbi_model_export.json` before a comparison on a new dataset.
- Repository gap. `origin/main` is `bbf506f`. The accounts and visitor addendum is uncommitted. The live app cannot show the new pages until you push those files and redeploy.
- Deployment. The public Streamlit URL is not verified against the current remote tree. Set `VISITOR_HASH_SALT` in the Streamlit Cloud secrets.
- DB tests. `TEST_DATABASE_URL` is not set. 9 tests are deselected.
- AppTest limitation. `AppTest.switch_page` does not resolve callable `st.Page` objects. Test each page with `AppTest.from_string`. The sign-in gate and account flow work under `AppTest.from_file("app/main.py")`.
- Session limit. `st.session_state` is not persistent. A full browser reload starts a new Streamlit session, so the viewer signs in again. The app stores no session cookie.
- Account scope. Sign-up is open and no verification email is sent. The gate demonstrates authentication and does not protect sensitive data. Set `ALLOW_SIGNUP=false` after you create the needed accounts.
- Visitor accuracy. Counts are approximate. NAT can merge two people into one visitor, and a mobile IP change can split one person into two.
- Visitor salt. A blank `VISITOR_HASH_SALT` stops recording. The banner shows stored counts with a configuration caption.
- Documentation drift. Refresh `GitHub/README.md` after each root README change. README row 6 stays "In progress" until the PBIX exists.
- PDF. `01_Project_Documentation.pdf` does not exist.
- Build tool scope. `PowerBI/verify_scores.py` uses a `__main__` guard. It is a build-time check, not an application entry point. The Streamlit app has no CLI. The file carries `# ruff: noqa: E402` for its `src/` path bootstrap.
- Secrets. `.env` exists and contains `VISITOR_HASH_SALT`. `.streamlit/secrets.toml` does not exist. The admin gate fails closed. Never print or commit `.env`.

### Commands to verify

```bash
cd "/mnt/e/VSCode Workspace/PROJECTS/cronus"
export PATH="$HOME/.local/bin:$PATH"
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not db" -q
uv run alembic upgrade head
uv run streamlit run app/main.py
```

Expected results:

- `ruff` and `mypy` report no issues.
- `pytest` reports 147 passed and 9 deselected.
- `alembic` reports `0002 (head)` and applies no new step.
- Streamlit starts on the Account page. Create an account, and seven pages appear.

Run the DB tests only when a separate test database exists:

```bash
uv run pytest -m db -q
```

Expected: 9 passed. The five account and visitor tests join the four ingestion tests.

Run the Power BI parity test without a database:

```bash
uv run pytest tests/test_powerbi_export.py -q
```

Expected: 3 passed. The test checks the export against a fresh fit, reproduces both flag counts, and checks the M constants against the JSON export.
