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
    species_name: str = ""


def get_diagnostic_photos(
    conn: sqlite3.Connection, taxon_key: str, rank: str = "SPECIES"
) -> list[DiagnosticPhoto]:
    """Collect local photos for a canonical taxon ID at the guessed rank.

    Species guesses retain the full gallery. Higher-rank guesses show one
    labelled photo from each of up to 24 spread-out descendant species.
    """
    group_column = {"GENUS": "genus_key", "FAMILY": "family_key", "ORDER": "order_key"}.get(rank)
    if group_column:
        members = conn.execute(
            f"""SELECT taxon_key, canonical_name FROM taxa
                WHERE {group_column}=? AND UPPER(rank) IN
                ('SPECIES', 'SUBSPECIES', 'VARIETY', 'FORM')
                ORDER BY canonical_name, taxon_key""",
            (str(taxon_key),),
        ).fetchall()
        if len(members) > 24:
            members = [members[index * (len(members) - 1) // 23] for index in range(24)]
        photos = []
        seen = set()
        for member in members:
            observation = conn.execute(
                """SELECT occurrence_id, media_urls, recorded_by, references_url, locality
                   FROM occurrences WHERE taxon_key=? AND TRIM(media_urls) != ''
                   ORDER BY occurrence_id LIMIT 1""",
                (str(member["taxon_key"]),),
            ).fetchone()
            if observation is None:
                continue
            url = next((part.strip() for part in observation["media_urls"].split("|")
                        if part.strip()), None)
            if not url or url in seen:
                continue
            seen.add(url)
            photos.append(DiagnosticPhoto(
                url, str(observation["occurrence_id"]), observation["recorded_by"] or "",
                observation["references_url"] or "", observation["locality"] or "",
                member["canonical_name"],
            ))
        return photos

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
