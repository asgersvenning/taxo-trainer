"""Centralized resource path resolution helper for taxo-trainer.

Resolves static assets, guide files, and template data across both interpreted Python
development environments and PyInstaller frozen executable bundles.
"""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Check if the application is executing inside a compiled/frozen PyInstaller bundle.

    Returns:
        bool: True if frozen, False if running under interpreted Python.
    """
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def is_native_gui_available() -> bool:
    """Check if pywebview native GUI window framing dependencies (GTK/Qt/WinForms/Cocoa) are present.

    Returns:
        bool: True if GUI window bindings are installed, False otherwise.
    """
    try:
        import webview  # noqa: F401

        if sys.platform.startswith("linux"):
            for mod in ("gi", "qtpy", "PyQt6", "PyQt5", "PySide6", "PySide2"):
                try:
                    __import__(mod)
                    return True
                except ImportError:
                    continue
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def get_resource_path(relative_path: str | Path = "") -> Path:
    """Resolve absolute path to a resource file or directory.

    In frozen bundle mode (PyInstaller), resources are located inside sys._MEIPASS.
    In interpreted mode, resources are resolved relative to the taxo-trainer repository root.

    Args:
        relative_path: Path string or Path object relative to root resources directory.

    Returns:
        Path: Absolute Path object pointing to target resource.
    """
    rel_path = Path(relative_path)

    if is_frozen():
        base_path = Path(sys._MEIPASS)
    else:
        # Resolves taxo-trainer root directory: src/taxo_trainer/resources.py -> root
        base_path = Path(__file__).resolve().parent.parent.parent

    return (base_path / rel_path).resolve()
