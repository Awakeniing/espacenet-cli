"""Search journal (Edison-style logbook).

On-disk layout (compatible with the prior CLI's journal directory):
  <journal_root>/
    auto-log.ndjson           every operation, session or not
    .active-session           current session pointer
    sessions/<ts>_<slug>/
      session.json            metadata (title, goal, start/end)
      journal.ndjson          session event stream (search/note/detail/error)
      results/NN-<slug>.json  normalized result datasets per search
    reports/                  compiled Markdown search reports
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from espacenet_cli.core.errors import CliError
from espacenet_cli.core.session import locked_save_json, read_json_or_none

NOTE_KINDS = ["背景", "思路", "调整", "分析", "结论", "备注"]


def get_journal_root(env=None):
    env = env if env is not None else os.environ
    if env.get("ESPACENET_JOURNAL_DIR"):
        return Path(env["ESPACENET_JOURNAL_DIR"]).resolve()
    return Path.cwd() / "espacenet-journal"


def _slugify(title, fallback="session"):
    s = re.sub(r"[\\/:*?\"<>|]", "", re.sub(r"\s+", "-", str(title or "").strip()))[:40]
    return s or fallback


def _now_stamp():
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def validate_note_kind(kind):
    k = str(kind or "备注").strip()
    if k not in NOTE_KINDS:
        raise CliError("INVALID_ARGUMENT", f"备注类型必须是: {' / '.join(NOTE_KINDS)}", exit_code=2)
    return k


def get_active_session(journal_root=None):
    root = Path(journal_root or get_journal_root())
    pointer = read_json_or_none(root / ".active-session")
    if not (isinstance(pointer, dict) and pointer.get("id")):
        return None
    meta = read_json_or_none(root / "sessions" / pointer["id"] / "session.json")
    if not meta or meta.get("status") != "open":
        return None
    return meta


def start_session(journal_root=None, title="", goal=""):
    root = Path(journal_root or get_journal_root())
    if not title or not str(title).strip():
        raise CliError("INVALID_ARGUMENT", "会话标题不能为空。", exit_code=2,
                       action='示例: espacenet session start "禧玛诺传动系统专利检索" --goal "…"')
    session_id = f"{_now_stamp()}_{_slugify(title)}"
    session_dir = root / "sessions" / session_id
    (session_dir / "results").mkdir(parents=True, exist_ok=True)
    meta = {
        "id": session_id,
        "title": str(title).strip(),
        "goal": str(goal or "").strip(),
        "startedAt": datetime.now().astimezone().isoformat(),
        "status": "open",
        "events": 0,
    }
    locked_save_json(session_dir / "session.json", meta)
    locked_save_json(root / ".active-session", {"id": session_id})
    return meta


def end_session(journal_root=None, session_id=None):
    root = Path(journal_root or get_journal_root())
    target = session_id or (get_active_session(root) or {}).get("id")
    if not target:
        return None
    meta_file = root / "sessions" / target / "session.json"
    meta = read_json_or_none(meta_file)
    if not meta:
        raise CliError("NOT_FOUND", f"会话不存在: {target}")
    meta["status"] = "closed"
    meta["closedAt"] = datetime.now().astimezone().isoformat()
    locked_save_json(meta_file, meta)
    locked_save_json(root / ".active-session", {"id": None})
    return meta


def list_sessions(journal_root=None):
    root = Path(journal_root or get_journal_root())
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        return []
    out = []
    for entry in sessions_dir.iterdir():
        meta = read_json_or_none(entry / "session.json")
        if meta:
            out.append(meta)
    return sorted(out, key=lambda m: str(m.get("startedAt") or ""), reverse=True)


def append_event(journal_root=None, event=None, session=None):
    root = Path(journal_root or get_journal_root())
    record = {"ts": datetime.now().astimezone().isoformat(), **(event or {})}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "auto-log.ndjson", "a", encoding="utf-8") as f:
        f.write(json_dumps(record) + "\n")
    session_id = (session or {}).get("id") or (get_active_session(root) or {}).get("id")
    if session_id:
        session_dir = root / "sessions" / session_id
        meta_file = session_dir / "session.json"
        meta = read_json_or_none(meta_file)
        if meta:
            record["seq"] = (meta.get("events") or 0) + 1
            meta["events"] = record["seq"]
            locked_save_json(meta_file, meta)
            with open(session_dir / "journal.ndjson", "a", encoding="utf-8") as f:
                f.write(json_dumps(record) + "\n")
    return record


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False)


def save_search_results(journal_root=None, payload=None):
    root = Path(journal_root or get_journal_root())
    active = get_active_session(root)
    if not active:
        return None
    results_dir = root / "sessions" / active["id"] / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    seq = str(payload.get("seq") or active.get("events") or 1).zfill(3)
    file = results_dir / f"{seq}-{_slugify(payload.get('query', ''), 'query')[:30]}.json"
    data = {**payload, "savedAt": datetime.now().astimezone().isoformat()}
    locked_save_json(file, data)
    return str(file)


def read_session_events(journal_root=None, session_id=None):
    root = Path(journal_root or get_journal_root())
    if not session_id:
        raise CliError("NOT_FOUND", "没有指定会话。")
    meta = read_json_or_none(root / "sessions" / session_id / "session.json")
    if not meta:
        raise CliError("NOT_FOUND", f"会话不存在: {session_id}")
    events = []
    journal_file = root / "sessions" / session_id / "journal.ndjson"
    if journal_file.exists():
        for line in journal_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    return {"meta": meta, "events": events}


def diff_search_events(prev, curr):
    """Automatic diff between two consecutive searches (检索调整 evidence)."""
    if not prev:
        return None
    changes = []
    if prev.get("query") != curr.get("query"):
        changes.append(f"检索式变更：「{prev.get('query')}」→「{curr.get('query')}」")
    if prev.get("size") is not None and curr.get("size") is not None and prev.get("size") != curr.get("size"):
        changes.append(f"页大小 {prev.get('size')}→{curr.get('size')}")
    if bool(prev.get("all")) != bool(curr.get("all")):
        changes.append("取消全量" if prev.get("all") else "改为全量抓取")
    if prev.get("page") is not None and curr.get("page") is not None and prev.get("page") != curr.get("page"):
        changes.append(f"翻页 {curr.get('page')}")
    fam_delta = (curr.get("totalFamilies") or 0) - (prev.get("totalFamilies") or 0)
    if changes and fam_delta != 0:
        changes.append(f"同族命中 {prev.get('totalFamilies')}→{curr.get('totalFamilies')}（{fam_delta:+d}）")
    return "；".join(changes) if changes else None


def _fmt_date(value):
    return str(value or "")[:16].replace("T", " ")


def _collect_stats(datasets):
    years, applicants, countries = {}, {}, {}
    families = set()
    for item in datasets:
        for r in item.get("results") or []:
            if r.get("publicationDate"):
                y = str(r["publicationDate"])[:4]
                years[y] = years.get(y, 0) + 1
            countries[r.get("countryCode") or ""] = countries.get(r.get("countryCode") or "", 0) + 1
            families.add(f"{r.get('familyId')}|{r.get('publicationNumber')}")
            for a in str(r.get("applicants") or "").split(";"):
                name = a.strip()
                if name:
                    applicants[name] = applicants.get(name, 0) + 1
    top = lambda obj, n: sorted(obj.items(), key=lambda kv: -kv[1])[:n]
    return {"years": top(years, 12), "applicants": top(applicants, 10),
            "countries": top(countries, 10), "familyCount": len(families)}


def generate_report(journal_root=None, session_id=None, out=None):
    root = Path(journal_root or get_journal_root())
    session_id = session_id or (get_active_session(root) or {}).get("id") \
        or (next(iter(list_sessions(root)), {}) or {}).get("id")
    if not session_id:
        raise CliError("NOT_FOUND", "没有可用的检索会话。",
                       action="先 `espacenet session start <标题>` 开始记录。")
    data = read_session_events(root, session_id)
    meta, events = data["meta"], data["events"]
    searches = [e for e in events if e.get("type") == "search"]
    notes = [e for e in events if e.get("type") == "note"]
    others = [e for e in events if e.get("type") not in ("search", "note")]

    datasets = []
    results_dir = root / "sessions" / session_id / "results"
    if results_dir.is_dir():
        for f in sorted(p for p in results_dir.iterdir() if p.suffix == ".json"):
            j = read_json_or_none(f)
            if isinstance(j, dict) and j.get("results"):
                datasets.append({"file": f.name, **j})
    stats = _collect_stats(datasets)

    L = []
    L.append(f"# 专利检索报告：{meta.get('title', '')}")
    L.append("")
    L.append(f"- **会话 ID**：`{meta.get('id')}`")
    L.append(f"- **开始时间**：{_fmt_date(meta.get('startedAt'))}　**结束**：{_fmt_date(meta.get('closedAt')) if meta.get('closedAt') else '（进行中）'}")
    L.append(f"- **记录事件**：{len(events)} 条（检索 {len(searches)} 次、备注 {len(notes)} 条、其他 {len(others)} 条）")
    L.append("- **数据来源**：Espacenet（worldwide.espacenet.com），经由 espacenet")
    L.append("")
    L.append("## 一、检索任务与背景")
    L.append("")
    L.append(meta.get("goal") or "（未填写检索目的。下次用 `espacenet session start <标题> --goal <目的>` 记录。）")
    for n in (n for n in notes if n.get("kind") == "背景"):
        L.append(f"- {n.get('text')}")
    L.append("")
    L.append("## 二、检索思路")
    L.append("")
    ideas = [n for n in notes if n.get("kind") == "思路"]
    if ideas:
        for n in ideas:
            L.append(f"- {n.get('text')}")
    else:
        L.append("（无思路备注。）")
    L.append("")
    L.append("## 三、检索过程")
    L.append("")
    if searches:
        L.append("| # | 时间 | 检索式 | 命中族 | 命中件 | 输出条数 | 结果/输出文件 |")
        L.append("|---|------|--------|--------|--------|----------|----------------|")
        for i, e in enumerate(searches):
            files = "，".join(x for x in [Path(e["resultsFile"]).name if e.get("resultsFile") else "",
                                          e.get("outFile") or ""] if x)
            L.append(f"| {i + 1} | {_fmt_date(e.get('ts'))} | `{e.get('query')}` | "
                     f"{e.get('totalFamilies', '?')} | {e.get('totalPublications', '?')} | "
                     f"{e.get('resultCount', '?')} | {files or '—'} |")
        L.append("")
        errors = [e for e in events if e.get("type") == "error"]
        if errors:
            L.append("**过程中的失败尝试（同样留档）：**")
            for e in errors:
                L.append(f"- {_fmt_date(e.get('ts'))} `{e.get('query') or e.get('command') or ''}` — {e.get('error')}")
            L.append("")
    else:
        L.append("（本会话没有检索记录。）")
        L.append("")
    L.append("## 四、检索调整")
    L.append("")
    diffs = []
    for i in range(1, len(searches)):
        d = diff_search_events(searches[i - 1], searches[i])
        if d:
            diffs.append(f"- 第 {i} → {i + 1} 次检索：{d}")
    adjust_notes = [n for n in notes if n.get("kind") == "调整"]
    if diffs or adjust_notes:
        for d in diffs:
            L.append(d)
        for n in adjust_notes:
            L.append(f"- {_fmt_date(n.get('ts'))} {n.get('text')}")
    else:
        L.append("（相邻检索式无变化，或未记录调整原因。）")
    L.append("")
    L.append("## 五、结果分析")
    L.append("")
    if datasets:
        L.append("### 5.1 已归档结果数据集")
        L.append("")
        L.append("| 结果文件 | 检索式 | 同族 | 公开 | 留存条数 |")
        L.append("|----------|--------|------|------|----------|")
        for d in datasets:
            L.append(f"| {d['file']} | `{d.get('query')}` | {d.get('totalFamilies', '?')} | "
                     f"{d.get('totalPublications', '?')} | {len(d['results'])} |")
        L.append("")
        L.append("### 5.2 总量统计（基于归档数据集）")
        L.append("")
        L.append(f"- 涉及专利族：约 **{stats['familyCount']}** 族")
        L.append(f"- 年份分布：{'、'.join(f'{y}({c})' for y, c in stats['years']) or '—'}")
        L.append(f"- 国家/组织分布：{'、'.join(f'{c}({n})' for c, n in stats['countries']) or '—'}")
        L.append("- 高频申请人：")
        for a, c in stats["applicants"]:
            L.append(f"  - {a} — {c} 件")
        L.append("")
    analyses = [n for n in notes if n.get("kind") == "分析"]
    if analyses:
        L.append("### 5.3 分析记录" if datasets else "### 分析记录")
        L.append("")
        for n in analyses:
            L.append(f"- {_fmt_date(n.get('ts'))} {n.get('text')}")
        L.append("")
    if not datasets and not analyses:
        L.append("（无统计数据与分析记录。）")
        L.append("")
    L.append("## 六、结论")
    L.append("")
    conclusions = [n for n in notes if n.get("kind") == "结论"]
    if conclusions:
        for n in conclusions:
            L.append(f"- {n.get('text')}")
    else:
        L.append("（未记录结论。用 `espacenet note \"…\" --kind 结论` 补充。）")
    L.append("")
    detail_events = [e for e in others if e.get("type") in ("detail", "claims", "description", "family", "legal", "pdf")]
    if detail_events:
        L.append("## 七、单件核查记录")
        L.append("")
        L.append("| 时间 | 操作 | 对象 | 结果 |")
        L.append("|------|------|------|------|")
        for e in detail_events:
            L.append(f"| {_fmt_date(e.get('ts'))} | {e.get('type')} | {e.get('target') or ''} | {e.get('summary') or e.get('status') or ''} |")
        L.append("")
    L.append("## 附录：复现命令")
    L.append("")
    L.append("```bash")
    for e in searches:
        opts = []
        if e.get("page") and e.get("page") != 1:
            opts.append(f"-p {e['page']}")
        if e.get("size") and e.get("size") != 20:
            opts.append(f"-s {e['size']}")
        if e.get("all"):
            opts.append(f"--all --limit {e.get('limit') or 2000}")
        if e.get("outFile"):
            opts.append(f"-f csv -o {e['outFile']}")
        if e.get("pacing") and e.get("pacing") != 700:
            opts.append(f"--pacing {e['pacing']}")
        suffix = (" " + " ".join(opts)) if opts else ""
        L.append(f"espacenet search {json.dumps(e.get('query'), ensure_ascii=False)}{suffix}")
    L.append("```")
    L.append("")
    L.append(f"> 原始流水：`{root / 'sessions' / meta.get('id', '') / 'journal.ndjson'}`；"
             f"本报告由 `espacenet report {meta.get('id')}` 生成。")

    report = "\n".join(L)
    out_path = Path(out).resolve() if out else root / "reports" / f"{meta.get('id')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return {"file": str(out_path), "content": report}
