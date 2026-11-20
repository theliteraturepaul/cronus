# ChurnLab handoff

This file lets a new session continue the ChurnLab project in Codex without
re-reading the full history.

## Current state

The Streamlit application works. All six requested UI changes are in place:

1. The sidebar has a **Power BI dashboard** page.
2. The sidebar has an **Upload dataset** button. Every signed-in user can stage a file.
3. The **Admin** page is administrator-only. A viewer sees an access message and a pointer to the upload button.
4. The app has a dark theme only. The Appearance control is removed.
5. Values, labels, and tables wrap or scroll inside their containers.
6. Every analysis page uses live Altair charts from the active dataset. No "Phase" string remains in `app/`.

Local verification on 2026-11-20:

- `uv run ruff check .` passes.
- `uv run ruff format --check .` passes.
- `uv run mypy src` passes for 19 source files.
- `uv run pytest -m "not db" -q` reports 159 passed and 13 deselected.
- AppTest renders all eight views without an exception.
- AppTest sign-in with the seeded administrator succeeds.

## Run the app

```bash
cd "/mnt/e/VSCode Workspace/PROJECTS/cronus"
export PATH="$HOME/.local/bin:$PATH"
uv run streamlit run app/main.py
```

Sign in with `admin` and the `ADMIN_PASSWORD` value. The `.env` file holds the
secret. Never print or commit `.env`.

## What changed in this pass

| Area | File | Change |
| --- | --- | --- |
| Theme | `.streamlit/config.toml` | `base = "dark"`, dark palette only |
| Theme | `app/shared.py` | Removed `THEME_OPTIONS`, `_LIGHT_VARS`, and `render_appearance_control` |
| Charts | `app/shared.py` | Added dark Altair helpers for every live chart |
| Layout | `app/shared.py` | Anti-clipping CSS for metrics, buttons, tabs, alerts, and tables |
| Navigation | `app/main.py` | Hidden `upload` page, sidebar upload button, Power BI page |
| Upload | `app/views/upload.py` | Signed-in staging page. Replace and activate stay admin-only |
| Admin | `app/views/admin.py` | Administrator gate, dataset activation, no viewer password prompt |
| Power BI | `app/views/powerbi.py` | Embed, PBIX download, and five native preview tabs |
| Overview | `app/views/overview.py` | Profile summary, dual-grain chart, live segment charts |
| Providers | `app/views/providers.py` | Live rate charts, unused imports removed |
| Usage | `app/views/usage.py` | Live rate and correlation charts |
| Performance | `app/views/performance.py` | Altair importance, recall, calibration, and metric charts |
| Predictions | `app/views/predictions.py` | Altair score histogram and flagged-by-provider chart |
| Config | `src/cronus/config.py` | `Settings.powerbi_report_url` |
| Docs | `README.md`, `GitHub/README.md`, `AGENTS.md` | Updated for the current UI |

`plotly` is not installed. Streamlit 1.67 bundles `altair 6.3.0`. Do not add a
runtime dependency.

## Pending work

1. **PBIX desktop check.** Open `PowerBI/project_dashboard.pbix` on Windows Power BI Desktop. Confirm Import mode, the five pages, and both flag counts. Power BI Desktop does not run in WSL.

   - `[Flagged Count Default] = 1,180`.
   - `[Flagged Count Recall70] = 3,286`.

2. **Parity export check.** Export `ScoredRelationships` to CSV, then run:

   ```bash
   uv run python PowerBI/verify_scores.py path/to/exported_scores.csv
   ```

   Require `max_probability_diff <= 1e-6` and matching flag columns.

3. **Power BI Service embed.** Publish the report and set `POWERBI_REPORT_URL` in `.env` or Streamlit secrets. The Power BI page shows the download and preview path until this value exists.

4. **Deployment.** Set `ADMIN_PASSWORD` and `VISITOR_HASH_SALT` in the Streamlit Cloud secrets. Run `alembic upgrade head` against Neon. The schema is at `0003`.

5. **Final PDF.** `01_Project_Documentation.pdf` does not exist. Build it in the final phase.

6. **Git.** `origin/main` is behind the local work. Run the checks, then push.

## Next steps

```bash
cd "/mnt/e/VSCode Workspace/PROJECTS/cronus"
export PATH="$HOME/.local/bin:$PATH"
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not db" -q
git status
git add -A
git commit -m "feat: add Power BI page, sidebar upload, dark theme, and live charts"
git push origin main
```

## Constraints to keep

- Never mix relationship churn (19.87%) with current customer churn (9.56%).
- Every score display and every export carries its threshold.
- Never train on historical rows. Never deduplicate current rows.
- Do not add a prediction table. Do not commit `PowerBI/scored_latest.csv`.
- Do not add a runtime dependency.
- Keep `cronus` as the package name. ChurnLab is the user-facing name.
- Keep the admin gate closed by default. Only `is_admin` accounts manage datasets.
- Do not display, log, or commit `.env` values.

## Test gotchas

- `AppTest.switch_page` does not resolve callable `st.Page` objects. Test a view with `AppTest.from_string`. Test the gate with `AppTest.from_file("app/main.py")`.
- `Settings.admin_password` is a `SecretStr`. Call `.get_secret_value()` or `shared.configured_admin_password(settings)` before you pass it to a widget.
- `TEST_DATABASE_URL` is not set. The 13 DB tests stay deselected until a separate database exists.
- Static PNGs remain in `app/assets/`. The views no longer show them. Delete them or wire them into a fallback when you confirm the live charts cover every figure.
