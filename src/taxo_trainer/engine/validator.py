"""Identification validation, fuzzy typo matching, and autocomplete engine.

Supports multi-rank evaluation (Family, Genus, Species) and vernacular fallback chains.
"""

import json
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


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


from taxo_trainer.db import row_to_dict


def get_display_name(taxon_row: sqlite3.Row | dict | None, lang: str = "da") -> str:
    """Execute vernacular fallback chain according to preferred language (da, en, de, sv, no, fr, es, nl, la).

    Args:
        taxon_row: Database row or dict containing taxon columns.
        lang: Preferred language code ("da", "en", "de", "sv", "no", "fr", "es", "nl", "la").

    Returns:
        str: Best user-facing primary display name.
    """
    if not taxon_row:
        return "Unknown Species"

    d = row_to_dict(taxon_row)
    canon = d.get("canonical_name") or d.get("rank_name") or d.get("genus") or d.get("family")
    sci = d.get("scientific_name")

    if lang == "la":
        return str(canon or sci or "Unknown Species").strip()

    v_da_raw = d.get("vernacular_da")
    v_en_raw = d.get("vernacular_en")
    v_json_raw = d.get("vernacular_json")

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
    v_da = (
        str(v_da_raw).split("|")[0].strip()
        if (v_da_raw and str(v_da_raw).strip())
        else ""
    )
    v_en = (
        str(v_en_raw).split("|")[0].strip()
        if (v_en_raw and str(v_en_raw).strip())
        else ""
    )
    c_str = str(canon).strip() if (canon and str(canon).strip()) else ""
    s_str = str(sci).strip() if (sci and str(sci).strip()) else ""

    if lang == "da" and v_da:
        return v_da
    if lang == "en" and v_en:
        return v_en
    if v_da and lang not in ("en", "la"):
        return v_da
    if v_en and lang == "en":
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
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    lang: str = "da",
    parent_genus: str | None = None,
    parent_family: str | None = None,
    parent_order: str | None = None,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Autocomplete taxa query returning matching canonical, vernacular, genus, and family names.

    Prioritizes exact matches first (Priority 0), followed by Genus/Family matches,
    prefix matches, and symmetric substring matches. If parent rank constraints are passed,
    suggestions are strictly scoped to valid sub-taxa.

    Args:
        conn: SQLite connection to app_data.db.
        query: User typed search string.
        limit: Max autocomplete suggestions.
        lang: Preferred language ("da", "en", etc.).
        parent_genus: Optional genus constraint to restrict suggestions to species within genus.
        parent_family: Optional family constraint to restrict suggestions to genera/species within family.
        parent_order: Optional order constraint to restrict suggestions to family/genus/species within order.
        min_count: Minimum occurrence count cutoff threshold.

    Returns:
        List[Dict[str, str]]: List of suggestion objects containing label, value, rank, taxon_key.
    """
    if not query or len(query.strip()) < 2:
        return []

    q_strip = query.strip().lower()
    q_clean = normalize_name(query)

    sub_pat = f"%{q_strip}%"
    clean_sub_pat = f"%{q_clean}%"

    p_gen = (
        parent_genus.strip().lower() if parent_genus and parent_genus.strip() else None
    )
    p_fam = (
        parent_family.strip().lower()
        if parent_family and parent_family.strip()
        else None
    )
    p_ord = (
        parent_order.strip().lower() if parent_order and parent_order.strip() else None
    )

    params = {
        "sub": sub_pat,
        "clean_sub": clean_sub_pat,
        "lang_code": lang,
        "p_gen": p_gen or "",
        "p_fam": p_fam or "",
        "p_ord": p_ord or "",
        "min_count": min_count if min_count > 1 else 0,
    }

    candidates: list[dict[str, Any]] = []
    seen_values = set()

    def calc_priority_and_rank_weight(
        canon: str,
        rank_str: str,
        primary_vernaculars: list[str | None],
        secondary_names: list[str | None],
    ) -> tuple[int, int]:
        r = (rank_str or "").upper()
        rw = (
            1
            if r in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM")
            else (2 if r == "GENUS" else (3 if r == "FAMILY" else 4))
        )

        def is_title_prefix(
            name: str | None, target: str, target_clean: str
        ) -> bool:
            if not name:
                return False
            for part in str(name).split("|"):
                p_l = part.strip().lower()
                p_c = normalize_name(part)
                if p_l.startswith(target) or p_c.startswith(target_clean):
                    return True
                for suf in (
                    "-slægten",
                    " slægten",
                    "-familien",
                    " familien",
                    "-ordenen",
                    " ordenen",
                ):
                    if p_l.endswith(suf):
                        base_l = p_l[: -len(suf)].strip()
                        base_c = normalize_name(base_l)
                        if base_l.startswith(target) or base_c.startswith(target_clean):
                            return True
            return False

        def is_word_prefix(
            name: str | None, target: str, target_clean: str
        ) -> bool:
            if not name:
                return False
            for part in str(name).split("|"):
                p_l = part.strip().lower()
                p_c = normalize_name(part)
                words = [
                    w for w in p_l.replace("-", " ").replace("/", " ").split() if w
                ]
                if any(w.startswith(target) for w in words):
                    return True
                clean_words = [
                    w for w in p_c.replace("-", " ").replace("/", " ").split() if w
                ]
                if any(w.startswith(target_clean) for w in clean_words):
                    return True
            return False

        # 1. Exact match on canonical_name or primary vernacular (including base-words without -slægten/-familien)
        for n in [canon] + primary_vernaculars:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if p_l == q_strip or p_c == q_clean:
                    return 0, rw
                for suf in (
                    "-slægten",
                    " slægten",
                    "-familien",
                    " familien",
                    "-ordenen",
                    " ordenen",
                ):
                    if p_l.endswith(suf):
                        base_l = p_l[: -len(suf)].strip()
                        base_c = normalize_name(base_l)
                        if base_l == q_strip or base_c == q_clean:
                            return 0, rw

        # 2. Exact match on secondary names
        for n in secondary_names:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if p_l == q_strip or p_c == q_clean:
                    return 1, rw

        # 3. Title/Full-name prefix match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if is_title_prefix(n, q_strip, q_clean):
                return 2, rw

        # 4. Title/Full-name prefix match on secondary names
        for n in secondary_names:
            if is_title_prefix(n, q_strip, q_clean):
                return 3, rw

        # 5. Subword prefix match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if is_word_prefix(n, q_strip, q_clean):
                return 4, rw

        # 6. Subword prefix match on secondary names
        for n in secondary_names:
            if is_word_prefix(n, q_strip, q_clean):
                return 5, rw

        # 7. Substring match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if q_strip in p_l or q_clean in p_c:
                    return 6, rw

        # 8. Substring match on secondary names
        for n in secondary_names:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if q_strip in p_l or q_clean in p_c:
                    return 7, rw

        return 8, 4

    # 1. Species matches
    sp_where_extra = ""
    if p_gen:
        sp_where_extra = " AND LOWER(genus) = :p_gen"
    elif p_fam:
        sp_where_extra = " AND LOWER(family) = :p_fam"
    elif p_ord:
        sp_where_extra = " AND LOWER(order_name) = :p_ord"

    sp_sql = f"""
        SELECT taxon_key, canonical_name, scientific_name, rank, family, genus, vernacular_da, vernacular_en, vernacular_json
        FROM taxa
        WHERE occurrence_count >= :min_count
          AND (LOWER(canonical_name) LIKE :sub
           OR LOWER(vernacular_da) LIKE :sub
           OR LOWER(vernacular_en) LIKE :sub
           OR LOWER(scientific_name) LIKE :sub
           OR json_extract(vernacular_json, '$.' || :lang_code) LIKE :sub
           OR REPLACE(REPLACE(LOWER(canonical_name), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(vernacular_da), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(vernacular_en), '-', ''), ' ', '') LIKE :clean_sub
           OR REPLACE(REPLACE(LOWER(scientific_name), '-', ''), ' ', '') LIKE :clean_sub){sp_where_extra}
    """
    for row in conn.execute(sp_sql, params).fetchall():
        r_str = (row["rank"] or "SPECIES").upper()
        if r_str in (
            "FAMILY",
            "GENUS",
            "ORDER",
            "CLASS",
            "PHYLUM",
            "KINGDOM",
            "UNRANKED",
            "HIGHER",
        ):
            continue
        canon = row["canonical_name"]
        if canon not in seen_values:
            seen_values.add(canon)
            display = get_display_name(row, lang=lang)
            primary_v = (
                [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
            )
            v_json_raw = row.get("vernacular_json") if "vernacular_json" in row else None
            if v_json_raw:
                try:
                    v_dict = json.loads(v_json_raw)
                    if v_dict.get(lang):
                        primary_v.append(v_dict[lang])
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            secondary_v = [row["scientific_name"]]
            if lang == "da" and row["vernacular_en"]:
                secondary_v.append(row["vernacular_en"])
            elif lang != "da" and row["vernacular_da"]:
                secondary_v.append(row["vernacular_da"])
            prio, rw = calc_priority_and_rank_weight(canon, r_str, primary_v, secondary_v)
            if prio >= 8:
                continue
            label = f"{display} ({canon})" if display != canon else canon
            candidates.append(
                {
                    "label": label,
                    "value": canon,
                    "display_name": display,
                    "canonical_name": canon,
                    "rank": r_str,
                    "taxon_key": row["taxon_key"],
                    "priority": prio,
                    "rank_order": rw,
                }
            )

    # 2. Genus matches (only if genus has not already been guessed)
    if not p_gen:
        g_where_extra = ""
        if p_fam:
            g_where_extra = " AND LOWER(t.family) = :p_fam"
        elif p_ord:
            g_where_extra = " AND LOWER(t.order_name) = :p_ord"

        g_sql = f"""
            SELECT DISTINCT t.genus, h.vernacular_da, h.vernacular_en, h.vernacular_json 
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.rank_name = t.genus
            WHERE t.genus IS NOT NULL AND t.genus != '' AND t.occurrence_count >= :min_count{g_where_extra}
              AND (LOWER(t.genus) LIKE :sub 
                OR LOWER(h.vernacular_da) LIKE :sub 
                OR LOWER(h.vernacular_en) LIKE :sub
                OR json_extract(h.vernacular_json, '$.' || :lang_code) LIKE :sub
                OR REPLACE(REPLACE(LOWER(t.genus), '-', ''), ' ', '') LIKE :clean_sub
                OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_sub)
        """
        for row in conn.execute(g_sql, params).fetchall():
            g_name = row["genus"]
            if g_name and g_name not in seen_values:
                seen_values.add(g_name)
                g_disp = get_display_name(row, lang=lang)
                primary_v = (
                    [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
                )
                v_json_raw = (
                    row.get("vernacular_json") if "vernacular_json" in row else None
                )
                if v_json_raw:
                    try:
                        v_dict = json.loads(v_json_raw)
                        if v_dict.get(lang):
                            primary_v.append(v_dict[lang])
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                secondary_v = [
                    row["vernacular_en"] if lang == "da" else row["vernacular_da"]
                ]
                prio, rw = calc_priority_and_rank_weight(g_name, "GENUS", primary_v, secondary_v)
                if prio >= 6:
                    continue
                g_label = (
                    f"📁 Genus: {g_disp} ({g_name})"
                    if g_disp and g_disp != g_name and g_disp != "Unknown Species"
                    else f"📁 Genus: {g_name}"
                )
                candidates.append(
                    {
                        "label": g_label,
                        "value": g_name,
                        "display_name": g_disp,
                        "canonical_name": g_name,
                        "rank": "GENUS",
                        "taxon_key": None,
                        "priority": prio,
                        "rank_order": rw,
                    }
                )

    # 3. Family matches (only if family or genus has not already been guessed)
    if not p_gen and not p_fam:
        f_where_extra = ""
        if p_ord:
            f_where_extra = " AND LOWER(t.order_name) = :p_ord"

        f_sql = f"""
            SELECT DISTINCT t.family, h.vernacular_da, h.vernacular_en, h.vernacular_json 
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.rank_name = t.family
            WHERE t.family IS NOT NULL AND t.family != '' AND t.occurrence_count >= :min_count{f_where_extra}
              AND (LOWER(t.family) LIKE :sub 
                OR LOWER(h.vernacular_da) LIKE :sub 
                OR LOWER(h.vernacular_en) LIKE :sub
                OR json_extract(h.vernacular_json, '$.' || :lang_code) LIKE :sub
                OR REPLACE(REPLACE(LOWER(t.family), '-', ''), ' ', '') LIKE :clean_sub
                OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_sub)
        """
        for row in conn.execute(f_sql, params).fetchall():
            f_name = row["family"]
            if f_name and f_name not in seen_values:
                seen_values.add(f_name)
                f_disp = get_display_name(row, lang=lang)
                primary_v = (
                    [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
                )
                v_json_raw = (
                    row.get("vernacular_json") if "vernacular_json" in row else None
                )
                if v_json_raw:
                    try:
                        v_dict = json.loads(v_json_raw)
                        if v_dict.get(lang):
                            primary_v.append(v_dict[lang])
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                secondary_v = [
                    row["vernacular_en"] if lang == "da" else row["vernacular_da"]
                ]
                prio, rw = calc_priority_and_rank_weight(f_name, "FAMILY", primary_v, secondary_v)
                if prio >= 6:
                    continue
                f_label = (
                    f"🏛️ Family: {f_disp} ({f_name})"
                    if f_disp and f_disp != f_name and f_disp != "Unknown Species"
                    else f"🏛️ Family: {f_name}"
                )
                candidates.append(
                    {
                        "label": f_label,
                        "value": f_name,
                        "display_name": f_disp,
                        "canonical_name": f_name,
                        "rank": "FAMILY",
                        "taxon_key": None,
                        "priority": prio,
                        "rank_order": rw,
                    }
                )

    # Filter out pseudo-species candidates whose canonical/scientific name represents a higher rank
    higher_canonical = {
        normalize_name(c["canonical_name"]) for c in candidates if (c["rank"] or "").upper() in ("GENUS", "FAMILY")
    }

    filtered_candidates = []
    for c in candidates:
        r_up = (c["rank"] or "").upper()
        if r_up in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM"):
            norm_c = normalize_name(c["canonical_name"])
            if norm_c in higher_canonical:
                continue
        filtered_candidates.append(c)
    candidates = filtered_candidates

    # Count distinct concept/display names per rank group for strong matches (priority <= 4) to determine rank ambiguity
    rank_distinct_names: dict[str, set[str]] = {}
    for c in candidates:
        if c["priority"] <= 4:
            r_str = (c["rank"] or "").upper()
            r_grp = (
                "SPECIES"
                if r_str in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM")
                else r_str
            )
            norm_disp = normalize_name(c["display_name"])
            rank_distinct_names.setdefault(r_grp, set()).add(norm_disp)

    def get_sort_key(c: dict[str, Any]) -> tuple:
        r_upper = (c["rank"] or "").upper()
        r_grp = (
            "SPECIES"
            if r_upper in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM")
            else r_upper
        )
        # 1. Exact species match (priority 0 on species rank) always at the very top
        is_exact_species = 0 if (c["priority"] == 0 and r_grp == "SPECIES") else 1
        # 2. Unambiguous rank level first (only 1 distinct display name matched at this rank level)
        distinct_cnt = len(rank_distinct_names.get(r_grp, set()))
        is_unambiguous = 0 if distinct_cnt == 1 else 1

        return (
            is_exact_species,
            is_unambiguous,
            c["priority"],
            c["rank_order"],
            len(c["display_name"]),
            c["display_name"],
        )

    candidates.sort(key=get_sort_key)

    results: list[dict[str, Any]] = []
    for c in candidates[:limit]:
        results.append(
            {
                "label": c["label"],
                "value": c["value"],
                "display_name": c["display_name"],
                "canonical_name": c["canonical_name"],
                "rank": c["rank"],
                "taxon_key": c["taxon_key"],
            }
        )
    return results


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
    target_taxon_key: int | str,
    typo_threshold: float = 0.90,
    lang: str = "da",
    min_count: int = 1,
) -> ValidationResult:
    """Validate user guess against target taxon across Family, Genus, and Species ranks.

    Args:
        conn: Connection to app_data.db.
        user_input: Raw input guess string.
        target_taxon_key: Target GBIF taxon_key for observation.
        typo_threshold: SequenceMatcher similarity threshold for soft typo acceptance (default >0.90).
        lang: Preferred language ("da" or "en").
        min_count: Minimum occurrence count cutoff threshold for valid taxa lookup.

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
    import re

    target_names_clean = [
        normalize_name(target_canonical),
        normalize_name(target_sci),
    ]
    for syn in re.findall(r"\((.*?)\)", target_sci):
        norm_syn = normalize_name(syn)
        if norm_syn and norm_syn not in target_names_clean:
            target_names_clean.append(norm_syn)

    v_json_raw = (
        target_row["vernacular_json"]
        if "vernacular_json" in target_row.keys()  # noqa: SIM118
        else None
    )
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
        g_row = conn.execute(
            "SELECT vernacular_da, vernacular_en, vernacular_json FROM higher_ranks WHERE rank_name = ?",
            (target_genus,),
        ).fetchone()
        if g_row:
            for v_col in [g_row["vernacular_da"], g_row["vernacular_en"]]:
                if v_col:
                    for part in v_col.split("|"):
                        np = normalize_name(part)
                        if np and np not in genus_names_clean:
                            genus_names_clean.append(np)
                        for suf in ("slægten", "familien", "ordenen"):
                            if np.endswith(suf) and len(np) > len(suf):
                                base_np = np[: -len(suf)].strip()
                                if base_np and base_np not in genus_names_clean:
                                    genus_names_clean.append(base_np)
            if g_row["vernacular_json"]:
                try:
                    g_dict = json.loads(g_row["vernacular_json"])
                    for p_str in g_dict.values():
                        if p_str:
                            for part in p_str.split("|"):
                                np = normalize_name(part)
                                if np and np not in genus_names_clean:
                                    genus_names_clean.append(np)
                                for suf in ("slægten", "familien", "ordenen"):
                                    if np.endswith(suf) and len(np) > len(suf):
                                        base_np = np[: -len(suf)].strip()
                                        if base_np and base_np not in genus_names_clean:
                                            genus_names_clean.append(base_np)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        if input_clean in genus_names_clean:
            g_disp = get_display_name(g_row, lang=lang) if g_row else target_genus
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="GENUS",
                matched_taxon_key=None,
                matched_name=f"{g_disp} ({target_genus})"
                if g_disp != target_genus
                else target_genus,
                similarity_score=1.0,
                is_soft_typo=False,
                feedback_message=f"Correct Genus! ({g_disp} / {target_genus}). Now identify the species.",
            )

    # Direct exact / symmetric check against target family (including scientific name and higher_ranks vernaculars)
    if target_family:
        family_names_clean = [normalize_name(target_family)]
        f_row = conn.execute(
            "SELECT vernacular_da, vernacular_en, vernacular_json FROM higher_ranks WHERE rank_name = ?",
            (target_family,),
        ).fetchone()
        if f_row:
            for v_col in [f_row["vernacular_da"], f_row["vernacular_en"]]:
                if v_col:
                    for part in v_col.split("|"):
                        np = normalize_name(part)
                        if np and np not in family_names_clean:
                            family_names_clean.append(np)
                        for suf in ("slægten", "familien", "ordenen"):
                            if np.endswith(suf) and len(np) > len(suf):
                                base_np = np[: -len(suf)].strip()
                                if base_np and base_np not in family_names_clean:
                                    family_names_clean.append(base_np)
            if f_row["vernacular_json"]:
                try:
                    f_dict = json.loads(f_row["vernacular_json"])
                    for p_str in f_dict.values():
                        if p_str:
                            for part in p_str.split("|"):
                                np = normalize_name(part)
                                if np and np not in family_names_clean:
                                    family_names_clean.append(np)
                                for suf in ("slægten", "familien", "ordenen"):
                                    if np.endswith(suf) and len(np) > len(suf):
                                        base_np = np[: -len(suf)].strip()
                                        if base_np and base_np not in family_names_clean:
                                            family_names_clean.append(base_np)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        if input_clean in family_names_clean:
            f_disp = get_display_name(f_row, lang=lang) if f_row else target_family
            return ValidationResult(
                user_input=user_input,
                is_correct=True,
                matched_rank="FAMILY",
                matched_taxon_key=None,
                matched_name=f"{f_disp} ({target_family})"
                if f_disp != target_family
                else target_family,
                similarity_score=1.0,
                is_soft_typo=False,
                feedback_message=f"Correct Family! ({f_disp} / {target_family}). Now refine to Genus or Species.",
            )

    # Check fuzzy typo match against target names
    all_target_variants = [target_canonical, target_sci]
    if target_da:
        all_target_variants.extend(
            [p.strip() for p in target_da.split("|") if p.strip()]
        )
    if target_en:
        all_target_variants.extend(
            [p.strip() for p in target_en.split("|") if p.strip()]
        )

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

    # Identify if user entered a real Genus or Family taxon name
    # 1. Check Genus match
    g_match = conn.execute(
        """SELECT DISTINCT t.genus, h.vernacular_da, h.vernacular_en, h.vernacular_json 
           FROM taxa t LEFT JOIN higher_ranks h ON h.rank_name = t.genus
           WHERE LOWER(t.genus) = :raw 
              OR LOWER(h.vernacular_da) = :raw
              OR LOWER(h.vernacular_en) = :raw
              OR LOWER(h.vernacular_da) LIKE :pipe_prefix
              OR LOWER(h.vernacular_da) LIKE :pipe_suffix
              OR LOWER(h.vernacular_da) LIKE :pipe_mid
           LIMIT 1""",
        {
            "raw": input_lower,
            "pipe_prefix": f"{input_lower}|%",
            "pipe_suffix": f"%|{input_lower}",
            "pipe_mid": f"%|{input_lower}|%",
        },
    ).fetchone()

    if g_match and g_match["genus"]:
        g_name = g_match["genus"]
        g_disp = get_display_name(g_match, lang=lang)
        g_label = (
            f"📁 Genus: {g_disp} ({g_name})"
            if g_disp and g_disp != g_name and g_disp != "Unknown Species"
            else f"📁 Genus: {g_name}"
        )
        sample_sp = conn.execute(
            "SELECT taxon_key FROM taxa WHERE genus = ? AND taxon_key IS NOT NULL LIMIT 1",
            (g_name,),
        ).fetchone()
        sample_key = sample_sp["taxon_key"] if sample_sp else None
        return ValidationResult(
            user_input=user_input,
            is_correct=False,
            matched_rank="GENUS",
            matched_taxon_key=sample_key,
            matched_name=g_label,
            similarity_score=0.0,
            is_soft_typo=False,
            feedback_message=f"Incorrect. Target species was {get_display_name(target_row)} ({target_row['canonical_name']}).",
        )

    # 2. Check Family match
    f_match = conn.execute(
        """SELECT DISTINCT t.family, h.vernacular_da, h.vernacular_en, h.vernacular_json 
           FROM taxa t LEFT JOIN higher_ranks h ON h.rank_name = t.family
           WHERE LOWER(t.family) = :raw 
              OR LOWER(h.vernacular_da) = :raw
              OR LOWER(h.vernacular_en) = :raw
              OR LOWER(h.vernacular_da) LIKE :pipe_prefix
              OR LOWER(h.vernacular_da) LIKE :pipe_suffix
              OR LOWER(h.vernacular_da) LIKE :pipe_mid
           LIMIT 1""",
        {
            "raw": input_lower,
            "pipe_prefix": f"{input_lower}|%",
            "pipe_suffix": f"%|{input_lower}",
            "pipe_mid": f"%|{input_lower}|%",
        },
    ).fetchone()

    if f_match and f_match["family"]:
        f_name = f_match["family"]
        f_disp = get_display_name(f_match, lang=lang)
        f_label = (
            f"🏛️ Family: {f_disp} ({f_name})"
            if f_disp and f_disp != f_name and f_disp != "Unknown Species"
            else f"🏛️ Family: {f_name}"
        )
        sample_sp = conn.execute(
            "SELECT taxon_key FROM taxa WHERE family = ? AND taxon_key IS NOT NULL LIMIT 1",
            (f_name,),
        ).fetchone()
        sample_key = sample_sp["taxon_key"] if sample_sp else None
        return ValidationResult(
            user_input=user_input,
            is_correct=False,
            matched_rank="FAMILY",
            matched_taxon_key=sample_key,
            matched_name=f_label,
            similarity_score=0.0,
            is_soft_typo=False,
            feedback_message=f"Incorrect. Target species was {get_display_name(target_row)} ({target_row['canonical_name']}).",
        )

    # 3. Species match fallback
    guessed_cursor = conn.execute(
        """
        SELECT taxon_key, canonical_name, genus, family, order_name, vernacular_da, vernacular_en, vernacular_json, scientific_name FROM taxa
        WHERE LOWER(canonical_name) = :raw
           OR LOWER(vernacular_da) = :raw
           OR LOWER(vernacular_en) = :raw
           OR LOWER(scientific_name) = :raw
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
            "json_pat": f'%"{input_lower}"%',
            "clean_pipe_prefix": f"{input_clean}|%",
            "clean_pipe_suffix": f"%|{input_clean}",
            "clean_pipe_mid": f"%|{input_clean}|%",
        },
    )
    guessed_row = guessed_cursor.fetchone()

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

    sp_disp = get_display_name(guessed_row, lang=lang)
    sp_label = (
        f"{sp_disp} ({guessed_row['canonical_name']})"
        if sp_disp != guessed_row["canonical_name"]
        else guessed_row["canonical_name"]
    )

    return ValidationResult(
        user_input=user_input,
        is_correct=False,
        matched_rank="SPECIES",
        matched_taxon_key=guessed_row["taxon_key"],
        matched_name=sp_label,
        similarity_score=0.0,
        is_soft_typo=False,
        feedback_message=f"Incorrect. Target species was {get_display_name(target_row)} ({target_row['canonical_name']}).",
    )
