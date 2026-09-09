"""Offline cache, failure, and rate-limit regression tests for GBIF lookups."""

import io
import sqlite3
import urllib.error
from email.utils import formatdate

import pytest

from taxo_trainer.db import init_app_db
from taxo_trainer.ingestion import taxonomy_builder as builder


class Response(io.BytesIO):
    """Minimal successful urllib JSON response."""

    status = 200


@pytest.fixture
def cache(monkeypatch):
    """Provide an isolated cache and deterministic shared cooldown clock."""
    monkeypatch.setattr(builder, "_GBIF_COOLDOWN_UNTIL", 0.0)
    monkeypatch.setattr(builder.time, "monotonic", lambda: 1000.0)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE gbif_api_cache (url TEXT PRIMARY KEY, response_json TEXT, cached_at INTEGER)")
    yield conn
    conn.close()


@pytest.mark.parametrize("cached", ['{"results": []}', '{"matchType": "NONE"}'])
def test_valid_empty_results_are_cached(cache, monkeypatch, cached):
    """No-name/no-match responses are successes and need no repeat request."""
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        return Response(cached.encode())

    monkeypatch.setattr("urllib.request.urlopen", request)
    first = builder.fetch_gbif_raw_api("https://api.gbif.org/example", cache)
    assert builder.fetch_gbif_raw_api("https://api.gbif.org/example", cache) == first
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [b"not json", b"null", b"[]", b"\xff", b'{"results": null}', b'{"results": [1]}'])
def test_bad_responses_are_visible_and_not_cached(cache, monkeypatch, payload):
    """Malformed responses cannot masquerade as absent vernacular names."""
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    with pytest.raises(builder.GBIFRequestError):
        builder.fetch_gbif_raw_api("https://api.gbif.org/example", cache)
    assert cache.execute("SELECT COUNT(*) FROM gbif_api_cache").fetchone()[0] == 0


@pytest.mark.parametrize("cached,age", [("broken", 0), ("[]", 0), ('{"old": true}', 8 * 86400)])
def test_invalid_or_expired_cache_is_refreshed(cache, monkeypatch, cached, age):
    """Only fresh JSON objects are eligible cache hits."""
    url = "https://api.gbif.org/example"
    cache.execute("INSERT INTO gbif_api_cache VALUES (?, ?, ?)", (url, cached, int(builder.time.time()) - age))
    cache.commit()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(b'{"fresh": true}'))
    assert builder.fetch_gbif_raw_api(url, cache) == {"fresh": True}


def test_cache_write_failure_preserves_successful_response(cache, monkeypatch, caplog):
    """Cache persistence failure must not throw away usable API results."""
    cache.execute("CREATE TRIGGER fail_write BEFORE INSERT ON gbif_api_cache BEGIN SELECT RAISE(ABORT, 'full'); END")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(b'{"usageKey": 1}'))
    assert builder.fetch_gbif_raw_api("https://api.gbif.org/example", cache) == {"usageKey": 1}
    assert "could not be cached" in caplog.text


@pytest.mark.parametrize("retry_after,delay", [("120", 120), (None, 60), ("invalid", 60), ("date", 90)])
def test_rate_limit_cooldown_allows_cache_and_delays_retry(cache, monkeypatch, retry_after, delay):
    """429 stops uncached requests across URLs while fresh cache remains usable."""
    monkeypatch.setattr(builder.time, "time", lambda: 1700000000.0)
    if retry_after == "date":
        retry_after = formatdate(1700000090, usegmt=True)
    cache.execute("INSERT INTO gbif_api_cache VALUES ('https://api.gbif.org/cached', '{}', 1700000000)")
    cache.commit()
    calls = []

    def request(req, **kwargs):
        calls.append(req.full_url)
        if len(calls) == 1:
            headers = {} if retry_after is None else {"Retry-After": retry_after}
            raise urllib.error.HTTPError(req.full_url, 429, "Slow down", headers, None)
        return Response(b'{}')

    monkeypatch.setattr("urllib.request.urlopen", request)
    with pytest.raises(builder.GBIFRequestError, match="429"):
        builder.fetch_gbif_raw_api("https://api.gbif.org/first", cache)
    with pytest.raises(builder.GBIFRequestError, match="paused"):
        builder.fetch_gbif_raw_api("https://api.gbif.org/second", cache)
    assert builder.fetch_gbif_raw_api("https://api.gbif.org/cached", cache) == {}
    assert len(calls) == 1
    monkeypatch.setattr(builder.time, "monotonic", lambda: 1000.0 + delay + 1)
    assert builder.fetch_gbif_raw_api("https://api.gbif.org/first", cache) == {}
    assert len(calls) == 2


@pytest.mark.parametrize("phase", ["enrich_vernacular_names_from_gbif", "enrich_higher_ranks_vernacular_names", "consolidate_synonyms_with_gbif"])
def test_network_failures_propagate_from_enrichment_workers(tmp_path, monkeypatch, cache, phase):
    """All production enrichment phases report an outage instead of success."""
    monkeypatch.setattr("taxo_trainer.db.ensure_data_dir", lambda: tmp_path)
    monkeypatch.setattr("taxo_trainer.db.GBIF_CACHE_DB_PATH", tmp_path / "cache.db")

    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_app_db(conn)
    conn.execute("""INSERT INTO taxa (taxon_key, scientific_name, canonical_name,
        accepted_name, rank, genus, family, vernacular_da)
        VALUES ('1', 'Quercus robur', 'Quercus robur', 'Quercus robur',
        'SPECIES', 'Quercus', 'Fagaceae', 'Existing name')""")
    conn.commit()
    try:
        with pytest.raises(builder.GBIFRequestError, match="incomplete"):
            getattr(builder, phase)(conn)
        assert conn.execute("SELECT vernacular_da FROM taxa").fetchone()[0] == "Existing name"
    finally:
        conn.close()
