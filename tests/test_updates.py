"""Manual update checks against GitHub Releases."""

import io

import pytest

from taxo_trainer import updates


def test_release_version_comparison():
    assert updates.is_newer_release("v0.1.10", "0.1.5")
    assert not updates.is_newer_release("v0.1.5", "0.1.5")
    assert not updates.is_newer_release("v0.1.4", "0.1.5")
    with pytest.raises(ValueError):
        updates.is_newer_release("latest", "0.1.5")


def test_fetch_latest_release_is_manual_and_uses_public_api(monkeypatch):
    requests = []

    def open_response(request, timeout):
        requests.append((request.full_url, timeout))
        return io.BytesIO(b'{"tag_name":"v0.1.6"}')

    monkeypatch.setattr(updates.urllib.request, "urlopen", open_response)
    assert updates.fetch_latest_release() == "v0.1.6"
    assert requests == [(updates.LATEST_RELEASE_API, 10)]
