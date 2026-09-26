"""espacenet — Click CLI + REPL for worldwide.espacenet.com.

Every command supports --json for machine consumption; the REPL is the
default entry point (invoke_without_command). Data path: real Edge session
(utils/edge_backend) → Espacenet's own REST services.
"""

import contextlib
import json
import re
import shlex
import sys
import time
from pathlib import Path

import click

from espacenet_cli import __version__
from espacenet_cli.core.config import ESPACENET_ORIGIN, find_edge_executables, get_profile_paths, read_endpoint_file
from espacenet_cli.core.document import run_claims, run_description, run_detail, run_family, run_legal
from espacenet_cli.core.errors import CliError
from espacenet_cli.core.journal import (
    append_event,
    end_session,
    generate_report,
    get_active_session,
    get_journal_root,
    list_sessions,
    read_session_events,
    save_search_results,
    start_session,
    validate_note_kind,
)
from espacenet_cli.core.pdf import run_pdf
from espacenet_cli.core.search import run_search
from espacenet_cli.core.session import read_json_or_none as read_json_file
from espacenet_cli.utils.format import (
    RESULT_COLUMNS,
    apply_jq,
    format_output,
    parse_field_spec,
    project_payload,
    validate_fields,
    write_out,
)

#populated when the REPL re-dispatches through the group
_BASE_ARGS = []


def _stderr(msg, obj=None):
    obj = obj or {}
    if not obj.get("quiet") or obj.get("debug"):
        click.echo(f"[espacenet] {msg}", err=True)


def _event_logger(obj):
    return lambda msg: _stderr(msg, obj)


def _journal_root(obj):
    if obj.get("journal_dir"):
        return Path(obj["journal_dir"]).resolve()
    return get_journal_root()


def _log_event(obj, event, session=None):
    if obj.get("no_journal"):
        return None
    try:
        return append_event(journal_root=_journal_root(obj), event=event, session=session)
    except Exception:
        return None


def _session_hint(obj):
    if obj.get("no_journal") or obj.get("quiet") or obj.get("session"):
        return
    try:
        if not get_active_session(_journal_root(obj)):
            click.echo("[espacenet] 提示：未创建检索会话，本次操作仅写入全量流水。"
                       "需要体系化留档请先 `espacenet session start <标题> --goal <目的>`", err=True)
    except Exception:
        pass


@contextlib.contextmanager
def backend_from(obj):
    from espacenet_cli.utils.edge_backend import EspacenetBackend

    paths = get_profile_paths(obj["profile"])
    backend = EspacenetBackend.create(
        profile=obj["profile"], mode=obj["edge_mode"],
        pacing_ms=obj["pacing"], on_event=_event_logger(obj),
        await_budget=obj.get("await_budget", False))
    try:
        yield backend
    finally:
        backend.close()


def _json_fields_from(as_json, command):
    """--json 三态：无 → None；裸 --json → None（完整 JSON）；'pn,title' → 校验后的字段表。"""
    if not as_json or as_json is True:
        return None
    fields = parse_field_spec(as_json)
    return validate_fields(command, fields) if command else fields


def _emit(payload, obj, columns=None, rows_key="results"):
    as_json = bool(obj.get("as_json") or obj.get("jq"))
    fmt = "json" if as_json else obj.get("fmt", "table")
    if fmt == "json":
        fields = obj.get("json_fields")
        if fields:
            payload = project_payload(payload, fields, rows_key=rows_key)
        if obj.get("jq"):
            output = apply_jq(payload, obj["jq"])
        else:
            output = format_output(payload, "json", columns=columns, rows_key=rows_key)
    else:
        output = format_output(payload, fmt, columns=columns, rows_key=rows_key)
    write_out(output, obj.get("out"))


def _output_options(f):
    f = click.option("-f", "--format", "fmt", default="table", show_default=True,
                     type=click.Choice(["table", "json", "csv", "ndjson"]), help="输出格式")(f)
    f = click.option("-o", "--out", default=None, help="写入文件而非标准输出")(f)
    f = click.option("--json", "as_json", is_flag=False, flag_value=True, default=None,
                     help="JSON 输出（等价 -f json）；可跟字段表只取所选字段，如 --json publicationNumber,title "
                          "（建议放在命令末尾）")(f)
    f = click.option("--jq", "jq_expr", default=None,
                     help="对 JSON 结果施加 jq 子集过滤（.字段/.[]/.[N]/| 管道），隐含 --json")(f)
    return f


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="espacenet")
@click.option("--profile", default="default", show_default=True, help="Edge profile 名称")
@click.option("--edge-mode", default="visible", show_default=True,
              type=click.Choice(["visible", "background"]), help="Edge 窗口模式")
@click.option("--pacing", default=700, show_default=True, type=int, help="请求间隔毫秒（EPO Fair Use）")
@click.option("--journal-dir", default=None, help="检索记录目录（默认 ./espacenet-journal）")
@click.option("--no-journal", is_flag=True, help="本次不写检索记录")
@click.option("--session", "session_id", default=None, help="记录到指定会话 id")
@click.option("--await-budget", is_flag=True,
              help="检索配额不足时自动排队等待（默认快速失败并给出恢复时间）")
@click.option("--debug", is_flag=True, help="输出调试信息")
@click.option("--quiet", "-q", is_flag=True, help="不输出进度信息")
@click.pass_context
def cli(ctx, profile, edge_mode, pacing, journal_dir, no_journal, session_id, await_budget, debug, quiet):
    """Espacenet（worldwide.espacenet.com）的 AI 可用命令行客户端。

    无参数运行进入交互式 REPL。数据通道：本机 Edge 常驻会话 + Espacenet
    同款 REST 服务（自动通过 Cloudflare 人机验证，遵守 EPO Fair Use）。

    检索配额内置令牌桶（默认 12 次突发、约 8.6 次/分钟回填、触发限流自动冻结
    6-7 分钟），多次命令共享同一份预算；文献类命令（claims/family/legal/pdf）
    走本地缓存与不限流的文献端点，基本不消耗检索配额。
    """
    ctx.obj = {
        "profile": profile, "edge_mode": edge_mode, "pacing": pacing,
        "journal_dir": journal_dir, "no_journal": no_journal,
        "session": session_id, "await_budget": await_budget,
        "debug": debug, "quiet": quiet,
        "fmt": "table", "out": None, "as_json": False,
    }
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.command()
@click.option("--json", "as_json_flag", is_flag=True, help="JSON 输出（本命令默认已是 JSON）")
@click.pass_context
def connect(ctx, as_json_flag):
    """启动/复用共享 Edge 并完成人机验证。"""
    obj = ctx.obj
    with backend_from(obj) as backend:
        page = backend.ensure_on_espacenet(force_reload=obj.get("debug", False))
        status = {
            "connected": True,
            "profile": backend.paths["profile"],
            "edge": f"127.0.0.1:{backend.endpoint['port']}",
            "edgeMode": backend.endpoint["mode"],
            "page": page.url,
        }
    _emit(status, {**obj, "as_json": True})


@cli.command()
@click.option("--json", "as_json_flag", is_flag=True, help="JSON 输出（本命令默认已是 JSON）")
@click.pass_context
def status(ctx, as_json_flag):
    """查看共享 Edge 会话、profile 状态与检索预算。"""
    obj = ctx.obj
    paths = get_profile_paths(obj["profile"])
    endpoint = read_endpoint_file(paths["edge_endpoint_file"])
    from espacenet_cli.core.budget import SearchBudget

    budget = SearchBudget(paths["profile_root"] / "search-budget.json").snapshot()
    cache_file = paths["profile_root"] / "document-cache.json"
    cache_entries = len(read_json_file(cache_file) or {})
    _emit({
        "profile": paths["profile"],
        "profileRoot": str(paths["profile_root"]),
        "edgeExecutableFound": len(find_edge_executables()) > 0,
        "sharedEdge": ({
            "host": endpoint["host"], "port": endpoint["port"], "pid": endpoint["pid"],
            "mode": endpoint["mode"], "updatedAt": endpoint["updated_at"],
        } if endpoint else None),
        "searchBudget": budget,
        "documentCache": {"entries": cache_entries, "ttlDays": 7},
    }, {**obj, "as_json": True})


@cli.command()
@click.option("--json", "as_json_flag", is_flag=True, help="JSON 输出（本命令默认已是 JSON）")
def doctor(as_json_flag):
    """环境自检（Edge 可执行文件、profile、共享会话）。"""
    paths = get_profile_paths("default")
    exe = next((c for c in find_edge_executables() if Path(c).exists()), None)
    click.echo(json.dumps({
        "edgeExecutable": exe,
        "edgeCandidates": find_edge_executables(),
        "profileRoot": str(paths["profile_root"]),
        "sharedEdge": read_endpoint_file(paths["edge_endpoint_file"]),
    }, ensure_ascii=False, indent=2))


@cli.command()
@click.argument("sub", default="status", type=click.Choice(["start", "status", "stop"]))
@click.option("--json", "as_json_flag", is_flag=True, help="JSON 输出（本命令默认已是 JSON）")
@click.pass_context
def edge(ctx, sub, as_json_flag):
    """管理共享 Edge 进程（start|status|stop）。"""
    obj = ctx.obj
    from espacenet_cli.utils.edge_backend import stop_edge

    paths = get_profile_paths(obj["profile"])
    if sub == "start":
        with backend_from(obj) as backend:
            _emit({"started": True, "reused": backend.reused,
                   "endpoint": f"127.0.0.1:{backend.endpoint['port']}", "mode": backend.endpoint["mode"]},
                  {**obj, "as_json": True})
    elif sub == "stop":
        _emit({"stopped": stop_edge(paths)}, {**obj, "as_json": True})
    else:
        endpoint = read_endpoint_file(paths["edge_endpoint_file"])
        _emit({"running": bool(endpoint), "endpoint": endpoint}, {**obj, "as_json": True})


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="确认执行")
@click.option("--json", "as_json_flag", is_flag=True, help="JSON 输出（本命令默认已是 JSON）")
@click.pass_context
def logout(ctx, yes, as_json_flag):
    """清除 profile（含已保存的人机验证凭据）。"""
    if not yes:
        raise CliError("CONFIRM_REQUIRED", "logout 将删除该 profile 的 Edge 数据（含已通过的人机验证）。",
                       action="确认执行请加 --yes")
    import shutil

    obj = ctx.obj
    from espacenet_cli.utils.edge_backend import stop_edge

    paths = get_profile_paths(obj["profile"])
    stop_edge(paths)
    shutil.rmtree(paths["profile_root"], ignore_errors=True)
    _emit({"cleared": str(paths["profile_root"])}, {**obj, "as_json": True})


@cli.command()
@click.argument("query", nargs=-1, required=True)
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=20, show_default=True, type=int, help="页大小 1-100")
@click.option("--all", "fetch_all", is_flag=True, help="抓取全部结果（配合 --limit）")
@click.option("--limit", default=2000, show_default=True, type=int)
@_output_options
@click.pass_context
def search(ctx, query, page, size, fetch_all, limit, fmt, out, as_json, jq_expr):
    """检索（Espacenet CQL 或智能检索文本）。"""
    obj = {**ctx.obj, "fmt": fmt, "out": out, "as_json": as_json, "jq": jq_expr}
    obj["json_fields"] = _json_fields_from(as_json, "search")
    query_str = " ".join(query).strip()
    _session_hint(obj)
    t0 = time.monotonic()
    payload = None
    try:
        with backend_from(obj) as backend:
            payload = run_search(backend, query_str, page=page, size=size,
                                 fetch_all=fetch_all, limit=limit,
                                 on_progress=lambda m: _stderr(m, obj))
    except CliError as error:
        _log_event(obj, {"type": "error", "query": query_str, "page": page, "size": size,
                         "error": f"{error.code}: {error.message}"[:300]})
        raise
    duration_ms = int((time.monotonic() - t0) * 1000)

    summary = {"query": payload["query"], "totalFamilies": payload["totalFamilies"],
               "totalPublications": payload["totalPublications"], "resultCount": payload["resultCount"]}
    _log_event(obj, {
        "type": "search", "query": query_str, "page": page, "size": size, "all": fetch_all,
        "limit": limit, "pacing": obj["pacing"], "format": "json" if as_json else fmt,
        "outFile": out, "totalFamilies": payload["totalFamilies"],
        "totalPublications": payload["totalPublications"], "resultCount": payload["resultCount"],
        "durationMs": duration_ms,
    })
    results_file = save_search_results(journal_root=_journal_root(obj), payload={
        "query": query_str, "page": page, "size": size, "all": fetch_all,
        "totalFamilies": payload["totalFamilies"], "totalPublications": payload["totalPublications"],
        "results": [{k: v for k, v in r.items()} for r in payload["results"]],
    }) if not obj.get("no_journal") else None
    if not obj.get("as_json"):
        _stderr(f"同族命中 {payload['totalFamilies']}，公开文献 {payload['totalPublications']}，"
                f"本次输出 {payload['resultCount']} 条", obj)
    _emit(payload, obj, columns=RESULT_COLUMNS, rows_key="results")
    if results_file:
        _stderr(f"已留档 {results_file}", obj)
    if out:
        _stderr(f"已写入 {out}（{json.dumps(summary, ensure_ascii=False)}）", obj)
    return payload


def _document_command(doc_type):
    @_output_options
    @click.argument("publication_number")
    @click.option("--raw", is_flag=True, help="附带/输出原始响应")
    @click.option("--refresh", is_flag=True, help="跳过本地解析缓存，强制重新检索")
    @click.option("--dir", "out_dir", default=".", help="PDF 输出目录（仅 pdf）")
    @click.pass_context
    def command(ctx, publication_number, fmt, out, as_json, raw, refresh, out_dir, jq_expr):
        obj = {**ctx.obj, "fmt": fmt, "out": out, "as_json": as_json, "jq": jq_expr}
        obj["json_fields"] = _json_fields_from(as_json, doc_type)
        _session_hint(obj)
        try:
            with backend_from(obj) as backend:
                if doc_type == "detail":
                    payload = run_detail(backend, publication_number, on_event=_event_logger(obj))
                elif doc_type == "claims":
                    payload = run_claims(backend, publication_number, raw=raw,
                                         on_event=_event_logger(obj), refresh=refresh)
                elif doc_type == "description":
                    payload = run_description(backend, publication_number, raw=raw,
                                              on_event=_event_logger(obj), refresh=refresh)
                elif doc_type == "family":
                    payload = run_family(backend, publication_number,
                                         on_event=_event_logger(obj), refresh=refresh)
                elif doc_type == "legal":
                    payload = run_legal(backend, publication_number,
                                        on_event=_event_logger(obj), refresh=refresh)
                else:
                    payload = run_pdf(backend, publication_number, out_dir=out_dir,
                                      on_event=_event_logger(obj), refresh=refresh)
        except CliError as error:
            _log_event(obj, {"type": "error", "command": doc_type, "target": publication_number,
                             "error": f"{error.code}: {error.message}"[:300]})
            raise
        if doc_type == "detail":
            summary = str(payload.get("title") or "")[:80]
        elif doc_type == "claims":
            summary = f"{len(payload.get('claims') or [])} 项" + (f"，来自 {payload['textFrom']}" if payload.get("textFrom") else "")
        elif doc_type == "description":
            summary = f"{len(payload.get('description') or '')} 字符" + (f"，来自 {payload['textFrom']}" if payload.get("textFrom") else "")
        elif doc_type == "family":
            summary = f"{payload.get('memberCount', len(payload.get('members') or []))} 个同族成员"
        elif doc_type == "legal":
            summary = f"{payload.get('eventCount', len(payload.get('events') or []))} 个法律事件"
        else:
            summary = f"{payload.get('file')}（{payload.get('bytes')} B，图像版本 {payload.get('imageKind')}）"
        _log_event(obj, {"type": doc_type, "target": payload.get("publicationNumber"), "summary": summary})
        _emit(payload, obj, columns=None, rows_key="members")
        if obj.get("out"):
            _stderr(f"已写入 {out}", obj)

    help_text = {
        "detail": "单件著录数据 + 摘要。",
        "claims": "权利要求文本（EP 自动回退同族英文成员并标注来源）。",
        "description": "说明书文本（EP 自动回退同族英文成员并标注来源）。",
        "family": "INPADOC 扩展同族成员。",
        "legal": "法律事件。",
        "pdf": "下载整册 PDF（部分文献按图像索引回退）。",
    }[doc_type]
    return click.command(doc_type, help=help_text)(command)


cli.add_command(_document_command("detail"))
cli.add_command(_document_command("claims"))
cli.add_command(_document_command("description"))
cli.add_command(_document_command("family"))
cli.add_command(_document_command("legal"))
cli.add_command(_document_command("pdf"))


@cli.command("open")
@click.argument("target", nargs=-1, required=True)
@click.pass_context
def open_(ctx, target):
    """在共享 Edge 中打开检索式或公开号对应页面（人工浏览）。"""
    obj = ctx.obj
    target_str = " ".join(target).strip()
    compact = re.sub(r"\s+", "", target_str)
    is_pn = re.match(r"^[A-Za-z]{2}\d{4,}", compact) and not re.search(r"[=(]", target_str)
    url = f"{ESPACENET_ORIGIN}/patent/search?q={compact if is_pn else target_str}"
    from espacenet_cli.utils.edge_backend import goto_cleared

    with backend_from(obj) as backend:
        page = backend.ensure_on_espacenet()
        with contextlib.suppress(Exception):
            page.bring_to_front()
        result = goto_cleared(page, url, on_event=_event_logger(obj))
        if not result["ok"]:
            raise CliError("CHALLENGE_BLOCKED", "未能通过人机验证，无法打开页面。")
    _stderr(f"已在 Edge 中打开: {url}", obj)


@cli.group(invoke_without_command=True)
@click.pass_context
def session(ctx):
    """检索会话：start 开题（--goal 记录目的）→ 自动留档 → end 归档。"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@session.command("start")
@click.argument("title", nargs=-1, required=True)
@click.option("--goal", default="", help="检索目的")
@click.option("--dry-run", is_flag=True, help="预览将创建的会话，不写入")
@click.pass_context
def session_start(ctx, title, goal, dry_run):
    obj = ctx.obj
    title_str = " ".join(title).strip()
    if dry_run:
        _emit({"wouldStart": True, "title": title_str, "goal": goal,
               "journalRoot": str(_journal_root(obj))}, {**obj, "as_json": True})
        return
    meta = start_session(journal_root=_journal_root(obj), title=title_str, goal=goal)
    _emit({"started": True, "id": meta["id"], "title": meta["title"], "goal": meta["goal"],
           "dir": str(_journal_root(obj) / "sessions" / meta["id"])}, {**obj, "as_json": True})
    _stderr("会话已开启并设为当前。之后所有检索/单件操作自动留档；用 `note \"…\"` 记录思路与结论，"
            "`session end` 归档，`report` 生成报告。", obj)


@session.command("list")
@_output_options
@click.pass_context
def session_list(ctx, fmt, out, as_json, jq_expr):
    obj = {**ctx.obj, "fmt": fmt, "out": out, "as_json": as_json, "jq": jq_expr}
    obj["json_fields"] = _json_fields_from(as_json, "session-list")
    sessions = list_sessions(_journal_root(obj))
    active = get_active_session(_journal_root(obj))
    rows = [{"id": s["id"], "title": s["title"], "status": s["status"],
             "active": bool(active and active["id"] == s["id"]),
             "startedAt": s["startedAt"], "goal": s.get("goal", ""),
             "events": s.get("events", 0)} for s in sessions]
    _emit(rows, obj, columns=None)


@session.command("show")
@click.argument("session_id", required=False)
@_output_options
@click.pass_context
def session_show(ctx, session_id, fmt, out, as_json, jq_expr):
    obj = {**ctx.obj, "fmt": fmt, "out": out, "as_json": as_json, "jq": jq_expr}
    obj["json_fields"] = _json_fields_from(as_json, "session-show")
    target = session_id or (get_active_session(_journal_root(obj)) or {}).get("id")
    if not target:
        raise CliError("NOT_FOUND", "没有指定会话，也没有当前活跃会话。",
                       action="用 `session list` 查看会话。")
    data = read_session_events(_journal_root(obj), target)
    _emit({**data["meta"], "events": data["events"]}, obj, columns=None)


@session.command("end")
@click.argument("session_id", required=False)
@click.option("--dry-run", is_flag=True, help="预览将归档的会话，不写入")
@click.pass_context
def session_end(ctx, session_id, dry_run):
    obj = ctx.obj
    target = session_id or (get_active_session(_journal_root(obj)) or {}).get("id")
    if dry_run:
        _emit({"wouldEnd": target}, {**obj, "as_json": True})
        return
    meta = end_session(_journal_root(obj), target)
    if not meta:
        _emit({"ended": False, "reason": "没有活跃会话"}, {**obj, "as_json": True})
        return
    _emit({"ended": True, "id": meta["id"], "closedAt": meta["closedAt"]}, {**obj, "as_json": True})
    _stderr(f"可运行 `report {meta['id']}` 生成检索报告。", obj)


@cli.command()
@click.argument("text", nargs=-1, required=True)
@click.option("--kind", default="备注", show_default=True,
              type=click.Choice(["背景", "思路", "调整", "分析", "结论", "备注"]))
@click.option("--dry-run", is_flag=True, help="预览将记录的内容，不写入")
@click.pass_context
def note(ctx, text, kind, dry_run):
    """记录检索备注（背景/思路/调整/分析/结论/备注）。"""
    obj = ctx.obj
    text_str = " ".join(text).strip()
    kind = validate_note_kind(kind)
    if dry_run:
        _emit({"wouldRecord": True, "kind": kind, "text": text_str}, {**obj, "as_json": True})
        return
    active = obj.get("session")
    if not active and not get_active_session(_journal_root(obj)):
        raise CliError("NO_SESSION", "没有活跃检索会话，备注无处落档。",
                       action="先 `session start <标题>`，或用 --session <id> 指定会话。")
    record = _log_event(obj, {"type": "note", "kind": kind, "text": text_str},
                        session={"id": active} if active else None)
    _stderr(f"已记录 {kind}：{text_str[:60]}{'…' if len(text_str) > 60 else ''}", obj)
    _emit({"recorded": True, "seq": (record or {}).get("seq"), "kind": kind, "text": text_str},
          {**obj, "as_json": True})


@cli.command()
@click.argument("session_id", required=False)
@click.option("-o", "--out", default=None, help="报告输出路径")
@click.option("--json", "as_json", is_flag=True, help="JSON 输出")
@click.pass_context
def report(ctx, session_id, out, as_json):
    """把会话编译为体系化检索报告（Markdown）。"""
    obj = {**ctx.obj, "out": None, "as_json": as_json}
    result = generate_report(journal_root=_journal_root(obj), session_id=session_id, out=out)
    _stderr(f"检索报告已生成：{result['file']}", obj)
    _emit({"file": result["file"]}, obj)


@cli.command()
@click.pass_context
def repl(ctx):
    """进入交互式 REPL（无子命令时的默认行为）。"""
    from espacenet_cli.utils.repl_skin import ReplSkin

    global _BASE_ARGS
    _BASE_ARGS = [f"--profile={ctx.obj['profile']}", f"--edge-mode={ctx.obj['edge_mode']}",
                  f"--pacing={ctx.obj['pacing']}"]
    if ctx.obj.get("journal_dir"):
        _BASE_ARGS.append(f"--journal-dir={ctx.obj['journal_dir']}")
    if ctx.obj.get("no_journal"):
        _BASE_ARGS.append("--no-journal")

    skin = ReplSkin("espacenet", version=__version__)
    skin.print_banner()
    try:
        pt_session = skin.create_prompt_session()
    except Exception:
        # No interactive console (piped stdin, agent subprocess): fall back to plain input.
        pt_session = None
    last_results = None

    def read_line():
        active = get_active_session(_journal_root(ctx.obj))
        title = (active or {}).get("title") or ctx.obj["profile"]
        if pt_session is not None:
            return skin.get_input(pt_session, project_name=title, modified=bool(active))
        return input(f"espacenet [{title}]> ")

    commands_help = {
        "search": "search <检索式> [-s N] [--all] [-f csv] — 检索",
        "detail": "detail <公开号> — 单件著录数据",
        "claims": "claims <公开号> — 权利要求",
        "description": "description <公开号> — 说明书",
        "family": "family <公开号> — 同族",
        "legal": "legal <公开号> — 法律事件",
        "pdf": "pdf <公开号> --dir <目录> — 下载 PDF",
        "open": "open <检索式|公开号> — Edge 中打开页面",
        "connect": "connect — 连接共享 Edge 并过验证",
        "status": "status — 会话与 profile 状态",
        "edge": "edge start|status|stop — 管理共享 Edge",
        "session": "session start|list|show|end — 检索会话",
        "note": "note <文字> --kind 类型 — 检索备注",
        "report": "report [会话id] — 编译检索报告",
        "save": "save <文件.json|csv> — 保存最近检索结果",
        "context": "context — 最近一次检索摘要",
        "help": "help — 本帮助",
        "quit": "quit / exit — 退出",
    }

    def show_context():
        if not last_results:
            skin.info("还没有检索结果。先 search 一次。")
            return
        skin.status("query", last_results["query"])
        skin.status("hits", f"{last_results['totalFamilies']} families / "
                            f"{last_results['totalPublications']} publications / {last_results['resultCount']} rows")

    while True:
        try:
            line = read_line()
            if line is None:
                break
            line = line.strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        try:
            # Literal whitespace split: CQL phrase quotes (ti="disc brake")
            # must reach the query intact — no shell-style quote stripping.
            tokens = line.split()
        except ValueError as error:
            skin.error(f"解析失败: {error}")
            continue
        head = tokens[0].lower()
        try:
            if head in ("quit", "exit"):
                break
            if head == "help":
                skin.help(commands_help)
                continue
            if head == "context":
                show_context()
                continue
            if head == "save":
                if not last_results:
                    skin.error("没有可保存的检索结果。")
                    continue
                target = tokens[1] if len(tokens) > 1 else f"results-{int(time.time())}.json"
                fmt = "csv" if target.lower().endswith(".csv") else "json"
                output = format_output(last_results, fmt, columns=RESULT_COLUMNS)
                write_out(output, target)
                skin.success(f"已保存 {target}")
                continue
            result = cli.main(args=_BASE_ARGS + tokens, standalone_mode=False, obj=None)
            if head == "search" and isinstance(result, dict) and "results" in result:
                last_results = result  # keep for save/context
        except click.exceptions.Exit as error:
            if int(error.code or 0) != 0:
                skin.error(f"exit code {error.code}")
        except click.ClickException as error:
            skin.error(str(error.format_message()))
        except CliError as error:
            skin.error(f"[{error.code}] {error.message}")
            if error.action:
                skin.hint(f"→ {error.action}")
        except Exception as error:  # noqa: BLE001 — REPL must survive anything
            skin.error(str(error))

    skin.print_goodbye()


def main():
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        cli.main(standalone_mode=False)
        sys.exit(0)
    except click.exceptions.Exit as error:
        sys.exit(int(error.code or 0))
    except click.ClickException as error:
        error.show()
        sys.exit(error.exit_code)
    except CliError as error:
        click.echo(f"✗ [{error.code}] {error.message}", err=True)
        if error.action:
            click.echo(f"  → {error.action}", err=True)
        sys.exit(error.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
