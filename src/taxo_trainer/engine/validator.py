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
    matched_taxon_key: str | int | None
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
    return "".join(s.casefold().replace("-", "").split())


def word_distance(query: str, name: str) -> int:
    """Sum word edit costs, ignoring word order and counting unmatched words.

    Word boundaries cannot be used to hide missing letters. Hyphens are treated
    as spaces, and reordered abbreviated names receive the same score.
    """
    def distance(left, right, substitution, size):
        previous = [0]
        for item in right:
            previous.append(previous[-1] + size(item))
        for a in left:
            current = [previous[0] + size(a)]
            for j, b in enumerate(right):
                current.append(min(current[-1] + size(b),
                                   previous[j + 1] + size(a),
                                   previous[j] + substitution(a, b)))
            previous = current
        return previous[-1]

    def letters(a, b):
        return distance(a, b, lambda x, y: int(x != y), lambda _: 1)

    def words(value):
        return sorted(value.casefold().replace("-", " ").replace("/", " ").split())

    return distance(words(query), words(name), letters, len)


def is_multiword_prefix(name: str | None, q_words: list[str]) -> bool:
    """Check if all tokens in q_words match distinct words in target name as prefixes.

    For example, q_words=['alm', 'fred'] matches name='Almindelig Fredløs'.
    """
    if not name or not q_words:
        return False
    for part in str(name).split("|"):
        p_l = part.strip().lower()
        if not p_l:
            continue
        for suf in (
            "-slægten",
            " slægten",
            "-familien",
            " familien",
            "-ordenen",
            " ordenen",
        ):
            if p_l.endswith(suf):
                p_l = p_l[: -len(suf)].strip()

        target_words = [
            w for w in p_l.replace("-", " ").replace("/", " ").split() if w
        ]
        if not target_words:
            continue

        used_indices = set()
        matched_all = True
        for qw in q_words:
            found = False
            for idx, tw in enumerate(target_words):
                if idx not in used_indices and tw.startswith(qw):
                    used_indices.add(idx)
                    found = True
                    break
            if not found:
                matched_all = False
                break
        if matched_all:
            return True
    return False


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

    Prioritizes exact aliases at every rank, then the lowest unambiguous rank.
    Remaining matches use combined word Levenshtein distance across local aliases.
    If parent rank constraints are passed, suggestions are strictly scoped to valid sub-taxa.

    Args:
        conn: SQLite connection to app_data.db.
        query: User typed search string.
        limit: Max autocomplete suggestions.
        lang: Preferred language ("da", "en", etc.).
        parent_genus: Optional GBIF genus ID constraining species suggestions.
        parent_family: Optional GBIF family ID constraining genus/species suggestions.
        parent_order: Optional GBIF order ID constraining lower-rank suggestions.
        min_count: Minimum occurrence count cutoff threshold.

    Returns:
        List[Dict[str, str]]: List of suggestion objects containing label, value, rank, taxon_key.
    """
    if not query or len(query.strip()) < 2:
        return []

    q_strip = query.strip().casefold()
    q_clean = normalize_name(query)
    q_words = [w for w in q_strip.replace("-", " ").replace("/", " ").split() if w]

    conn.create_function("normalize_taxon_name", 1, normalize_name, deterministic=True)
    sub_pat = f"%{q_strip}%"
    clean_sub_pat = f"%{q_clean}%"

    p_gen = (
        str(parent_genus).strip() if parent_genus and str(parent_genus).strip() else None
    )
    p_fam = (
        str(parent_family).strip()
        if parent_family and str(parent_family).strip()
        else None
    )
    p_ord = (
        str(parent_order).strip() if parent_order and str(parent_order).strip() else None
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
    ) -> tuple[int, int, int]:
        aliases = [part.strip() for value in [canon, *primary_vernaculars, *secondary_names]
                   if value for part in str(value).split("|") if part.strip()]
        alias_distance = min((word_distance(query, alias) for alias in aliases), default=0)
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
                    return 0, rw, alias_distance
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
                            return 0, rw, alias_distance

        # 2. Exact match on secondary names
        for n in secondary_names:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if p_l == q_strip or p_c == q_clean:
                    return 1, rw, alias_distance

        # 3. Title/Full-name prefix match or Multi-word per-word prefix match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if is_title_prefix(n, q_strip, q_clean):
                return 2, rw, alias_distance
            if len(q_words) > 1 and is_multiword_prefix(n, q_words):
                return 2, rw, alias_distance

        # 4. Title/Full-name prefix match or Multi-word per-word prefix match on secondary names
        for n in secondary_names:
            if is_title_prefix(n, q_strip, q_clean):
                return 3, rw, alias_distance
            if len(q_words) > 1 and is_multiword_prefix(n, q_words):
                return 3, rw, alias_distance

        # 5. Subword prefix match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if is_word_prefix(n, q_strip, q_clean):
                return 4, rw, alias_distance

        # 6. Subword prefix match on secondary names
        for n in secondary_names:
            if is_word_prefix(n, q_strip, q_clean):
                return 5, rw, alias_distance

        # 7. Substring match on canonical or primary vernaculars
        for n in [canon] + primary_vernaculars:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if q_strip in p_l or q_clean in p_c:
                    return 6, rw, alias_distance

        # 8. Substring match on secondary names
        for n in secondary_names:
            if not n:
                continue
            for p in str(n).split("|"):
                p_l = p.strip().lower()
                p_c = normalize_name(p)
                if q_strip in p_l or q_clean in p_c:
                    return 7, rw, alias_distance

        return 8, 4, alias_distance

    # Build SQL queries (handling multi-word AND conditions when len(q_words) > 1)
    sp_where_extra = ""
    if p_gen:
        sp_where_extra = " AND genus_key = :p_gen"
    elif p_fam:
        sp_where_extra = " AND family_key = :p_fam"
    elif p_ord:
        sp_where_extra = " AND order_key = :p_ord"

    g_where_extra = ""
    if p_fam:
        g_where_extra = " AND t.family_key = :p_fam"
    elif p_ord:
        g_where_extra = " AND t.order_key = :p_ord"

    f_where_extra = ""
    if p_ord:
        f_where_extra = " AND t.order_key = :p_ord"

    if len(q_words) > 1:
        sp_conds = []
        g_conds = []
        f_conds = []
        multi_params = {
            "min_count": params["min_count"],
            "lang_code": lang,
            "p_gen": p_gen or "",
            "p_fam": p_fam or "",
            "p_ord": p_ord or "",
        }
        for idx, w in enumerate(q_words):
            wk = f"w_{idx}"
            multi_params[wk] = f"%{w}%"
            sp_conds.append(
                f"(LOWER(canonical_name) LIKE :{wk} OR LOWER(vernacular_da) LIKE :{wk} OR LOWER(vernacular_en) LIKE :{wk} OR LOWER(scientific_name) LIKE :{wk} OR LOWER(json_extract(vernacular_json, '$.' || :lang_code)) LIKE :{wk})"
            )
            g_conds.append(
                f"(LOWER(t.genus) LIKE :{wk} OR LOWER(h.vernacular_da) LIKE :{wk} OR LOWER(h.vernacular_en) LIKE :{wk} OR LOWER(json_extract(h.vernacular_json, '$.' || :lang_code)) LIKE :{wk})"
            )
            f_conds.append(
                f"(LOWER(t.family) LIKE :{wk} OR LOWER(h.vernacular_da) LIKE :{wk} OR LOWER(h.vernacular_en) LIKE :{wk} OR LOWER(json_extract(h.vernacular_json, '$.' || :lang_code)) LIKE :{wk})"
            )

        sp_sql = f"""
            SELECT taxon_key, canonical_name, scientific_name, rank, family, genus, vernacular_da, vernacular_en, vernacular_json
            FROM taxa
            WHERE occurrence_count >= :min_count
              AND ({" AND ".join(sp_conds)}){sp_where_extra}
        """
        g_sql = f"""
            SELECT DISTINCT t.genus_key AS taxon_key, t.genus, h.vernacular_da, h.vernacular_en, h.vernacular_json
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.taxon_key = t.genus_key
            WHERE t.genus_key IS NOT NULL AND t.genus IS NOT NULL AND t.genus != '' AND t.occurrence_count >= :min_count{g_where_extra}
              AND ({" AND ".join(g_conds)})
        """
        f_sql = f"""
            SELECT DISTINCT t.family_key AS taxon_key, t.family, h.vernacular_da, h.vernacular_en, h.vernacular_json
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.taxon_key = t.family_key
            WHERE t.family_key IS NOT NULL AND t.family IS NOT NULL AND t.family != '' AND t.occurrence_count >= :min_count{f_where_extra}
              AND ({" AND ".join(f_conds)})
        """
        exec_params = multi_params
    else:
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
        g_sql = f"""
            SELECT DISTINCT t.genus_key AS taxon_key, t.genus, h.vernacular_da, h.vernacular_en, h.vernacular_json
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.taxon_key = t.genus_key
            WHERE t.genus_key IS NOT NULL AND t.genus IS NOT NULL AND t.genus != '' AND t.occurrence_count >= :min_count{g_where_extra}
              AND (LOWER(t.genus) LIKE :sub
                OR LOWER(h.vernacular_da) LIKE :sub
                OR LOWER(h.vernacular_en) LIKE :sub
                OR json_extract(h.vernacular_json, '$.' || :lang_code) LIKE :sub
                OR REPLACE(REPLACE(LOWER(t.genus), '-', ''), ' ', '') LIKE :clean_sub
                OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_sub)
        """
        f_sql = f"""
            SELECT DISTINCT t.family_key AS taxon_key, t.family, h.vernacular_da, h.vernacular_en, h.vernacular_json
            FROM taxa t
            LEFT JOIN higher_ranks h ON h.taxon_key = t.family_key
            WHERE t.family_key IS NOT NULL AND t.family IS NOT NULL AND t.family != '' AND t.occurrence_count >= :min_count{f_where_extra}
              AND (LOWER(t.family) LIKE :sub
                OR LOWER(h.vernacular_da) LIKE :sub
                OR LOWER(h.vernacular_en) LIKE :sub
                OR json_extract(h.vernacular_json, '$.' || :lang_code) LIKE :sub
                OR REPLACE(REPLACE(LOWER(t.family), '-', ''), ' ', '') LIKE :clean_sub
                OR REPLACE(REPLACE(LOWER(h.vernacular_da), '-', ''), ' ', '') LIKE :clean_sub)
        """
        exec_params = params

    exec_params["exact_query"] = q_clean
    def exact_condition(columns):
        return " OR ".join(f"normalize_taxon_name({column}) = :exact_query" for column in columns)

    sp_sql = sp_sql.replace("AND (", "AND (" + exact_condition([
        "canonical_name", "vernacular_da", "vernacular_en",
        "json_extract(vernacular_json, '$.' || :lang_code)",
    ]) + " OR ", 1)
    for rank, sql in (("genus", g_sql), ("family", f_sql)):
        sql = sql.replace("AND (", "AND (" + exact_condition([
            f"t.{rank}", "h.vernacular_da", "h.vernacular_en",
            "json_extract(h.vernacular_json, '$.' || :lang_code)",
        ]) + " OR ", 1)
        if rank == "genus":
            g_sql = sql
        else:
            f_sql = sql

    # 1. Species matches
    for row in conn.execute(sp_sql, exec_params).fetchall():
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
        if row["taxon_key"] not in seen_values:
            seen_values.add(row["taxon_key"])
            display = get_display_name(row, lang=lang)
            primary_v = (
                [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
            )
            v_json_raw = row["vernacular_json"]
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
            prio, rw, alias_distance = calc_priority_and_rank_weight(canon, r_str, primary_v, secondary_v)
            if prio >= 8:
                continue
            label = f"{display} ({canon})" if display != canon else canon
            candidates.append(
                {
                    "label": label,
                    "value": str(row["taxon_key"]),
                    "display_name": display,
                    "canonical_name": canon,
                    "rank": r_str,
                    "taxon_key": row["taxon_key"],
                    "priority": prio,
                    "distance": alias_distance,
                    "rank_order": rw,
                }
            )

    # 2. Genus matches (only if genus has not already been guessed)
    if not p_gen:
        for row in conn.execute(g_sql, exec_params).fetchall():
            g_name = row["genus"]
            if g_name and row["taxon_key"] not in seen_values:
                seen_values.add(row["taxon_key"])
                g_disp = get_display_name(row, lang=lang)
                primary_v = (
                    [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
                )
                v_json_raw = (
                    row["vernacular_json"]
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
                prio, rw, alias_distance = calc_priority_and_rank_weight(g_name, "GENUS", primary_v, secondary_v)
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
                        "value": str(row["taxon_key"]),
                        "display_name": g_disp,
                        "canonical_name": g_name,
                        "rank": "GENUS",
                        "taxon_key": row["taxon_key"],
                        "priority": prio,
                    "distance": alias_distance,
                        "rank_order": rw,
                    }
                )

    # 3. Family matches (only if family or genus has not already been guessed)
    if not p_gen and not p_fam:
        for row in conn.execute(f_sql, exec_params).fetchall():
            f_name = row["family"]
            if f_name and row["taxon_key"] not in seen_values:
                seen_values.add(row["taxon_key"])
                f_disp = get_display_name(row, lang=lang)
                primary_v = (
                    [row["vernacular_da"]] if lang == "da" else [row["vernacular_en"]]
                )
                v_json_raw = (
                    row["vernacular_json"]
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
                prio, rw, alias_distance = calc_priority_and_rank_weight(f_name, "FAMILY", primary_v, secondary_v)
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
                        "value": str(row["taxon_key"]),
                        "display_name": f_disp,
                        "canonical_name": f_name,
                        "rank": "FAMILY",
                        "taxon_key": row["taxon_key"],
                        "priority": prio,
                    "distance": alias_distance,
                        "rank_order": rw,
                    }
                )

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
            norm_disp = str(c["taxon_key"])
            rank_distinct_names.setdefault(r_grp, set()).add(norm_disp)

    def get_sort_key(c: dict[str, Any]) -> tuple:
        r_upper = (c["rank"] or "").upper()
        r_grp = (
            "SPECIES"
            if r_upper in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM")
            else r_upper
        )
        # 1. Exact aliases at every rank always come first
        is_exact = 0 if c["priority"] <= 1 else 1
        # 2. Unambiguous rank level first (only 1 distinct display name matched at this rank level)
        distinct_cnt = len(rank_distinct_names.get(r_grp, set()))
        is_unambiguous = 0 if distinct_cnt == 1 else 1

        return (
            is_exact,
            c["priority"] if is_exact == 0 else 0,
            c["rank_order"] if is_exact == 0 else 0,
            is_unambiguous,
            c["rank_order"] if is_unambiguous == 0 else 0,
            c["distance"],
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


def _aliases(row: dict) -> list[str]:
    """Return local input aliases attached to a taxon ID, never new identities."""
    import re

    names = [row.get("canonical_name"), row.get("scientific_name"), row.get("rank_name"),
             row.get("vernacular_da"), row.get("vernacular_en")]
    try:
        translations = json.loads(row.get("vernacular_json") or "{}")
        if isinstance(translations, dict):
            names.extend(v for v in translations.values() if isinstance(v, str))
    except (ValueError, TypeError):
        pass
    names.extend(re.findall(r"\((.*?)\)", row.get("scientific_name") or ""))
    aliases = [part.strip() for name in names if name for part in name.split("|") if part.strip()]
    if row.get("rank_level") in ("GENUS", "FAMILY", "ORDER"):
        for name in list(aliases):
            for suffix in ("-slægten", " slægten", "-familien", " familien", "-ordenen", " ordenen"):
                if name.lower().endswith(suffix):
                    aliases.append(name[:-len(suffix)])
    return aliases


def validate_user_guess(conn, user_input, target_taxon_key, typo_threshold=0.90, lang="da", min_count=1) -> ValidationResult:
    """Resolve local input aliases or a selected GBIF ID and compare IDs only.

    Ambiguous aliases require a selection. Higher-rank guesses carry their own
    IDs, never the ID of an arbitrary example species.
    """
    raw = user_input.strip()
    target = conn.execute("SELECT * FROM taxa WHERE taxon_key=?", (str(target_taxon_key),)).fetchone()

    def result(row=None, correct=False, similarity=0.0, soft=False, message=""):
        rank = (row.get("rank_level") or row.get("rank") or "SPECIES") if row else None
        if rank in ("SUBSPECIES", "VARIETY", "FORM"):
            rank = "SPECIES"
        return ValidationResult(user_input, correct, rank, row["taxon_key"] if row else None,
                                get_display_name(row, lang) if row else "", similarity, soft, message)

    if not raw or not target:
        return result(message="Please enter a species, genus, or family name." if not raw else "Target species record missing.")
    target = dict(target)
    target_ids = {"SPECIES": str(target_taxon_key), "GENUS": target.get("genus_key"),
                  "FAMILY": target.get("family_key"), "ORDER": target.get("order_key")}
    ancestors = []
    for rank in ("GENUS", "FAMILY", "ORDER"):
        key = target_ids[rank]
        if not key:
            continue
        row = conn.execute("SELECT * FROM higher_ranks WHERE taxon_key=?", (key,)).fetchone()
        ancestors.append(dict(row) if row else {"taxon_key": key, "rank_level": rank,
            "rank_name": target.get(rank.lower() if rank != "ORDER" else "order_name")})

    selected = conn.execute("SELECT * FROM taxa WHERE taxon_key=?", (raw,)).fetchone()
    if selected is None:
        selected = conn.execute("SELECT * FROM higher_ranks WHERE taxon_key=?", (raw,)).fetchone()
    if selected is None:
        selected = next((r for r in ancestors if str(r["taxon_key"]) == raw), None)
    if selected:
        selected = dict(selected)
    else:
        # SQL autocomplete narrows the set; only local aliases are inspected.
        matches = autocomplete_taxa(conn, raw, limit=100, lang=lang, min_count=min_count)
        candidates = {str(r["taxon_key"]): r for r in [target] + ancestors}
        for match in matches:
            table = "higher_ranks" if match["rank"] in ("GENUS", "FAMILY", "ORDER") else "taxa"
            row = conn.execute(f"SELECT * FROM {table} WHERE taxon_key=?", (match["taxon_key"],)).fetchone()
            if row:
                candidates[str(row["taxon_key"])] = dict(row)
        clean = normalize_name(raw)
        exact = [r for r in candidates.values() if clean in {normalize_name(a) for a in _aliases(r)}]
        species = [r for r in exact if r.get("rank", "") in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM")]
        exact = species or exact
        if len(exact) > 1:
            return result(message="This name refers to more than one taxon. Please select a suggestion.")
        if exact:
            selected = exact[0]
        else:
            for row in [target] + ancestors:
                aliases = _aliases(row)
                if len(raw.split()) > 1 and any(is_multiword_prefix(a, raw.lower().replace("-", " ").split()) for a in aliases):
                    return result(row, True, 1.0, message="Correct identification!")
                similarity = max((check_string_similarity(raw, a) for a in aliases), default=0.0)
                if similarity >= typo_threshold:
                    return result(row, True, similarity, True, "Correct identification! (Soft typo accepted).")
            return result(message=f"Unrecognized taxon name '{user_input}'. Please check spelling or select from suggestions.")
    rank = selected.get("rank_level") or selected.get("rank")
    if rank in ("SUBSPECIES", "VARIETY", "FORM"):
        rank = "SPECIES"
    correct = str(selected["taxon_key"]) == str(target_ids.get(rank))
    return result(selected, correct, 1.0 if correct else 0.0,
                  message=f"Correct {rank.lower()} identification!" if correct else
                  f"Incorrect. Target species was {get_display_name(target, lang)} ({target['canonical_name']}).")
