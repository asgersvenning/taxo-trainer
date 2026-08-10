"""Identification validation, fuzzy typo matching, and autocomplete engine.

Supports multi-rank evaluation (Family, Genus, Species) and vernacular fallback chains.
"""

import json
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class ValidationResult:
    """Dataclass holding validation evaluation results for a user guess."""

    user_input: str
    is_correct: bool
    matched_rank: str | None  # "FAMILY", "GENUS", "SPECIES"
    matched_taxon_key: int | None
    matched_name: str
    similarity_score: float
    is_soft_typo: bool
    feedback_message: str


def get_display_name(taxon_row: sqlite3.Row | dict, lang: str = "da") -> str:

    """Execute vernacular fallback chain according to preferred language (da, en, de, sv, no, fr, es, nl, la).

    Args:
        taxon_row: Database row or dict containing taxon columns.
        lang: Preferred language code ("da", "en", "de", "sv", "no", "fr", "es", "nl", "la").

    Returns:
        str: Best user-facing primary display name.
    """
    if lang == "la":
        if isinstance(taxon_row, sqlite3.Row):
            keys = taxon_row.keys()
            canon = taxon_row["canonical_name"] if "canonical_name" in keys else None
            sci = taxon_row["scientific_name"] if "scientific_name" in keys else None
        elif isinstance(taxon_row, dict):
            canon = taxon_row.get("canonical_name")
            sci = taxon_row.get("scientific_name")
        else:
            return "Unknown Species"
        return str(canon or sci or "Unknown Species").strip()

    v_json_raw = None
    if isinstance(taxon_row, sqlite3.Row):
        keys = taxon_row.keys()
        v_da_raw = taxon_row["vernacular_da"] if "vernacular_da" in keys else None
        v_en_raw = taxon_row["vernacular_en"] if "vernacular_en" in keys else None
        v_json_raw = taxon_row["vernacular_json"] if "vernacular_json" in keys else None
        canon = taxon_row["canonical_name"] if "canonical_name" in keys else None
        sci = taxon_row["scientific_name"] if "scientific_name" in keys else None
    elif isinstance(taxon_row, dict):
        v_da_raw = taxon_row.get("vernacular_da")
        v_en_raw = taxon_row.get("vernacular_en")
        v_json_raw = taxon_row.get("vernacular_json")
        canon = taxon_row.get("canonical_name")
        sci = taxon_row.get("scientific_name")
    else:
        return "Unknown Species"

    v_dict = {}
    if v_json_raw and str(v_json_raw).strip():
        try:
            v_dict = json.loads(str(v_json_raw).strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            v_dict = {}

    target_lang_str = v_dict.get(lang, "")
    if target_lang_str:
        return target_lang_str.split("|")[0].strip()

    # Fallbacks: requested lang -> da -> en -> canonical_name
    v_da = str(v_da_raw).split("|")[0].strip() if (v_da_raw and str(v_da_raw).strip()) else ""
    v_en = str(v_en_raw).split("|")[0].strip() if (v_en_raw and str(v_en_raw).strip()) else ""
    c_str = str(canon).strip() if (canon and str(canon).strip()) else ""
    s_str = str(sci).strip() if (sci and str(sci).strip()) else ""

    if lang == "en" and v_en:
        return v_en
    if v_da:
        return v_da
    if v_en:
        return v_en
    if c_str:
        return c_str
    return s_str if s_str else "Unknown Species"



def normalize_name(s: str) -> str:
    """Normalize string by removing dashes, spaces, and converting to lowercase for symmetric matching.

    Args:
        s: Input string.

    Returns:
        str: Cleaned string without dashes or spaces.
    """
    if not s:
        return ""
    return s.strip().lower().replace("-", "").replace(" ", "")


def autocomplete_taxa(
    conn: sqlite3.Connection, query: str, limit: int = 10, lang: str = "da"
) -> list[dict[str, str]]:
    """Autocomplete taxa query returning matching canonical, vernacular, genus, and family names.

    Prioritizes exact matches first (Priority 0), followed by Genus/Family matches,
    prefix matches, and symmetric substring matches.

    Args:
        conn: SQLite connection to app_data.db.
        query: User typed search string.
        limit: Max autocomplete suggestions.
        lang: Preferred language ("da", "en", etc.).

    Returns:
        List[Dict[str, str]]: List of suggestion objects containing label, value, rank, taxon_key.
    """
    if not query or len(query.strip()) < 2:
        return []

    q_strip = query.strip().lower()
    q_clean = normalize_name(query)

    prefix_pat = f"{q_strip}%"
    sub_pat = f"%{q_strip}%"
    clean_prefix_pat = f"{q_clean}%"
    clean_sub_pat = f"%{q_clean}%"

    results: list[dict[str, str]] = []
    seen_values = set()

    params = {
        "exact": q_strip,
        "clean_exact": q_clean,
        "prefix": prefix_pat,
        "clean_prefix": clean_prefix_pat,
    }

    # 1. Check for Genus matches (scientific or vernacular)
    genus_cursor = conn.execute(
        """SELECT DISTINCT t.genus, h.vernacular_da, h.vernacular_en, h.vernacular_json 
           FROM taxa t
           LEFT JOIN higher_ranks h ON h.rank_name = t.genus
           WHERE t.genus IS NOT NULL AND t.genus != '' 
             AND (LOWER(t.genus) LIKE :prefix 
               OR LOWER(h.vernacular_da) LIKE :prefix 
               OR LOWER(h.vernacular_en) LIKE :prefix
               OR REPLACE(REPLACE(LOWER(t.genus), '-', ''), ' ', '') LIKE :clean_prefix
               OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_prefix)
           ORDER BY CASE WHEN LOWER(t.genus) = :exact OR LOWER(h.vernacular_da) = :exact THEN 0 ELSE 1 END, t.genus ASC
           LIMIT 3""",
        params,
    )
    for r in genus_cursor.fetchall():
        g_name = r["genus"]
        if g_name and g_name not in seen_values:
            g_disp = get_display_name(r, lang=lang)
            g_label = f"📁 Genus: {g_disp} ({g_name})" if g_disp != g_name else f"📁 Genus: {g_name}"
            results.append({
                "label": g_label,
                "value": g_name,
                "display_name": g_disp,
                "canonical_name": g_name,
                "rank": "GENUS",
                "taxon_key": None,
            })
            seen_values.add(g_name)

    # 2. Check for Family matches (scientific or vernacular)
    family_cursor = conn.execute(
        """SELECT DISTINCT t.family, h.vernacular_da, h.vernacular_en, h.vernacular_json 
           FROM taxa t
           LEFT JOIN higher_ranks h ON h.rank_name = t.family
           WHERE t.family IS NOT NULL AND t.family != '' 
             AND (LOWER(t.family) LIKE :prefix 
               OR LOWER(h.vernacular_da) LIKE :prefix 
               OR LOWER(h.vernacular_en) LIKE :prefix
               OR REPLACE(REPLACE(LOWER(t.family), '-', ''), ' ', '') LIKE :clean_prefix
               OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_prefix)
           ORDER BY CASE WHEN LOWER(t.family) = :exact OR LOWER(h.vernacular_da) = :exact THEN 0 ELSE 1 END, t.family ASC
           LIMIT 3""",
        params,
    )

    for r in family_cursor.fetchall():
        f_name = r["family"]
        if f_name and f_name not in seen_values:
            f_disp = get_display_name(r, lang=lang)
            f_label = f"🏛️ Family: {f_disp} ({f_name})" if f_disp != f_name else f"🏛️ Family: {f_name}"
            results.append({
                "label": f_label,
                "value": f_name,
                "display_name": f_disp,
                "canonical_name": f_name,
                "rank": "FAMILY",
                "taxon_key": None,
            })
            seen_values.add(f_name)


    # 3. Species matches with Priority 0 for exact full name matches
    sql = """
        SELECT taxon_key, canonical_name, scientific_name, rank, family, genus, vernacular_da, vernacular_en, vernacular_json,
               CASE
                   WHEN LOWER(canonical_name) = :exact
                     OR LOWER(vernacular_da) = :exact
                     OR LOWER(vernacular_en) = :exact
                     OR LOWER(vernacular_json) LIKE '%"' || :exact || '"%'
                     OR LOWER(vernacular_json) LIKE '%|' || :exact || '|%'
                     OR LOWER(vernacular_json) LIKE '%|' || :exact || '"%'
                     OR LOWER(vernacular_json) LIKE '%"' || :exact || '|%'
                     OR REPLACE(REPLACE(LOWER(canonical_name), '-', ''), ' ', '') = :clean_exact
                     OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') = :clean_exact THEN 0
                   WHEN LOWER(canonical_name) LIKE :prefix
                     OR LOWER(vernacular_da) LIKE :prefix
                     OR LOWER(vernacular_en) LIKE :prefix
                     OR LOWER(scientific_name) LIKE :prefix
                     OR LOWER(vernacular_json) LIKE :sub THEN 1
                   WHEN LOWER(canonical_name) LIKE :sub
                     OR LOWER(vernacular_da) LIKE :sub
                     OR LOWER(vernacular_en) LIKE :sub
                     OR LOWER(scientific_name) LIKE :sub THEN 2
                   WHEN REPLACE(REPLACE(LOWER(canonical_name), '-', ''), ' ', '') LIKE :clean_prefix
                     OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_prefix
                     OR REPLACE(REPLACE(LOWER(vernacular_en), '-', ''), ' ', '') LIKE :clean_prefix
                     OR REPLACE(REPLACE(LOWER(scientific_name), '-', ''), ' ', '') LIKE :clean_prefix THEN 3
                   ELSE 4
               END AS priority
        FROM taxa
        WHERE LOWER(canonical_name) LIKE :sub
           OR LOWER(vernacular_da) LIKE :sub
           OR LOWER(vernacular_en) LIKE :sub
           OR LOWER(scientific_name) LIKE :sub
           OR LOWER(vernacular_json) LIKE :sub
           OR family LIKE :sub
           OR genus LIKE :sub
           OR REPLACE(REPLACE(LOWER(canonical_name), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(vernacular_en), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(scientific_name), '-', ''), ' ', '') LIKE :clean_sub
        ORDER BY priority ASC, LENGTH(canonical_name) ASC, canonical_name ASC
        LIMIT :rem_limit
    """

    rem_limit = max(1, limit - len(results))
    cursor = conn.execute(
        sql,
        {
            "exact": q_strip,
            "clean_exact": q_clean,
            "prefix": prefix_pat,
            "sub": sub_pat,
            "clean_prefix": clean_prefix_pat,
            "clean_sub": clean_sub_pat,
            "rem_limit": rem_limit,
        },
    )

    for row in cursor.fetchall():
        display = get_display_name(row, lang=lang)
        canon = row["canonical_name"]
        if canon not in seen_values:
            label = f"{display} ({canon})" if display != canon else canon
            results.append({
                "label": label,
                "value": canon,
                "display_name": display,
                "canonical_name": canon,
                "rank": row["rank"],
                "taxon_key": row["taxon_key"],
            })
            seen_values.add(canon)

    return results[:limit]



def check_string_similarity(a: str, b: str) -> float:
    """Calculate SequenceMatcher similarity score between two normalized strings.

    Args:
        a: String input A.
        b: String input B.

    Returns:
        float: Similarity ratio between 0.0 and 1.0.
    """
    norm_a = normalize_name(a)
    norm_b = normalize_name(b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def validate_user_guess(
    conn: sqlite3.Connection,
    user_input: str,
    target_taxon_key: int,
    typo_threshold: float = 0.90,
    lang: str = "da",
) -> ValidationResult:
    """Validate user guess against target taxon across Family, Genus, and Species ranks.

    Args:
        conn: Connection to app_data.db.
        user_input: Raw input guess string.
        target_taxon_key: Target GBIF taxon_key for observation.
        typo_threshold: SequenceMatcher similarity threshold for soft typo acceptance (default >0.90).
        lang: Preferred language ("da" or "en").

    Returns:
        ValidationResult: Detailed validation outcome dataclass.
    """
    clean_input = user_input.strip()
    if not clean_input:
        return ValidationResult(
            user_input=user_input,
            is_correct=False,
            matched_rank=None,
            matched_taxon_key=None,
            matched_name="",
            similarity_score=0.0,
            is_soft_typo=False,
            feedback_message="Please enter a species, genus, or family name.",
        )

    # 1. Fetch target taxon details
    cursor = conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (target_taxon_key,))
    target_row = cursor.fetchone()
    if not target_row:
        return ValidationResult(
            user_input=user_input,
            is_correct=False,
            matched_rank=None,
            matched_taxon_key=None,
            matched_name="",
            similarity_score=0.0,
            is_soft_typo=False,
            feedback_message="Target species record missing.",
        )

    target_canonical = target_row["canonical_name"].strip()
    target_sci = target_row["scientific_name"].strip()
    target_da = (target_row["vernacular_da"] or "").strip()
    target_en = (target_row["vernacular_en"] or "").strip()
    target_genus = (target_row["genus"] or "").strip()
    target_family = (target_row["family"] or "").strip()

    input_lower = clean_input.lower()
    input_clean = normalize_name(clean_input)

    # Direct exact / symmetric check against target species (including all multi-language pipe-separated vernacular variations)
    target_names_clean = [
        normalize_name(target_canonical),
        normalize_name(target_sci),
    ]

    v_json_raw = target_row["vernacular_json"] if "vernacular_json" in target_row.keys() else None  # noqa: SIM118
    v_dict = {}
    if v_json_raw and str(v_json_raw).strip():
        try:
            v_dict = json.loads(str(v_json_raw).strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            v_dict = {}

    for pipe_str in v_dict.values():
        if pipe_str:
            for part in pipe_str.split("|"):
                norm_p = normalize_name(part)
                if norm_p and norm_p not in target_names_clean:
                    target_names_clean.append(norm_p)

    if target_da:
        for part in target_da.split("|"):
            norm_p = normalize_name(part)
            if norm_p and norm_p not in target_names_clean:
                target_names_clean.append(norm_p)

    if target_en:
        for part in target_en.split("|"):
            norm_p = normalize_name(part)
            if norm_p and norm_p not in target_names_clean:
                target_names_clean.append(norm_p)


    if input_clean in target_names_clean and input_clean != "":
        return ValidationResult(
            user_input=user_input,
            is_correct=True,
            matched_rank="SPECIES",
            matched_taxon_key=target_taxon_key,
            matched_name=get_display_name(target_row, lang=lang),
            similarity_score=1.0,
            is_soft_typo=False,
            feedback_message="Correct species identification!",
        )

    # Direct exact / symmetric check against target genus (including scientific name and higher_ranks vernaculars)
    if target_genus:
        genus_names_clean = [normalize_name(target_genus)]
        g_row = conn.execute("SELECT vernacular_da, vernacular_en, vernacular_json FROM higher_ranks WHERE rank_name = ?", (target_genus,)).fetchone()
        if g_row:
            for v_col in [g_row["vernacular_da"], g_row["vernacular_en"]]:
                if v_col:
                    for part in v_col.split("|"):
                        np = normalize_name(part)
                        if np and np not in genus_names_clean:
                            genus_names_clean.append(np)
            if g_row["vernacular_json"]:
                try:
                    g_dict = json.loads(g_row["vernacular_json"])
                    for p_str in g_dict.values():
                        if p_str:
                            for part in p_str.split("|"):
                                np = normalize_name(part)
                                if np and np not in genus_names_clean:
                                    genus_names_clean.append(np)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        if input_clean in genus_names_clean:
            g_disp = get_display_name(g_row, lang=lang) if g_row else target_genus
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="GENUS",
                matched_taxon_key=None,
                matched_name=f"{g_disp} ({target_genus})" if g_disp != target_genus else target_genus,
                similarity_score=1.0,
                is_soft_typo=False,
                feedback_message=f"Correct Genus! ({g_disp} / {target_genus}). Now identify the species.",
            )

    # Direct exact / symmetric check against target family (including scientific name and higher_ranks vernaculars)
    if target_family:
        family_names_clean = [normalize_name(target_family)]
        f_row = conn.execute("SELECT vernacular_da, vernacular_en, vernacular_json FROM higher_ranks WHERE rank_name = ?", (target_family,)).fetchone()
        if f_row:
            for v_col in [f_row["vernacular_da"], f_row["vernacular_en"]]:
                if v_col:
                    for part in v_col.split("|"):
                        np = normalize_name(part)
                        if np and np not in family_names_clean:
                            family_names_clean.append(np)
            if f_row["vernacular_json"]:
                try:
                    f_dict = json.loads(f_row["vernacular_json"])
                    for p_str in f_dict.values():
                        if p_str:
                            for part in p_str.split("|"):
                                np = normalize_name(part)
                                if np and np not in family_names_clean:
                                    family_names_clean.append(np)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        if input_clean in family_names_clean:
            f_disp = get_display_name(f_row, lang=lang) if f_row else target_family
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="FAMILY",
                matched_taxon_key=None,
                matched_name=f"{f_disp} ({target_family})" if f_disp != target_family else target_family,
                similarity_score=1.0,
                is_soft_typo=False,
                feedback_message=f"Correct Family! ({f_disp} / {target_family}). Now refine to Genus or Species.",
            )


    # Check fuzzy typo match against target names
    all_target_variants = [target_canonical, target_sci]
    if target_da:
        all_target_variants.extend([p.strip() for p in target_da.split("|") if p.strip()])
    if target_en:
        all_target_variants.extend([p.strip() for p in target_en.split("|") if p.strip()])

    for name in all_target_variants:
        if not name:
            continue
        sim = check_string_similarity(input_clean, name)
        if sim >= typo_threshold:
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="SPECIES",
                matched_taxon_key=target_taxon_key,
                matched_name=get_display_name(target_row, lang=lang),
                similarity_score=sim,
                is_soft_typo=True,
                feedback_message=f"Correct! (Soft typo correction for '{name.title()}')",
            )


    # Fuzzy check on Genus
    if target_genus:
        sim_g = check_string_similarity(input_clean, target_genus)
        if sim_g >= typo_threshold:
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="GENUS",
                matched_taxon_key=None,
                matched_name=target_row["genus"],
                similarity_score=sim_g,
                is_soft_typo=True,
                feedback_message=f"Correct Genus '{target_row['genus']}'! (Soft typo accepted).",
            )

    # Fuzzy check on Family
    if target_family:
        sim_f = check_string_similarity(input_clean, target_family)
        if sim_f >= typo_threshold:
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="FAMILY",
                matched_taxon_key=None,
                matched_name=target_row["family"],
                similarity_score=sim_f,
                is_soft_typo=True,
                feedback_message=f"Correct Family '{target_row['family']}'! (Soft typo accepted).",
            )

    # Query database to identify if user entered a real taxon name (species, genus, family, or pipe-separated vernacular)
    guessed_cursor = conn.execute(
        """
        SELECT taxon_key, canonical_name, genus, family, order_name FROM taxa
        WHERE LOWER(canonical_name) = :raw
           OR LOWER(vernacular_da) = :raw
           OR LOWER(vernacular_en) = :raw
           OR LOWER(scientific_name) = :raw
           OR LOWER(genus) = :raw
           OR LOWER(family) = :raw
           OR LOWER(vernacular_da) LIKE :pipe_prefix
           OR LOWER(vernacular_da) LIKE :pipe_suffix
           OR LOWER(vernacular_da) LIKE :pipe_mid
           OR LOWER(vernacular_en) LIKE :pipe_prefix
           OR LOWER(vernacular_en) LIKE :pipe_suffix
           OR LOWER(vernacular_en) LIKE :pipe_mid
           OR LOWER(vernacular_json) LIKE :json_pat
           OR REPLACE(REPLACE(LOWER(canonical_name), '-', ''), ' ', '') = :clean
           OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_pipe_prefix
           OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_pipe_suffix
           OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_pipe_mid
        LIMIT 1
        """,
        {
            "raw": input_lower,
            "clean": input_clean,
            "pipe_prefix": f"{input_lower}|%",
            "pipe_suffix": f"%|{input_lower}",
            "pipe_mid": f"%|{input_lower}|%",
            "json_pat": f"%\"{input_lower}\"%",
            "clean_pipe_prefix": f"{input_clean}|%",
            "clean_pipe_suffix": f"%|{input_clean}",
            "clean_pipe_mid": f"%|{input_clean}|%",
        },
    )
    guessed_row = guessed_cursor.fetchone()

    if not guessed_row:
        # Check higher_ranks table for Genus/Family names
        hr_row = conn.execute(
            """SELECT rank_name, rank_level FROM higher_ranks 
               WHERE LOWER(rank_name) = :raw 
                  OR LOWER(vernacular_da) LIKE :pipe_prefix
                  OR LOWER(vernacular_da) = :raw
                  OR LOWER(vernacular_en) = :raw
               LIMIT 1""",
            {"raw": input_lower, "pipe_prefix": f"%{input_lower}%"},
        ).fetchone()
        if hr_row:
            guessed_row = {"taxon_key": None, "canonical_name": hr_row["rank_name"], "genus": hr_row["rank_name"] if hr_row["rank_level"] == "GENUS" else None, "family": hr_row["rank_name"] if hr_row["rank_level"] == "FAMILY" else None, "order_name": None}

    if not guessed_row:
        return ValidationResult(
            user_input=user_input,
            is_correct=False,
            matched_rank=None,
            matched_taxon_key=None,
            matched_name="",
            similarity_score=0.0,
            is_soft_typo=False,
            feedback_message=f"Unrecognized taxon name '{user_input}'. Please check spelling or select from suggestions.",
        )

    return ValidationResult(
        user_input=user_input,
        is_correct=False,
        matched_rank=None,
        matched_taxon_key=guessed_row["taxon_key"],
        matched_name=guessed_row["canonical_name"],
        similarity_score=0.0,
        is_soft_typo=False,
        feedback_message=f"Incorrect. Target species was {get_display_name(target_row)} ({target_row['canonical_name']}).",
    )



