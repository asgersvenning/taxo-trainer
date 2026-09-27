"""Manual release update lookup for the desktop app."""

import json
import re
import urllib.request

APP_VERSION = "0.1.6"
DOWNLOAD_PAGE = "https://asgersvenning.github.io/taxo-trainer/"
LATEST_RELEASE_API = "https://api.github.com/repos/asgersvenning/taxo-trainer/releases/latest"


def is_newer_release(tag: str, installed: str = APP_VERSION) -> bool:
    """Compare stable three-part release versions."""
    def parts(value: str) -> tuple[int, int, int]:
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
        if match is None:
            raise ValueError(f"Unexpected release version: {value}")
        return tuple(map(int, match.groups()))

    return parts(tag) > parts(installed)


def fetch_latest_release() -> str:
    """Return the latest public GitHub release tag on explicit user request."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"taxo-trainer/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        tag = json.load(response)["tag_name"]
    if not isinstance(tag, str):
        raise TypeError("GitHub returned an invalid release version.")
    is_newer_release(tag)
    return tag
