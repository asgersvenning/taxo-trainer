"""Language-aware, user-facing summaries of available species names."""

import json
import math
import sqlite3

from taxo_trainer.ingestion.taxonomy_builder import GBIFRequestError

LANGUAGE_NAMES = {
    "da": "Danish", "en": "English", "de": "German", "sv": "Swedish",
    "no": "Norwegian", "fi": "Finnish", "pl": "Polish", "cs": "Czech",
    "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch",
}


def name_lookup_failure_message(error: Exception) -> str:
    """Give an actionable explanation while technical details stay in logs."""
    if isinstance(error, GBIFRequestError) and error.retry_after_seconds is not None:
        minutes = max(1, math.ceil(error.retry_after_seconds / 60))
        return (
            f"GBIF has asked us to pause. Try again in about {minutes} "
            f"{'minute' if minutes == 1 else 'minutes'}. Names already saved are kept."
        )
    return "Name lookup did not finish. Names already saved are kept. Please try again later."


def name_coverage_summary(conn: sqlite3.Connection, language: str) -> str:
    """Describe names actually available in the user's preferred language.

    Args:
        conn: Current dataset connection.
        language: Preferred vernacular language, or 'la' for scientific names.
    """
    rows = conn.execute(
        "SELECT vernacular_da, vernacular_en, vernacular_json FROM taxa "
        "WHERE UPPER(rank) = 'SPECIES'"
    ).fetchall()
    if not rows:
        return "Import a dataset to look up species names."
    if language == "la":
        return "Scientific names are selected. Vernacular-name lookup is optional."

    named = 0
    for da, en, raw_names in rows:
        try:
            names = json.loads(raw_names) if raw_names else {}
        except (TypeError, ValueError):
            names = {}
        value = names.get(language) if isinstance(names, dict) else None
        dedicated = da if language == "da" else en if language == "en" else None
        if any(
            isinstance(candidate, str) and any(part.strip() for part in candidate.split("|"))
            for candidate in (value, dedicated)
        ):
            named += 1

    language_name = LANGUAGE_NAMES.get(language, language)
    summary = f"{language_name} names available for {named:,} of {len(rows):,} species."
    missing = len(rows) - named
    if missing:
        summary += (
            f" {missing:,} still without {language_name} names."
            " You can continue training with the names already available."
        )
    return summary
