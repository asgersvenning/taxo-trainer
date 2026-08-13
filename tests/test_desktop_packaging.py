"""Unit tests for desktop application packaging, path helpers, and OS user data resolution."""

import sys
from pathlib import Path

from taxo_trainer.db import (
    APP_DB_PATH,
    GBIF_CACHE_DB_PATH,
    USER_DB_PATH,
    ensure_data_dir,
    get_user_data_dir,
    init_databases,
    seed_initial_data,
)
from taxo_trainer.engine.guides import load_all_guides
from taxo_trainer.resources import get_resource_path, is_frozen, is_native_gui_available


def test_is_native_gui_available_check():
    """Verify is_native_gui_available returns boolean without raising exceptions."""
    result = is_native_gui_available()
    assert isinstance(result, bool)


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
    """Verify ensure_data_dir creates directories and seeds missing initial dataset files."""
    test_data_dir = tmp_path / "user_app_data"
    monkeypatch.setattr("taxo_trainer.db.DATA_DIR", test_data_dir)
    monkeypatch.setattr("taxo_trainer.db.APP_DB_PATH", test_data_dir / "app_data.db")
    monkeypatch.setattr("taxo_trainer.db.USER_DB_PATH", test_data_dir / "user_data.db")
    monkeypatch.setattr("taxo_trainer.db.GBIF_CACHE_DB_PATH", test_data_dir / "gbif_cache.db")

    assert not test_data_dir.exists()
    created_dir = ensure_data_dir()

    assert created_dir.exists()
    assert created_dir.is_dir()
    # Datasets directory is tracked in source repository and should always be seeded
    assert (created_dir / "datasets").exists()

    # Verify init_databases initializes database files and schemas
    init_databases()
    assert (created_dir / "app_data.db").exists()
    assert (created_dir / "user_data.db").exists()


def test_seed_initial_data_with_bundle_files(tmp_path, monkeypatch):
    """Verify seed_initial_data copies template database files when present in resource bundle."""
    test_bundle_dir = tmp_path / "bundle_data"
    test_bundle_dir.mkdir()
    (test_bundle_dir / "app_data.db").write_text("mock_db_content")

    test_user_dir = tmp_path / "user_data"
    test_user_dir.mkdir()

    monkeypatch.setattr("taxo_trainer.db.get_resource_path", lambda p: test_bundle_dir)

    seed_initial_data(test_user_dir)
    assert (test_user_dir / "app_data.db").exists()
    assert (test_user_dir / "app_data.db").read_text() == "mock_db_content"


def test_guides_loading_with_resource_path():
    """Verify load_all_guides loads guide structures cleanly using resource path helper."""
    guides = load_all_guides()
    assert isinstance(guides, list)
    assert len(guides) > 0

    guide_ids = [g.id for g in guides]
    assert "initial_dataset_setup" in guide_ids
