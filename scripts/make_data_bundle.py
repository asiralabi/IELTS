"""Pack the runtime slice of `backend/data` for another host.

`backend/data` is ~12GB, and almost none of it is needed to SERVE the app: the
audio corpus and the TTS cache are training material and regenerable output.
This copies only what the running app reads, and reports what it skipped.

    python scripts/make_data_bundle.py [--out dist/ielts-data]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "data"

# Read by app/ at runtime. Sizes as of 2026-09-03.
INCLUDE = {
    "ielts.db": "student accounts, attempts, band history, the Cambridge tests (~17MB)",
    "qdrant": "the Cambridge knowledge base every generation is grounded on (~67MB)",
    "assets": "figure images the backend serves from /assets (~139MB)",
    "figure_knowledge": "figure conventions read while drawing (~1.2MB)",
}

# Deliberately absent, and why — so the omission reads as a decision.
SKIP = {
    "audio_corpus": "5.3GB of training/eval audio; nothing in app/ opens it",
    "tts_cache": "5.6GB the app regenerates on demand from edge-tts",
    "ocr_cache": "ingestion-time only; needed to rebuild the KB, not to serve it",
    "datasets": "fine-tuning SFT data; already in git, not read while serving",
    "cambridge_tests": "parser output; the tests live in ielts.db by the time it serves",
    "uploads": "student uploads, created empty at startup",
    "_e2e": "test fixtures",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "dist" / "ielts-data"))
    parser.add_argument("--archive", action="store_true",
                        help="also write a .tar.gz next to the directory")
    args = parser.parse_args()

    if not DATA.exists():
        print(f"! {DATA} not found.")
        return 1

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    total = 0
    for name, why in INCLUDE.items():
        src = DATA / name
        if not src.exists():
            print(f"  MISSING  {name:<18} {why}")
            continue
        dest = out / name
        if dest.exists():
            shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest)
            size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        else:
            shutil.copy2(src, dest)
            size = dest.stat().st_size
        total += size
        print(f"  copied   {name:<18} {size / 1e6:7.1f} MB  {why}")

    print("\n  skipped:")
    for name, why in SKIP.items():
        if (DATA / name).exists():
            print(f"    {name:<18} {why}")

    print(f"\nbundle: {out}  ({total / 1e6:.0f} MB)")
    if args.archive:
        archive = shutil.make_archive(str(out), "gztar", root_dir=out)
        print(f"archive: {archive}  ({Path(archive).stat().st_size / 1e6:.0f} MB)")
    print("\nOn the target host: unpack it and mount it at /app/data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
