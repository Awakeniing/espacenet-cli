"""Per-publication data: detail / claims / description / family / legal.

Service endpoints (restored from the Espacenet SPA, pn as cc/num/kc):
  claims-tree:  /3.2/rest-services/claims-tree/family/{fam}/publication/{cc}/{num}/{kc}?locale=en
  highlight:    /3.2/rest-services/highlight/family/{fam}/publication/{cc}/{num}/{kc}?fields=publications.{f}&q={cql}
  family:       /3.2/rest-services/family/publication/{cc}/{num}/{kc}.json?buildLinks
  legal:        /3.2/rest-services/legal/publication/{cc}/{num}/{kc}.json
The anonymous highlight service rejects EP documents → fall back to an English
family member (WO/US preferred) and label the source in `textFrom`.
"""

import re
import time

from espacenet_cli.core.errors import CliError
from espacenet_cli.core.search import normalize_search_payload, run_search
from espacenet_cli.core.text import num_to_date, parse_multipart_text, parse_publication_number, same_publication, split_claims, xml_to_text

FULLTEXT_UNSUPPORTED = {"EP"}
EN_PREFERENCE = ["WO", "US", "GB", "AU", "CA", "IN", "KR", "JP", "CN", "MX", "BR", "ES", "DE", "FR"]

PN_PARTS_RE = re.compile(r"^([A-Z]{2})(\d+)([A-Z]\d?)$")

CACHE_TTL_S = 7 * 24 * 3600.0
CACHE_MAX_ENTRIES = 500


def _cache_file(backend):
    return backend.paths["profile_root"] / "document-cache.json"


def _load_persistent_cache(backend):
    from espacenet_cli.core.session import read_json_or_none

    data = read_json_or_none(_cache_file(backend))
    return data if isinstance(data, dict) else {}


def _save_persistent_cache(backend, cache):
    from espacenet_cli.core.session import locked_save_json

    # prune oldest beyond the cap
    items = sorted(cache.items(), key=lambda kv: kv[1].get("cached_at", 0))
    if len(items) > CACHE_MAX_ENTRIES:
        cache = dict(items[-CACHE_MAX_ENTRIES:])
    locked_save_json(_cache_file(backend), cache)


def resolve_ref(backend, pn_input, on_event=lambda m: None, refresh=False):
    """Resolve a publication number via ONE detail search, memoized.

    Every document command needs the same resolution (pn/cc/num/kc/family), so
    the result is cached in memory and on disk (7-day TTL). A full dossier
    (claims+description+family+legal+pdf on one PN) therefore costs a single
    search instead of one per command — searches are the throttled resource.
    """
    parsed = parse_publication_number(pn_input)
    cache_key = parsed["full"]
    now = time.time()

    if not refresh:
        cached = backend._resolution_cache.get(cache_key)
        if cached:
            return cached
        persistent = _load_persistent_cache(backend)
        entry = persistent.get(cache_key)
        if entry and now - float(entry.get("cached_at", 0)) < CACHE_TTL_S:
            on_event(f"命中本地缓存 {cache_key}（{int((now - entry['cached_at']) / 86400)} 天前解析）")
            backend._resolution_cache[cache_key] = entry["ref"]
            return entry["ref"]

    detail = run_detail(backend, pn_input, on_event=on_event)
    m = PN_PARTS_RE.match(str(detail["publicationNumber"]).upper())
    ref = {
        "requested": str(pn_input).upper(),
        "pn": detail["publicationNumber"],
        "cc": m.group(1) if m else "",
        "num": m.group(2) if m else "",
        "kc": m.group(3) if m else "",
        "pn_slash": f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else "",
        "family_id": detail.get("familyId", ""),
        "detail": detail,
    }
    backend._resolution_cache[cache_key] = ref
    # alias: kind-code-less lookups should hit too
    backend._resolution_cache[parsed["stem"]] = ref
    try:
        persistent = _load_persistent_cache(backend)
        persistent[cache_key] = {"cached_at": now, "ref": {**ref, "detail": None}}
        persistent[parsed["stem"]] = persistent[cache_key]
        _save_persistent_cache(backend, persistent)
    except Exception:
        pass  # cache is an optimization, never a failure
    return ref


def run_detail(backend, pn_input, on_event=lambda m: None):
    """Biblio data for one publication, resolved through the search service."""
    parsed = parse_publication_number(pn_input)
    attempts = ([f"PN={parsed['full']}", f"PN={parsed['stem']}", parsed["full"]]
                if parsed["kind"] else [f"PN={parsed['full']}", parsed["full"]])
    for query in attempts:
        on_event(f"查询 {query} …")
        payload = normalize_search_payload(backend.search_raw(query, from_=0, size=30), query=query)
        rows = payload["results"]
        exact = next((r for r in rows if same_publication(r["publicationNumber"], parsed["full"])
                      and (r["kindCode"] == parsed["kind"] if parsed["kind"] else True)), None)
        exact = exact or next((r for r in rows if same_publication(r["publicationNumber"], parsed["full"])), None)
        if exact:
            family_members = list(dict.fromkeys(
                r["publicationNumber"] for r in rows if r.get("familyId") == exact.get("familyId")))
            return {
                "publicationNumber": exact["publicationNumber"],
                "requested": parsed["full"],
                "title": exact["title"],
                "abstract": exact["abstract"],
                "applicants": exact["applicants"],
                "inventors": exact["inventors"],
                "publicationDate": exact["publicationDate"],
                "filingDate": exact["filingDate"],
                "priority": exact["priority"],
                "ipc": exact["ipc"],
                "cpc": exact["cpc"],
                "familyId": exact["familyId"],
                "familySize": exact["familySize"],
                "familyMembers": family_members,
                "score": exact["score"],
            }
    raise CliError("NOT_FOUND", f"Espacenet 中未找到公开号 {parsed['full']}。",
                   action="确认公开号/申请号是否正确；kind code 可省略（如 EP2600908）。")


def _require_family_id(resolved):
    if not resolved["family_id"]:
        raise CliError("NOT_FOUND", f"未能确定 {resolved['pn']} 的同族号，无法调用该服务。",
                       action=f"先运行 `espacenet detail {resolved['pn']}` 确认该公开号存在。")
    return resolved["family_id"]


def _fetch_family_json(backend, resolved, on_event):
    fam = _require_family_id(resolved)
    path = f"/3.2/rest-services/family/publication/{resolved['pn_slash']}.json?buildLinks"
    on_event(f"GET {path}")
    response = backend.fetch_json(path)
    if not response["json"]:
        return None
    return (response["json"].get("world-patent-data") or {}).get("patent-family")


def _extract_doc_id(doc):
    ref = doc.get("publication-reference")
    if isinstance(ref, list):
        ref = ref[0] if ref else None
    doc_id = (ref or {}).get("document-id") if isinstance(ref, dict) else None
    doc_id = doc_id if doc_id is not None else ref
    doc_id = doc_id or {}

    def val(key):
        v = doc_id.get(key)
        if isinstance(v, list):
            v = v[0] if v else None
        return v

    return {
        "cc": str(val("country") or "").upper(),
        "num": str(val("doc-number") or ""),
        "kc": str(val("kind") or "").upper(),
        "date": num_to_date(val("date")),
    }


def _english_family_candidates(backend, resolved, on_event):
    """Family members with English fulltext candidates, preference-ordered."""
    try:
        family = _fetch_family_json(backend, resolved, on_event)
    except CliError:
        return []
    members = []
    for doc in (family or {}).get("patent-document") or []:
        parsed = _extract_doc_id(doc)
        if parsed["cc"] and parsed["num"]:
            members.append(parsed)
    return [
        {**m, "pn_slash": f"{m['cc']}/{m['num']}/{m['kc']}", "pn": f"{m['cc']}{m['num']}{m['kc']}"}
        for m in sorted(
            (m for m in members
             if m["cc"] not in FULLTEXT_UNSUPPORTED and f"{m['cc']}{m['num']}{m['kc']}" != resolved["pn"]),
            key=lambda m: EN_PREFERENCE.index(m["cc"]) if m["cc"] in EN_PREFERENCE else 99,
        )
    ]


def _fetch_highlight_field(backend, family_id, pn_slash, field, on_event):
    from urllib.parse import quote

    path = f"/3.2/rest-services/highlight/family/{family_id}/publication/{pn_slash}?fields=publications.{field}&q={quote('the')}"
    on_event(f"GET {path}")
    response = backend.fetch(path, headers={"accept": "*/*"})
    text = response.get("text") or ""
    if response.get("status") != 200 or text.startswith("<?xml") or re.search(r"<fault", text[:400], re.I):
        return None
    return xml_to_text(parse_multipart_text(text))


def run_description(backend, pn_input, raw=False, on_event=lambda m: None, refresh=False):
    resolved = resolve_ref(backend, pn_input, on_event, refresh=refresh)
    fam = _require_family_id(resolved)
    attempts = [{"pn_slash": resolved["pn_slash"], "pn": resolved["pn"]}]
    if resolved["cc"] in FULLTEXT_UNSUPPORTED:
        attempts += _english_family_candidates(backend, resolved, on_event)
    for attempt in attempts:
        text = _fetch_highlight_field(backend, fam, attempt["pn_slash"], "desc_en", on_event)
        if text and len(text) > 200:
            return {
                "publicationNumber": resolved["pn"],
                "textFrom": attempt["pn"],
                "description": text,
                **({"note": f"{resolved['pn']} 的 EP 全文服务不可用，已返回同族成员 {attempt['pn']} 的英文文本（内容可能存在版本差异）。"}
                   if attempt["pn"] != resolved["pn"] else {}),
            }
    if raw:
        text = None
        try:
            text = _fetch_highlight_field(backend, fam, resolved["pn_slash"], "desc_en", on_event)
        except CliError:
            pass
        if text:
            return {"publicationNumber": resolved["pn"], "raw": text}
    raise CliError("NOT_SUPPORTED", f"未能获取 {resolved['pn']} 的说明书全文。",
                   action=f"Espacenet 对部分文献（尤其 EP）不提供匿名全文接口；可运行 `espacenet open {resolved['pn']}` 在浏览器中查看。")


def run_claims(backend, pn_input, raw=False, on_event=lambda m: None, refresh=False):
    resolved = resolve_ref(backend, pn_input, on_event, refresh=refresh)
    fam = _require_family_id(resolved)

    # 1) claims-tree (works for US/CN/...; returns structured claimsMap)
    ct_path = f"/3.2/rest-services/claims-tree/family/{fam}/publication/{resolved['pn_slash']}?locale=en"
    on_event(f"GET {ct_path}")
    try:
        ct = backend.fetch_json(ct_path)
    except CliError:
        ct = {"json": None, "text": ""}
    claims_map = None
    if isinstance(ct.get("json"), dict):
        claims_map = ct["json"].get("claimsMap") or (ct["json"].get("data") or {}).get("claimsMap")
    if isinstance(claims_map, dict):
        claims = [
            {"number": int(c["id"]) if str(c.get("id", "")).isdigit() else None,
             "text": str(c["text"]).strip()}
            for c in claims_map.values()
            if isinstance(c, dict) and c.get("text")
        ]
        if claims:
            return {
                "publicationNumber": resolved["pn"],
                "textFrom": resolved["pn"],
                "claimCount": len(claims),
                "claims": claims,
            }

    # 2) highlight claims_en; EP falls back to English family members
    attempts = [{"pn_slash": resolved["pn_slash"], "pn": resolved["pn"]}]
    if resolved["cc"] in FULLTEXT_UNSUPPORTED:
        attempts += _english_family_candidates(backend, resolved, on_event)
    for attempt in attempts:
        text = _fetch_highlight_field(backend, fam, attempt["pn_slash"], "claims_en", on_event)
        if text and len(text) > 100:
            return {
                "publicationNumber": resolved["pn"],
                "textFrom": attempt["pn"],
                "claims": split_claims(text),
                **({"note": f"{resolved['pn']} 的权利要求全文服务不可用，已返回同族成员 {attempt['pn']} 的英文文本（内容可能存在版本差异）。"}
                   if attempt["pn"] != resolved["pn"] else {}),
            }

    if raw and ct.get("text"):
        return {"publicationNumber": resolved["pn"], "raw": ct["text"]}
    raise CliError("NOT_SUPPORTED", f"未能获取 {resolved['pn']} 的权利要求文本。",
                   action=f"Espacenet 对部分文献（尤其 EP）不提供匿名全文接口；可运行 `espacenet open {resolved['pn']}` 在浏览器中查看。")


def run_family(backend, pn_input, on_event=lambda m: None, refresh=False):
    resolved = resolve_ref(backend, pn_input, on_event, refresh=refresh)
    family = _fetch_family_json(backend, resolved, on_event)
    members = []
    seen = set()
    for doc in (family or {}).get("patent-document") or []:
        parsed = _extract_doc_id(doc)
        if not parsed["cc"] or not parsed["num"]:
            continue
        pn = f"{parsed['cc']}{parsed['num']}{parsed['kc']}"
        if pn in seen:
            continue
        seen.add(pn)
        members.append({"publicationNumber": pn, "kindCode": parsed["kc"], "date": parsed["date"], "country": parsed["cc"]})
    if not members:
        members = [{"publicationNumber": pn}
                   for pn in (resolved.get("detail") or {}).get("familyMembers", [])]
    if not members:
        raise CliError("NOT_FOUND", f"未获取到 {resolved['pn']} 的同族信息。")
    num_members = (family or {}).get("number-of-members")
    return {
        "publicationNumber": resolved["pn"],
        "familyId": resolved["family_id"],
        "memberCount": num_members if num_members is not None else len(members),
        "truncated": bool((family or {}).get("truncated-family")),
        "members": members,
    }


def run_legal(backend, pn_input, on_event=lambda m: None, refresh=False):
    resolved = resolve_ref(backend, pn_input, on_event, refresh=refresh)
    path = f"/3.2/rest-services/legal/publication/{resolved['pn_slash']}.json"
    on_event(f"GET {path}")
    response = backend.fetch_json(path)
    root = (response.get("json") or {}).get("world-patent-data") or {}
    doc = root.get("patent-document") or {}
    legal_events = (doc.get("legal-events") or {}).get("legal-event")
    raw_events = legal_events if isinstance(legal_events, list) else ([legal_events] if legal_events else [])
    events = []
    for ev in raw_events:
        details = ev.get("event-details") or {}
        desc = details.get("event-description")
        desc_list = desc if isinstance(desc, list) else ([desc] if desc else [])
        chosen = next((d for d in desc_list if isinstance(d, dict) and d.get("lang") == "en"),
                      desc_list[0] if desc_list else {})
        parties = ((details.get("parties") or {}).get("parties-details") or {}).get("party")
        party_list = parties if isinstance(parties, list) else ([parties] if parties else [])
        events.append({
            "date": num_to_date(ev.get("event-date") or ev.get("event-date-effective")),
            "effectiveDate": num_to_date(ev.get("event-date-effective")),
            "code": ev.get("event-code") or "",
            "class": ev.get("event-class-description") or ev.get("event-class") or "",
            "office": ev.get("providing-office") or "",
            "description": (chosen or {}).get("content") or "",
            "text": details.get("text") if isinstance(details.get("text"), str) else "",
            "parties": "; ".join(p.get("name") for p in party_list if isinstance(p, dict) and p.get("name")),
        })
    if not events:
        return {"publicationNumber": resolved["pn"], "events": [],
                "note": "Espacenet 无该文献的结构化法律事件。"}
    return {"publicationNumber": resolved["pn"], "eventCount": len(events), "events": events}
