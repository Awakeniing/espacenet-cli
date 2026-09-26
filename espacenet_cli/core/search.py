"""Search result normalization and multi-page collection."""

import re

from espacenet_cli.core.errors import CliError
from espacenet_cli.core.text import strip_html


def _first(fields, key):
    value = (fields or {}).get(key)
    return value[0] if isinstance(value, list) and value else None


def _join(fields, key, sep="; "):
    value = (fields or {}).get(key)
    return sep.join(value) if isinstance(value, list) else ""


def _dedupe_join(values, sep="; "):
    seen = set()
    out = []
    for v in values or []:
        key = str(v).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(v).strip())
    return sep.join(out)


def normalize_hit_publication(hit, family_info=None):
    family_info = family_info or {}
    fields = hit.get("fields") or {}
    pn = _first(fields, "publications.pn_docdb") or ""
    title = ""
    for lang in ("en", "de", "fr", "es"):
        title = strip_html(_first(fields, f"publications.ti_{lang}") or "")
        if title:
            break
    pd = fields.get("publications.pd") if isinstance(fields.get("publications.pd"), list) else []
    kind_match = re.search(r"([A-Z]\d+)$", pn)
    cc_match = re.match(r"^([A-Z]{2})", pn)
    return {
        "publicationNumber": pn,
        "countryCode": cc_match.group(1) if cc_match else "",
        "kindCode": kind_match.group(1) if kind_match else "",
        "title": title,
        "abstract": strip_html(_first(fields, "publications.abs_en") or ""),
        "publicationDate": sorted(pd)[0] if pd else "",
        "publicationDates": sorted(pd),
        "filingDate": _first(fields, "publications.app_fdate.untouched") or "",
        "applicants": _dedupe_join(fields.get("publications.pa_patents")),
        "inventors": _dedupe_join(fields.get("publications.in_patents")),
        "ipc": _dedupe_join(fields.get("publications.ipc_icai")),
        "cpc": _dedupe_join(fields.get("publications.ci_cpci")),
        "priority": _join(fields, "publications.pr_docdb"),
        "familyId": family_info.get("familyId", ""),
        "familySize": family_info.get("familySize", 0),
        "score": hit.get("score") if hit.get("score") is not None else None,
    }


def _short_row(pn, info, family_info):
    dates = sorted(info.get("pd") and [d for v in info["pd"].values() for d in (v if isinstance(v, list) else [v])] or [])
    kind_match = re.search(r"([A-Z]\d+)$", pn)
    cc_match = re.match(r"^([A-Z]{2})", pn)
    pa = ""
    if info.get("pa_unstd_patents"):
        first = next(iter(info["pa_unstd_patents"].values()))
        pa = (first[0] if isinstance(first, list) else first) or ""
    inventors = ""
    if info.get("in_unstd_patents"):
        flat = [d for v in info["in_unstd_patents"].values() for d in (v if isinstance(v, list) else [v])]
        inventors = "; ".join(str(x) for x in flat)
    return {
        "publicationNumber": pn,
        "countryCode": cc_match.group(1) if cc_match else "",
        "kindCode": kind_match.group(1) if kind_match else "",
        "title": "", "abstract": "",
        "publicationDate": dates[0] if dates else "",
        "publicationDates": dates,
        "filingDate": "", "applicants": pa, "inventors": inventors,
        "ipc": "", "cpc": "", "priority": "",
        "familyId": family_info["familyId"], "familySize": family_info["familySize"], "score": None,
    }


def normalize_search_payload(payload, query="", from_=0, size=20):
    """Each hit is a family (hit.hits[] = member publications)."""
    hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
    results = []
    seen = set()

    def push(row):
        if not row or not row.get("publicationNumber"):
            return
        key = f"{row.get('familyId')}|{row['publicationNumber']}"
        if key in seen:
            return
        seen.add(key)
        results.append(row)

    for hit in hits:
        family_info = {"familyId": hit.get("familyNumber") or "", "familySize": hit.get("publicationsCount") or 0}
        members = hit.get("hits") if isinstance(hit.get("hits"), list) else []
        if members:
            for member in members:
                push(normalize_hit_publication(member, family_info))
            biblio_map = ((hit.get("fields") or {}).get("biblio") or [{}])[0] or {}
            for info in biblio_map.values():
                pn = None
                if info and info.get("pn_docdb"):
                    flat = [d for v in info["pn_docdb"].values() for d in (v if isinstance(v, list) else [v])]
                    pn = str(flat[0]) if flat else None
                if not pn or f"{family_info['familyId']}|{pn}" in seen:
                    continue
                seen.add(f"{family_info['familyId']}|{pn}")
                results.append(_short_row(pn, info, family_info))
        else:
            push(normalize_hit_publication(hit, family_info))

    return {
        "query": query,
        "totalFamilies": int(payload.get("familiesNumber") or 0),
        "totalPublications": int(payload.get("publicationsNumber") or 0),
        "from": from_,
        "size": size,
        "resultCount": len(results),
        "results": results,
        "search-engine-took-ms": payload.get("search-engine-took"),
    }


def run_search(backend, query, page=1, size=20, fetch_all=False, limit=2000, on_progress=lambda m: None):
    if not query or not str(query).strip():
        raise CliError("INVALID_ARGUMENT", "检索式不能为空。", exit_code=2)
    safe_size = min(max(int(size or 20), 1), 100)
    if fetch_all and safe_size < 50:
        # Bulk pulls take big pages: fewer requests = less search budget burned
        # (each page is one throttled search) without changing the result set.
        safe_size = 50
    from_ = (max(int(page or 1), 1) - 1) * safe_size
    normalized = normalize_search_payload(
        backend.search_raw(query, from_=from_, size=safe_size), query=query, from_=from_, size=safe_size)

    if not fetch_all:
        return normalized

    total = min(normalized["totalPublications"], int(limit or 2000))
    collected = list(normalized["results"])
    on_progress(f"已获取 {len(collected)}/{total} 条")
    while len(collected) < total and from_ + safe_size < min(normalized["totalFamilies"] * 3 + 10, 100000):
        from_ += safe_size
        payload = backend.search_raw(query, from_=from_, size=safe_size)
        nxt = normalize_search_payload(payload, query=query, from_=from_, size=safe_size)
        if not nxt["results"]:
            break
        known = {f"{r['familyId']}|{r['publicationNumber']}" for r in collected}
        fresh = 0
        for row in nxt["results"]:
            key = f"{row['familyId']}|{row['publicationNumber']}"
            if key not in known:
                known.add(key)
                collected.append(row)
                fresh += 1
        on_progress(f"已获取 {len(collected)}/{total} 条")
        if not fresh:
            break
        import time
        time.sleep(1.2)  # measured EPO/Cloudflare search budget refills slowly
    truncated = False
    if len(collected) > total:
        collected = collected[:total]
        truncated = True
    return {
        "query": query,
        "totalFamilies": normalized["totalFamilies"],
        "totalPublications": normalized["totalPublications"],
        "from": 0,
        "size": safe_size,
        "resultCount": len(collected),
        "results": collected,
        "truncated": truncated,
    }
