"""Reference photographs from locally imported, ID-linked observations."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticPhoto:
    """One reference image with its observation's provenance."""

    url: str
    occurrence_id: str
    recorded_by: str
    references: str
    locality: str


def get_diagnostic_photos(conn: sqlite3.Connection, taxon_key: str) -> list[DiagnosticPhoto]:
    """Collect distinct photos for a canonical taxon ID, grouped by observation.

    All matching imported observations are available for browsing. This function
    does not query remote services or infer taxonomic identity from a name.
    """
    photos = []
    seen = set()
    for row in conn.execute(
        """SELECT occurrence_id, media_urls, recorded_by, references_url, locality
           FROM occurrences WHERE taxon_key=? ORDER BY occurrence_id""", (str(taxon_key),)
    ):
        for value in (row["media_urls"] or "").split("|"):
            url = value.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            photos.append(DiagnosticPhoto(url, str(row["occurrence_id"]),
                                          row["recorded_by"] or "", row["references_url"] or "",
                                          row["locality"] or ""))
    return photos
