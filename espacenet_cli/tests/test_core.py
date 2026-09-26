"""Unit tests for espacenet core modules (synthetic data only)."""

import json

import pytest

from espacenet_cli.core.config import (
    find_edge_executables,
    get_profile_paths,
    read_endpoint_file,
    validate_profile_name,
)
from espacenet_cli.core.errors import CliError
from espacenet_cli.core.journal import (
    append_event,
    diff_search_events,
    end_session,
    generate_report,
    get_active_session,
    list_sessions,
    save_search_results,
    start_session,
    validate_note_kind,
)
from espacenet_cli.core.search import (
    normalize_hit_publication,
    normalize_search_payload,
    run_search,
)
from espacenet_cli.core.session import locked_save_json, read_json_or_none
from espacenet_cli.core.text import (
    num_to_date,
    parse_multipart_text,
    parse_publication_number,
    same_publication,
    split_claims,
    strip_html,
    xml_to_text,
)
from espacenet_cli.utils.edge_backend import build_edge_launch_args, make_trace_id
from espacenet_cli.utils.format import (
    apply_jq,
    format_csv,
    format_object_table,
    format_output,
    format_table,
    pad_cell,
    parse_field_spec,
    project_payload,
    validate_fields,
)


# ---------------------------------------------------------------- text.py

def test_parse_pn_full():
    parsed = parse_publication_number("EP2600908A1")
    assert parsed == {"cc": "EP", "num": "2600908", "kind": "A1",
                      "stem": "EP2600908", "full": "EP2600908A1"}


def test_parse_pn_kind_optional():
    assert parse_publication_number("EP2600908")["kind"] == ""
    assert parse_publication_number("EP2600908")["full"] == "EP2600908"


def test_parse_pn_normalizes_spaces_and_case():
    assert parse_publication_number(" ep 2600908 a1 ")["full"] == "EP2600908A1"


def test_parse_pn_us():
    assert parse_publication_number("US11234567B2")["kind"] == "B2"


def test_parse_pn_invalid():
    with pytest.raises(CliError) as exc:
        parse_publication_number("not-a-pn")
    assert exc.value.code == "INVALID_PN"
    assert exc.value.exit_code == 2


def test_strip_html():
    assert strip_html("<b>Hello</b> &amp; <i>world</i>") == "Hello & world"
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_xml_to_text_paragraph_numbers():
    xml = '<p n="1">Claim one.</p><p n="2">Second <hi rend="subscript">x</hi> part.</p>'
    text = xml_to_text(xml)
    assert "[1] Claim one." in text
    assert "[2] Second _{x} part." in text


def test_xml_to_text_entities():
    assert "A & B" in xml_to_text("<p n=\"1\">A &amp; B</p>")


def test_xml_to_text_collapses_blank_lines():
    assert "\n\n\n" not in xml_to_text("<p n=\"1\">a</p><p n=\"2\">b</p><p></p>")


def test_multipart_with_key_headers():
    raw = ("--BOUND\r\n"
           "Content-Type: text/plain\r\nkey: publications.claims_en\r\n\r\n"
           "part one\r\n"
           "--BOUND\r\n"
           "key: publications.desc_en\r\n\r\n"
           "part two\r\n"
           "--BOUND--")
    assert parse_multipart_text(raw) == "part one\n\npart two"


def test_multipart_headerless_part_kept():
    raw = "--B\n\norphan part\n--B--"
    assert parse_multipart_text(raw) == "orphan part"


def test_multipart_passthrough_plain_text():
    assert parse_multipart_text("plain text") == "plain text"


def test_split_claims_numbered():
    text = "[0001] First claim.\n[0002] Second claim.\n[0003] Third."
    claims = split_claims(text)
    assert [c["number"] for c in claims] == [1, 2, 3]
    assert claims[0]["text"] == "First claim."


def test_split_claims_dotted():
    text = "1. First.\n2. Second."
    claims = split_claims(text)
    assert len(claims) == 2 and claims[1]["text"] == "Second."


def test_split_claims_single_block():
    assert split_claims("one blob") == [{"number": 1, "text": "one blob"}]
    assert split_claims("") == [{"number": 1, "text": ""}]


def test_num_to_date():
    assert num_to_date("19780131") == "1978-01-31"
    assert num_to_date("weird") == "weird"
    assert num_to_date(None) == "None" or num_to_date(None) == ""


def test_same_publication_tolerates_kind():
    assert same_publication("EP2600908A1", "EP2600908A1")
    assert same_publication("EP2600908", "EP2600908A1")
    assert not same_publication("EP2600908A1", "US5960411A")
    assert not same_publication(None, "EP1")


# ---------------------------------------------------------------- search.py

def _hit(pn, title="T", **fields):
    base = {
        "fields": {
            "publications.pn_docdb": [pn],
            "publications.ti_en": [title],
            "publications.abs_en": ["<p>abstract</p>"],
            "publications.pd": ["2024-01-01"],
            "publications.pa_patents": ["ACME Corp", "acme corp", "Beta AG"],
            "publications.in_patents": ["Doe, John"],
            "publications.ipc_icai": ["A61K 38/00"],
            "publications.ci_cpci": ["A61K38/00"],
            "publications.pr_docdb": ["2023-01-05"],
        },
        "score": 1.5,
    }
    return base


def test_normalize_hit_fields_and_dedupe():
    row = normalize_hit_publication(_hit("EP2600908A1"), {"familyId": "123", "familySize": "4"})
    assert row["publicationNumber"] == "EP2600908A1"
    assert row["countryCode"] == "EP" and row["kindCode"] == "A1"
    assert row["title"] == "T"
    assert row["abstract"] == "abstract"
    assert row["applicants"] == "ACME Corp; Beta AG"
    assert row["familyId"] == "123" and row["familySize"] == "4"
    assert row["score"] == 1.5


def test_normalize_payload_nested_family():
    payload = {
        "familiesNumber": 1,
        "publicationsNumber": 2,
        "hits": [{
            "familyNumber": "77",
            "publicationsCount": 2,
            "hits": [_hit("EP2600908A1"), _hit("US20240001A1", "U")],
            "fields": {"biblio": [{"9": {"pn_docdb": {"0": ["CN109876543A"]}, "pd": {"0": ["2022-09-30"]}}}]},
        }],
    }
    out = normalize_search_payload(payload, query="q")
    pns = [r["publicationNumber"] for r in out["results"]]
    assert pns == ["EP2600908A1", "US20240001A1", "CN109876543A"]
    assert out["totalFamilies"] == 1 and out["totalPublications"] == 2
    short = out["results"][2]
    assert short["publicationDate"] == "2022-09-30"
    assert short["familyId"] == "77"


def test_normalize_payload_dedupes_rows():
    payload = {"hits": [{"familyNumber": "1", "hits": [_hit("EP1A1")]}],
               "familiesNumber": 1, "publicationsNumber": 1}
    payload["hits"].append({"familyNumber": "1", "hits": [_hit("EP1A1")]})
    out = normalize_search_payload(payload)
    assert out["resultCount"] == 1


def test_normalize_payload_empty():
    out = normalize_search_payload({"hits": []}, query="q")
    assert out["resultCount"] == 0 and out["totalFamilies"] == 0


class FakeBackend:
    """Queued search responses to exercise run_search paging without network."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def search_raw(self, query, from_=0, size=20):
        self.calls.append((query, from_, size))
        index = min(from_ // size, len(self.pages) - 1)
        return self.pages[index]


def test_run_search_single_page():
    backend = FakeBackend([{"hits": [{"familyNumber": "1", "hits": [_hit("EP1A1")]}],
                            "familiesNumber": 1, "publicationsNumber": 1}])
    out = run_search(backend, "ti=x", page=1, size=20)
    assert out["resultCount"] == 1
    assert backend.calls[0][1] == 0


def test_run_search_page_offset():
    backend = FakeBackend([{"hits": [], "familiesNumber": 0, "publicationsNumber": 0}])
    run_search(backend, "ti=x", page=3, size=25)
    assert backend.calls[0][1] == 50


def test_run_search_all_paginates_until_no_fresh():
    page1 = {"hits": [{"familyNumber": "1", "hits": [_hit("EP1A1"), _hit("EP2A1")]},
                      {"familyNumber": "2", "hits": [_hit("EP3A1")]}],
             "familiesNumber": 20, "publicationsNumber": 30}
    page2 = {"hits": [{"familyNumber": "1", "hits": [_hit("EP1A1")]}],
             "familiesNumber": 20, "publicationsNumber": 30}
    backend = FakeBackend([page1, page2])
    out = run_search(backend, "ti=x", size=2, fetch_all=True, limit=10)
    assert [r["publicationNumber"] for r in out["results"]] == ["EP1A1", "EP2A1", "EP3A1"]
    assert len(backend.calls) == 2
    assert out["truncated"] is False


def test_run_search_all_respects_limit():
    rows = [{"familyNumber": str(i), "hits": [_hit(f"EP{i}A1")]} for i in range(10)]
    backend = FakeBackend([{"hits": rows, "familiesNumber": 10, "publicationsNumber": 10}])
    out = run_search(backend, "ti=x", size=20, fetch_all=True, limit=3)
    assert out["resultCount"] == 3
    assert out["truncated"] is True


def test_run_search_empty_query():
    with pytest.raises(CliError) as exc:
        run_search(FakeBackend([]), "  ")
    assert exc.value.code == "INVALID_ARGUMENT"


# ---------------------------------------------------------------- journal.py

def test_journal_session_lifecycle(tmp_path):
    root = tmp_path / "journal"
    meta = start_session(journal_root=root, title="禧玛诺传动系统检索", goal="摸底布局")
    assert meta["status"] == "open"
    assert get_active_session(root)["id"] == meta["id"]
    append_event(journal_root=root, event={"type": "search", "query": 'ti="bicycle"',
                                           "totalFamilies": 10, "totalPublications": 12, "resultCount": 10})
    append_event(journal_root=root, event={"type": "note", "kind": "思路", "text": "改用英文词"})
    assert (root / "auto-log.ndjson").read_text(encoding="utf-8").count("\n") == 2
    data = read_json_or_none(root / "sessions" / meta["id"] / "session.json")
    assert data["events"] == 2
    closed = end_session(journal_root=root)
    assert closed["id"] == meta["id"] and closed["status"] == "closed"
    assert get_active_session(root) is None
    listed = list_sessions(root)
    assert [s["id"] for s in listed] == [meta["id"]]


def test_append_event_without_session_only_auto_log(tmp_path):
    root = tmp_path / "journal"
    record = append_event(journal_root=root, event={"type": "detail", "target": "EP1A1"})
    assert record.get("seq") is None
    assert (root / "auto-log.ndjson").exists()


def test_save_search_results_named_by_query(tmp_path):
    root = tmp_path / "journal"
    start_session(journal_root=root, title="t")
    file = save_search_results(journal_root=root, payload={
        "query": 'ti="bicycle"', "results": [{"publicationNumber": "EP1A1"}]})
    assert file.endswith('.json') and "001-ti" in file.replace("\\", "/").split("/")[-1]
    data = json.loads(open(file, encoding="utf-8").read())
    assert data["results"][0]["publicationNumber"] == "EP1A1"


def test_save_search_results_no_session_returns_none(tmp_path):
    assert save_search_results(journal_root=tmp_path / "j", payload={"query": "q", "results": []}) is None


def test_diff_search_events():
    prev = {"query": "a", "size": 20, "all": False, "page": 1, "totalFamilies": 100}
    curr = {"query": "b", "size": 50, "all": True, "page": 2, "totalFamilies": 90}
    diff = diff_search_events(prev, curr)
    assert "检索式变更" in diff and "页大小" in diff and "全量" in diff and "翻页" in diff and "+-10" not in diff
    assert diff_search_events(None, curr) is None
    same = diff_search_events(prev, dict(prev))
    assert same is None


def test_report_structure_and_repro_commands(tmp_path):
    root = tmp_path / "journal"
    meta = start_session(journal_root=root, title="Shimano 检索", goal="机械结构 tandem 布局")
    append_event(journal_root=root, event={"type": "search", "query": 'ti="bicycle"',
                                           "page": 1, "size": 20, "all": True, "limit": 500,
                                           "totalFamilies": 5, "totalPublications": 6, "resultCount": 5})
    save_search_results(journal_root=root, payload={
        "query": 'ti="bicycle"', "totalFamilies": 5, "totalPublications": 6,
        "results": [{"publicationNumber": "EP1A1", "countryCode": "EP", "publicationDate": "2024-03-01",
                     "applicants": "Shimano", "familyId": "1"}]})
    append_event(journal_root=root, event={"type": "note", "kind": "结论", "text": "重点在封装结构层"})
    append_event(journal_root=root, event={"type": "error", "query": "bad query", "error": "QUERY_ERROR: x"})
    append_event(journal_root=root, event={"type": "detail", "target": "EP1A1", "summary": "tilte"})
    result = generate_report(journal_root=root)
    content = open(result["file"], encoding="utf-8").read()
    assert "## 一、检索任务与背景" in content
    assert "## 二、检索思路" in content
    assert "## 三、检索过程" in content
    assert "## 四、检索调整" in content
    assert "## 五、结果分析" in content
    assert "## 六、结论" in content
    assert "## 附录：复现命令" in content
    assert "espacenet search" in content
    assert "--all --limit 500" in content
    assert "QUERY_ERROR" in content  # failed attempts are journaled too
    assert "重点在封装结构层" in content
    assert "Shimano" in content


def test_validate_note_kind():
    assert validate_note_kind("思路") == "思路"
    assert validate_note_kind(None) == "备注"
    with pytest.raises(CliError):
        validate_note_kind("胡说")


# ---------------------------------------------------------------- session.py

def test_locked_save_json_roundtrip(tmp_path):
    file = tmp_path / "deep" / "state.json"
    locked_save_json(file, {"a": 1, "中文": "值"})
    assert read_json_or_none(file) == {"a": 1, "中文": "值"}
    locked_save_json(file, {"a": 2})
    assert read_json_or_none(file) == {"a": 2}


def test_read_json_or_none_missing(tmp_path):
    assert read_json_or_none(tmp_path / "nope.json") is None


# ---------------------------------------------------------------- config.py

def test_profile_name_validation():
    assert validate_profile_name("default") == "default"
    for bad in ["", "..", "a/b", "a\\b", "con", "nul.txt", 'a"b']:
        with pytest.raises(CliError):
            validate_profile_name(bad)


def test_profile_paths_layout(tmp_path):
    paths = get_profile_paths("work", config_root=tmp_path)
    assert paths["profile_root"] == tmp_path / "profiles" / "work"
    assert paths["browser_profile_dir"] == tmp_path / "profiles" / "work" / "edge-profile"
    assert paths["edge_endpoint_file"].name == "edge-endpoint.json"
    assert paths["launch_lock_file"] == tmp_path / "locks" / "work.edge-launch.lock"


def test_read_endpoint_file(tmp_path):
    file = tmp_path / "edge-endpoint.json"
    file.write_text(json.dumps({"version": 1, "port": 9222, "pid": 4321,
                                "profileDir": "x", "mode": "visible", "updatedAt": "t"}), encoding="utf-8")
    endpoint = read_endpoint_file(file)
    assert endpoint["port"] == 9222 and endpoint["pid"] == 4321 and endpoint["host"] == "127.0.0.1"
    file.write_text("{broken", encoding="utf-8")
    assert read_endpoint_file(file) is None
    file.write_text(json.dumps({"port": "not-a-port"}), encoding="utf-8")
    assert read_endpoint_file(file) is None


def test_find_edge_executables_ordered():
    candidates = find_edge_executables(env={})
    assert any("msedge.exe" in c for c in candidates)


# ---------------------------------------------------------------- format.py

def test_pad_cell_cjk_width():
    padded = pad_cell("中文", 8)
    assert padded == "中文    "  # display width 8 (CJK=2), character length 6
    assert sum(2 if "\u2e80" <= c <= "\u9fff" else 1 for c in padded) == 8
    assert pad_cell("标题很长的中文标题超限", 8).endswith("…")
    assert pad_cell("ab", 4) == "ab  "


def test_format_table():
    rows = [{"a": "x", "b": "中"}, {"a": "yy", "b": "z"}]
    table = format_table(rows)
    lines = table.splitlines()
    assert len(lines) == 4  # header + rule + 2 rows
    assert "a" in lines[0] and "b" in lines[0]


def test_format_table_empty():
    assert format_table([]) == "(无结果)"


def test_format_csv_bom_and_escaping():
    csv_text = format_csv([{"a": 'say "hi"', "b": "x,y"}])
    assert csv_text.startswith("﻿")
    assert '"say ""hi"""' in csv_text and '"x,y"' in csv_text


def test_format_output_json_ndjson():
    payload = {"results": [{"a": 1}, {"a": 2}]}
    assert format_output(payload, "json") == json.dumps(payload, ensure_ascii=False, indent=2)
    nd = format_output(payload, "ndjson")
    assert nd.splitlines()[0] == '{"a": 1}'


def test_format_object_table_claims():
    text = format_object_table({"claims": [{"number": 1, "text": "claim one"}], "note": None})
    assert "[1] claim one" in text


# ------------------------------------------------------------ format.py: --json 投影与 --jq

def test_parse_field_spec():
    assert parse_field_spec(" publicationNumber, title ,") == ["publicationNumber", "title"]
    with pytest.raises(CliError) as exc:
        parse_field_spec(" , ")
    assert exc.value.exit_code == 2


def test_validate_fields_unknown_lists_catalog():
    with pytest.raises(CliError) as exc:
        validate_fields("search", parse_field_spec("publicationNumber,nope"))
    assert "nope" in exc.value.message and "publicationNumber" in exc.value.message
    assert exc.value.exit_code == 2
    assert validate_fields("search", parse_field_spec("publicationNumber,title")) == \
        ["publicationNumber", "title"]
    # 无目录的命令（session list/show）只解析不校验
    assert validate_fields(None, parse_field_spec("anything")) == ["anything"]


def test_project_search_rows():
    payload = {"query": "q", "resultCount": 2,
               "results": [{"publicationNumber": "EP1A1", "title": "t", "abstract": "a"},
                           {"publicationNumber": "EP2A1", "title": "u", "abstract": "b"}]}
    assert project_payload(payload, ["publicationNumber", "title"]) == \
        [{"publicationNumber": "EP1A1", "title": "t"}, {"publicationNumber": "EP2A1", "title": "u"}]


def test_project_object_payload():
    payload = {"publicationNumber": "EP1A1", "claimCount": 3, "claims": [{"number": 1}]}
    assert project_payload(payload, ["publicationNumber", "claimCount"]) == \
        {"publicationNumber": "EP1A1", "claimCount": 3}
    assert project_payload([{"a": 1}], ["a"]) == [{"a": 1}]


def test_apply_jq_paths_and_pipes():
    data = {"results": [{"publicationNumber": "EP1A1", "title": "x"},
                        {"publicationNumber": "EP2A1", "title": "y"}],
            "resultCount": 2}
    assert apply_jq(data, ".resultCount") == "2"
    assert apply_jq(data, ".results[].publicationNumber") == "EP1A1\nEP2A1"
    assert apply_jq(data, ".results[0].publicationNumber") == "EP1A1"
    assert apply_jq(data, ".results[-1].title") == "y"
    assert apply_jq(data, ".results[] | .publicationNumber") == "EP1A1\nEP2A1"
    assert apply_jq([{"pn": "EP1A1"}, {"pn": "EP2A1"}], ".[] | .pn") == "EP1A1\nEP2A1"
    assert apply_jq(data, ".results[] | .title") == "x\ny"
    assert apply_jq({"claims": [{"number": 1, "text": "a"}, {"number": 2, "text": "b"}]},
                    ".claims[].number") == "1\n2"


def test_apply_jq_edge_cases():
    assert apply_jq({"results": []}, ".results[].publicationNumber") == ""  # 空列表合法
    assert apply_jq({"a": None}, ".a.b") == "null"  # 缺键沿 null 传播（jq 语义）
    assert apply_jq({"m": {"x": 1}}, ".m") == '{"x": 1}'  # 非字符串结果输出紧凑 JSON
    with pytest.raises(CliError):  # 对 null 迭代报错（抓拼写错误）
        apply_jq({}, ".results[].publicationNumber")
    with pytest.raises(CliError):  # 不支持的语法
        apply_jq({}, ".results | map(.x)")
    with pytest.raises(CliError):  # 空阶段 / 裸词
        apply_jq({}, ".a |")
        apply_jq({}, "foo.b")


def test_search_unknown_json_field_fails_fast():
    """字段表拼错必须在触达 Edge/检索配额之前报错。"""
    from click.testing import CliRunner

    from espacenet_cli.cli import cli

    result = CliRunner().invoke(cli, ["search", "ti=x", "--json", "nope"],
                                standalone_mode=False)
    assert isinstance(result.exception, CliError)
    assert "nope" in str(result.exception)


# ------------------------------------------------------------ edge_backend.py

def test_build_edge_launch_args_visible():
    args = build_edge_launch_args("C:/prof", 9333, "visible")
    assert "--user-data-dir=C:/prof" in args
    assert "--remote-debugging-port=9333" in args
    assert "--start-maximized" in args
    assert "--headless=new" not in args


def test_build_edge_launch_args_background():
    args = build_edge_launch_args("C:/prof", 9333, "background")
    assert "--headless=new" in args and "--window-size=1600,1000" in args


def test_build_edge_launch_args_requires_profile():
    with pytest.raises(CliError):
        build_edge_launch_args("", 9333)


def test_make_trace_id_shape():
    trace = make_trace_id()
    parts = trace.split("-")
    assert len(parts) == 4 and len(parts[0]) == 6 and len(parts[1]) == 6 and parts[2] == "AAA"
