"""Extract image/png outputs from executed notebooks into app/assets."""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract(nb_path: Path, dest: Path, prefix: str) -> int:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for cell in nb.get("cells", []):
        for output in cell.get("outputs", []):
            png = (output.get("data") or {}).get("image/png")
            if not png:
                continue
            count += 1
            (dest / f"{prefix}_{count:02d}.png").write_bytes(base64.b64decode(png))
    return count


def main() -> None:
    analysis = extract(
        ROOT / "Python" / "analysis.ipynb",
        ROOT / "app" / "assets" / "analysis",
        "analysis",
    )
    modeling = extract(
        ROOT / "Python" / "modeling.ipynb",
        ROOT / "app" / "assets" / "modeling",
        "modeling",
    )
    print(f"analysis figures: {analysis}")
    print(f"modeling figures: {modeling}")


if __name__ == "__main__":
    main()
