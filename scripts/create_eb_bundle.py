#!/usr/bin/env python3
"""Create a flat Elastic Beanstalk source bundle from this repository."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = (
    "Procfile",
    "requirements.txt",
    "Backend/app.py",
    "Backend/requirements.txt",
    "Backend/templates/index.html",
    "Backend/Datasets/color_palate_ds.xlsx",
    "Backend/Datasets/suggestions.xlsx",
)


def should_skip(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if "__pycache__" in relative.parts:
        return True
    if "uploads" in relative.parts:
        return True
    return any(part == ".env" or part.startswith(".env.") for part in relative.parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a ZIP source bundle for Elastic Beanstalk."
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(REPO_ROOT / "stylespectrum-eb.zip"),
        help="Output ZIP path (default: stylespectrum-eb.zip in the repository root).",
    )
    args = parser.parse_args()
    output = Path(args.output).resolve()

    missing = [name for name in REQUIRED_FILES if not (REPO_ROOT / name).is_file()]
    if missing:
        parser.error(f"Required deployment files are missing: {', '.join(missing)}")

    files = [
        path
        for path in (REPO_ROOT / "Backend").rglob("*")
        if path.is_file() and not should_skip(path) and path.resolve() != output
    ]
    files.extend(REPO_ROOT / name for name in ("Procfile", "requirements.txt"))
    output.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(REPO_ROOT))

    print(f"Created Elastic Beanstalk source bundle: {output}")


if __name__ == "__main__":
    main()
