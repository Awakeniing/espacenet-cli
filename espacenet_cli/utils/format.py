"""Output formatting: table / csv / ndjson / json (+ CJK-aware padding),
--json 字段投影（gh Exporter 模式）与 --jq 子集求值。"""

import json
import re
import sys
from pathlib import Path

from espacenet_cli.core.errors import CliError

RESULT_COLUMNS = [
    ["publicationNumber", "公开号"],
    ["title", "标题"],
    ["applicants", "申请人"],
    ["publicationDate", "公开日"],
    ["familyId", "同族"],
]

# --json 字段目录（gh Exporter 模式）：命令 → 允许的字段。
# 契约：字段名只增不改；列表型命令（search/family）投影的是行，对象型命令投影顶层键。
JSON_FIELDS = {
    "search": [
        "publicationNumber", "countryCode", "kindCode", "title", "abstract",
        "publicationDate", "publicationDates", "filingDate", "applicants",
        "inventors", "ipc", "cpc", "priority", "familyId", "familySize", "score",
    ],
    "detail": [
        "publicationNumber", "requested", "title", "abstract", "applicants",
        "inventors", "ipc", "cpc", "priority", "publicationDate", "filingDate",
        "familyId", "familySize", "familyMembers", "score",
    ],
    "claims": ["publicationNumber", "claimCount", "claims", "textFrom", "raw"],
    "description": ["publicationNumber", "description", "textFrom", "raw"],
    "family": ["publicationNumber", "kindCode", "date", "country"],
    "legal": ["publicationNumber", "eventCount", "events", "note"],
    "pdf": ["publicationNumber", "file", "bytes", "imageKind"],
    "session-list": ["id", "title", "status", "active", "startedAt", "goal", "events"],
    "session-show": ["id", "title", "goal", "status", "startedAt", "closedAt", "events"],
}


def parse_field_spec(spec):
    """'pn, title,' → ['pn', 'title']；空表报用法错误。"""
    fields = [s.strip() for s in str(spec or "").split(",") if s.strip()]
    if not fields:
        raise CliError("INVALID_ARGUMENT",
                       "--json 需要至少一个字段，如 --json publicationNumber,title", exit_code=2)
    return fields


def validate_fields(command, fields):
    """对照目录校验字段表；未知字段报错并列出可用字段（gh 风格，兼当文档）。"""
    catalog = JSON_FIELDS.get(command)
    if not catalog:
        return fields
    unknown = [f for f in fields if f not in catalog]
    if unknown:
        raise CliError(
            "INVALID_ARGUMENT",
            '未知 JSON 字段: %s。%s 可用字段: %s' % (", ".join(unknown), command, ", ".join(catalog)),
            action="改用上面列出的字段，或不带字段表的 --json 输出完整 JSON", exit_code=2)
    return fields


def project_payload(payload, fields, rows_key="results"):
    """按字段表投影：列表载荷逐行投影；对象载荷投影顶层键。"""
    def row(out, src):
        for k in fields:
            out[k] = src.get(k) if isinstance(src, dict) else None
        return out

    if isinstance(payload, dict):
        rows = payload.get(rows_key)
        if isinstance(rows, list):
            return [row({}, r) for r in rows]
        return row({}, payload)
    if isinstance(payload, list):
        return [row({}, r) for r in payload]
    return payload


_JQ_HELP = "支持子集：. 、.字段、.字段.字段、.[]、.[N] 与 | 管道组合，如 '.results[].publicationNumber'"
_JQ_SEGMENT = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_-]*)|\[(-?\d+)\]|(\[\])")


def _jq_stages(expr):
    """把 'a.b[] | .c' 解析为阶段列表。每阶段 = ('id',) 或 ('steps', [step...])。"""
    stages = []
    for raw in str(expr or "").split("|"):
        part = raw.strip()
        if not part:
            raise CliError("INVALID_ARGUMENT", "jq 表达式含空阶段: %r。%s" % (expr, _JQ_HELP), exit_code=2)
        if part == ".":
            stages.append(("id",))
            continue
        if not part.startswith("."):
            raise CliError("INVALID_ARGUMENT", "无法解析 jq 阶段 %r。%s" % (part, _JQ_HELP), exit_code=2)
        body = part[1:]  # 去掉强制前导点，键名段自身可带可选点
        steps, pos = [], 0
        while pos < len(body):
            m = _JQ_SEGMENT.match(body, pos)
            if not m:
                raise CliError("INVALID_ARGUMENT", "无法解析 jq 阶段 %r。%s" % (part, _JQ_HELP), exit_code=2)
            pos = m.end()
            if m.group(1) is not None:
                steps.append(("key", m.group(1)))
            elif m.group(2) is not None:
                steps.append(("index", int(m.group(2))))
            else:
                steps.append(("iter",))
        stages.append(("steps", steps))
    return stages


def _jq_step(step, value):
    kind = step[0]
    if kind == "key":
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(step[1])
        raise CliError("INVALID_ARGUMENT",
                       "jq: 在 %s 上取字段 .%s。%s" % (type(value).__name__, step[1], _JQ_HELP), exit_code=2)
    if kind == "index":
        if value is None:
            return None
        if isinstance(value, list):
            i = step[1]
            return value[i] if -len(value) <= i < len(value) else None
        raise CliError("INVALID_ARGUMENT",
                       "jq: 在 %s 上取下标 .[%d]。%s" % (type(value).__name__, step[1], _JQ_HELP), exit_code=2)
    raise CliError("INVALID_ARGUMENT", "jq: 内部步骤异常。%s" % _JQ_HELP, exit_code=2)


def _jq_apply_stage(stage, stream):
    if stage[0] == "id":
        return list(stream)
    out = []
    for value in stream:
        fan = [value]
        for step in stage[1]:
            if step[0] != "iter":
                fan = [_jq_step(step, v) for v in fan]
                continue
            nxt = []
            for v in fan:
                if isinstance(v, list):
                    nxt.extend(v)
                elif isinstance(v, dict):
                    nxt.extend(v.values())
                else:
                    raise CliError("INVALID_ARGUMENT",
                                   "jq: 不能对 %s 使用 .[]。%s" % (type(v).__name__ if v is not None else "null",
                                                                _JQ_HELP), exit_code=2)
            fan = nxt
        out.extend(fan)
    return out


def apply_jq(data, expr):
    """对反序列化后的 JSON 值执行 jq 子集；多个结果各占一行（字符串原样，其余紧凑 JSON）。"""
    results = [data]
    for stage in _jq_stages(expr):
        results = _jq_apply_stage(stage, results)
    return "\n".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in results)

def _char_width(ch):
    return 2 if ("\u2e80" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" or "\uff00" <= ch <= "\uffef") else 1


def _display_width(value):
    return sum(_char_width(c) for c in value)


def pad_cell(text, width):
    value = str(text if text is not None else "")
    used = 0
    out = ""
    for ch in value:
        w = _char_width(ch)
        if used + w > width:
            out += "…"
            used += 2
            break
        out += ch
        used += w
    return out + " " * max(0, width - used)


def format_table(rows, columns=None):
    if not isinstance(rows, list) or not rows:
        return "(无结果)"
    if not columns:
        keys = [k for k, v in rows[0].items() if v is None or not isinstance(v, (dict, list))]
        columns = [[k, k] for k in keys]
    widths = [min(_display_width(header) + 2, 40) for _, header in columns]
    for row in rows:
        for i, (key, _) in enumerate(columns):
            value = str(row.get(key) if row.get(key) is not None else "")
            w = _display_width(value[:60])
            widths[i] = min(max(widths[i], min(w + 2, 60)), 60)
    header = " ".join(pad_cell(h, widths[i]) for i, (_, h) in enumerate(columns))
    line = " ".join("-" * w for w in widths)
    body = "\n".join(" ".join(pad_cell(row.get(key) or "", widths[i]) for i, (key, _) in enumerate(columns)) for row in rows)
    return f"{header}\n{line}\n{body}"


def _csv_escape(value):
    v = str(value if value is not None else "")
    return f'"{v.replace(chr(34), chr(34) * 2)}"' if any(c in v for c in ',"\n\r') else v


def format_csv(rows, columns=None):
    if not isinstance(rows, list) or not rows:
        return ""
    keys = [k for k, _ in columns] if columns else [k for k in rows[0] if k != "publicationDates"]
    head = ",".join(keys)
    body = "\r\n".join(",".join(_csv_escape(row.get(k)) for k in keys) for row in rows)
    return "\ufeff" + head + "\r\n" + body


def _stringify_cell(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            parts = []
            for item in value:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(f"[{item['number']}] {item['text']}" if item.get("number") is not None else item["text"])
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            return "\n".join(parts)
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=1)
    return str(value)


def format_object_table(payload):
    if not isinstance(payload, dict):
        return str(payload if payload is not None else "")
    skip = {"publicationDates"}
    lines = []
    for key, value in payload.items():
        if key in skip:
            continue
        text = _stringify_cell(value)
        display = text if len(text) <= 2000 else text[:2000] + "…"
        indented = display.replace("\n", "\n" + " " * 22)
        lines.append(f"{pad_cell(key, 20)} {indented}")
    return "\n".join(lines)


def format_output(payload, fmt, columns=RESULT_COLUMNS, rows_key="results"):
    fmt_l = str(fmt or "table").lower()
    if fmt_l == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt_l == "ndjson":
        rows = payload.get(rows_key) if isinstance(payload, dict) else None
        rows = rows if isinstance(rows, list) else (payload if isinstance(payload, list) else [payload])
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    rows = payload.get(rows_key) if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else payload
    if fmt_l == "csv":
        return format_csv(rows if isinstance(rows, list) else [rows], columns)
    if fmt_l == "table":
        if isinstance(rows, list):
            return format_table(rows, columns)
        return format_object_table(rows)
    raise CliError("INVALID_ARGUMENT", f"不支持的输出格式: {fmt}", exit_code=2)


def write_out(output, out_path):
    if not out_path:
        sys.stdout.write(output + "\n")
        return
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")
