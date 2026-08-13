"""Build script for compiling Taxo-Trainer into a standalone native desktop directory bundle.

Executes PyInstaller with taxo_trainer.spec and validates the generated bundle structure.
Usage:
    python scripts/build_desktop.py
"""

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT_DIR / "taxo_trainer.spec"
DIST_DIR = ROOT_DIR / "dist" / "taxo-trainer"


def build_desktop() -> None:
    """Compile Taxo-Trainer into directory bundle via PyInstaller."""
    print("🚀 Starting Taxo-Trainer Desktop Compilation...")

    if not SPEC_FILE.exists():
        print(f"❌ Error: Spec file not found at {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC_FILE),
    ]

    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR), check=False)

    if result.returncode != 0:
        print("❌ PyInstaller compilation failed!")
        sys.exit(result.returncode)

    if not DIST_DIR.exists():
        print(f"❌ Error: Dist directory {DIST_DIR} was not created!")
        sys.exit(1)

    print(f"✅ Taxo-Trainer desktop directory bundle created successfully at:\n   {DIST_DIR}")


if __name__ == "__main__":
    build_desktop()
