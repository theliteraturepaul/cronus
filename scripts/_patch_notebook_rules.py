"""One-off patch: remove matplotlib rule marks from notebook source cells."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def split_source(text: str) -> list[str]:
    if not text:
        return []
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])


def patch(path: Path, replacements: list[tuple[str, str]]) -> int:
    nb = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        new = src
        for old, repl in replacements:
            if old in new:
                new = new.replace(old, repl)
                changed += 1
        if new != src:
            cell["source"] = split_source(new)
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


ANALYSIS = [
    (
        "    median = values.median()\n"
        "    ax.axvline(\n"
        '        median,\n'
        '        color=PALETTE["churned"],\n'
        '        linestyle="--",\n'
        "        linewidth=1.5,\n"
        '        label=f"Median {median:,.0f}",\n'
        "    )\n"
        "    ax.set_title(numeric_labels[column])\n"
        '    ax.set_ylabel("Relationships")\n'
        "    ax.yaxis.set_major_formatter(count_formatter)\n"
        "    ax.legend(frameon=False)\n",
        "    median = values.median()\n"
        '    ax.set_title(f"{numeric_labels[column]} (median {median:,.0f})")\n'
        '    ax.set_ylabel("Relationships")\n'
        "    ax.yaxis.set_major_formatter(count_formatter)\n",
    ),
    (
        'axes[1].axvline(1.0, color=PALETTE["ink"], linestyle="--", linewidth=1)\n',
        "",
    ),
    (
        "ax.axvline(\n"
        "    report.current_churn_rate,\n"
        '    color=PALETTE["ink"],\n'
        '    linestyle="--",\n'
        "    linewidth=1,\n"
        '    label=f"Overall current churn {report.current_churn_rate:.2f}%",\n'
        ")\n",
        "",
    ),
    (
        'ax.legend(loc="lower right", frameon=False)\n',
        "",
    ),
]

MODELING = [
    (
        '    ax.axhline(model.cv.pr_auc_mean, color=color, linestyle="--", linewidth=1, alpha=0.7)\n',
        "",
    ),
    (
        'ax.axvline(max_f1_threshold, color=PALETTE["ink"], linestyle="--", linewidth=1)\n'
        'ax.text(max_f1_threshold, 1.015, " Max-F1", va="bottom", fontsize=8)\n'
        'ax.axvline(recall70_threshold, color=PALETTE["muted"], linestyle=":", linewidth=1.2)\n'
        'ax.text(recall70_threshold, 0.92, " 70% recall", va="bottom", fontsize=8)\n',
        'ax.text(max_f1_threshold, 1.015, " Max-F1", va="bottom", fontsize=8)\n'
        'ax.text(recall70_threshold, 0.92, " 70% recall", va="bottom", fontsize=8)\n',
    ),
    (
        "ax.axhline(\n"
        "    test_target.mean(),\n"
        '    color=PALETTE["muted"],\n'
        '    linestyle="--",\n'
        "    linewidth=1,\n"
        '    label=f"Prevalence ({format_share(test_target.mean())})",\n'
        ")\n",
        "",
    ),
    (
        'ax.axvline(0, color=PALETTE["ink"], linewidth=0.8)\n',
        "",
    ),
    (
        'ax.axhline(test_target.mean(), color=PALETTE["logistic"], linestyle="--", linewidth=1, alpha=0.5)\n'
        "ax.axhline(\n"
        '    time_test_target.mean(), color=PALETTE["churned"], linestyle="--", linewidth=1, alpha=0.5\n'
        ")\n",
        "",
    ),
]


def main() -> None:
    analysis_count = patch(ROOT / "Python" / "analysis.ipynb", ANALYSIS)
    modeling_count = patch(ROOT / "Python" / "modeling.ipynb", MODELING)
    print(f"analysis replacements applied: {analysis_count}")
    print(f"modeling replacements applied: {modeling_count}")


if __name__ == "__main__":
    main()
