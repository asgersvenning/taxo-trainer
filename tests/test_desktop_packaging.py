"""Unit tests for desktop application packaging, path helpers, and OS user data resolution."""

import sys
from pathlib import Path

from taxo_trainer.db import (
    APP_DB_PATH,
    GBIF_CACHE_DB_PATH,
    USER_DB_PATH,
    ensure_data_dir,
    get_user_data_dir,
)
from taxo_trainer.engine.guides import load_all_guides
from taxo_trainer.resources import get_resource_path, is_frozen


def test_resource_path_interpreted_mode():
    """Verify get_resource_path in interpreted Python development mode."""
    resource_path = get_resource_path("assets")
    assert resource_path.exists()
    assert resource_path.is_dir()
    assert (resource_path / "guides").exists()


def test_resource_path_frozen_mode(monkeypatch, tmp_path):
    """Verify get_resource_path in simulated PyInstaller frozen bundle mode."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert is_frozen() is True

    test_file = tmp_path / "test_asset.txt"
    test_file.write_text("frozen_asset_content")

    resolved_path = get_resource_path("test_asset.txt")
    assert resolved_path == test_file
    assert resolved_path.read_text() == "frozen_asset_content"


def test_user_data_dir_resolution():
    """Verify OS-compliant user application data directory resolution."""
    data_dir = get_user_data_dir()
    assert isinstance(data_dir, Path)
    assert data_dir.name == "taxo-trainer"

    assert APP_DB_PATH == data_dir / "app_data.db"
    assert USER_DB_PATH == data_dir / "user_data.db"
    assert GBIF_CACHE_DB_PATH == data_dir / "gbif_cache.db"


def test_ensure_data_dir_seeding(tmp_path, monkeypatch):
    """Verify ensure_data_dir creates directories and seeds missing initial database files."""
    test_data_dir = tmp_path / "user_app_data"
    monkeypatch.setattr("taxo_trainer.db.DATA_DIR", test_data_dir)

    assert not test_data_dir.exists()
    created_dir = ensure_data_dir()

    assert created_dir.exists()
    assert created_dir.is_dir()
    assert (created_dir / "app_data.db").exists() or (created_dir / "user_data.db").exists()


def test_guides_loading_with_resource_path():
    """Verify load_all_guides loads guide structures cleanly using resource path helper."""
    guides = load_all_guides()
    assert isinstance(guides, list)
    assert len(guides) > 0

    guide_ids = [g.id for g in guides]
    assert "initial_dataset_setup" in guide_ids
