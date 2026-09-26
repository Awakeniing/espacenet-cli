"""Whole-document PDF download with image-kind fallback."""

from pathlib import Path

from espacenet_cli.core.config import ESPACENET_ORIGIN
from espacenet_cli.core.document import resolve_ref
from espacenet_cli.core.errors import CliError


def _try_download(backend, path, on_event):
    try:
        response = backend.fetch(path, binary=True, headers={"accept": "application/pdf"})
    except CliError as error:
        response = {"status": 0, "error": str(error)}
    ct = (response.get("headers") or {}).get("content-type", "")
    data = response.get("bytes") or b""
    head = data[:5].decode("latin1") if data else ""
    on_event(f"GET {path} → {response.get('status')} {ct} {len(data)}B" if data
             else f"GET {path} → {response.get('status')} {response.get('error', '')}")
    if response.get("status") == 200 and ("pdf" in ct or head.startswith("%PDF")):
        return {"bytes": data, "content_type": ct}
    return None


def _available_image_kinds(backend, resolved, on_event):
    path = f"/3.2/rest-services/images/indexes/pub-ids/entries/{resolved['cc']}/{resolved['num']}"
    on_event(f"GET {path}")
    try:
        response = backend.fetch_json(path)
    except CliError:
        return []
    kinds = []
    for match in (((response.get("json") or {}).get("queries") or [{}])[0].get("result", {}).get("matches") or []):
        kind = ((match or {}).get("pubId") or {}).get("kindCode")
        if kind:
            kinds.append(str(kind).upper())
    return kinds


def run_pdf(backend, pn_input, out_dir=".", on_event=lambda m: None, refresh=False):
    resolved = resolve_ref(backend, pn_input, on_event, refresh=refresh)

    kinds = _available_image_kinds(backend, resolved, on_event)
    candidates = []
    if resolved["kc"]:
        candidates.append(resolved["kc"])
    candidates += [k for k in kinds if k not in candidates]

    for kind in candidates:
        found = _try_download(backend, f"/3.2/rest-services/images/documents/{resolved['cc']}/{resolved['num']}/{kind}/formats/pdf", on_event)
        if found:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            file = out / f"{resolved['pn']}.pdf"
            file.write_bytes(found["bytes"])
            return {
                "publicationNumber": resolved["pn"],
                "imageKind": kind,
                "file": str(file),
                "bytes": len(found["bytes"]),
                **({"note": f"该公开号无整册 PDF（{resolved['kc']}），已下载图像版本 {kind}。"}
                   if kind != resolved["kc"] else {}),
            }

    viewer_url = f"{ESPACENET_ORIGIN}/patent/search/family/{resolved['family_id'] or ''}/publication/{resolved['pn']}/en?tab=original"
    raise CliError(
        "PDF_UNAVAILABLE",
        f"未能下载 {resolved['pn']} 的 PDF（可用图像版本: {', '.join(kinds) if kinds else '无'}）。",
        action=f"该文献可能不提供整册 PDF；改用 `espacenet open {resolved['pn']}` 在原文页按页查看（{viewer_url}）。",
    )
