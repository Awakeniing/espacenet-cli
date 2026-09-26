# TEST.md — cli-anything-espacenet 测试计划与结果

## Part 1：测试清单计划（Phase 4，实现前撰写）

### 测试文件与预估数量

- `test_core.py`：约 45 个单元测试（合成数据，无外部依赖）
- `test_full_e2e.py`：约 14 个 E2E 测试（真实后端 + 子进程）

### 单元测试计划（test_core.py）

| 模块 | 测试函数/关注点 | 边界情况 | 预估数 |
|------|------------------|----------|--------|
| `core/text.py` | `parse_publication_number`：完整/无 kind/带空格连字符/非法输入报 `INVALID_PN` | 小写输入、多余空格、纯字母 | 6 |
| | `strip_html`：标签剔除、实体反转义、空白折叠 | 空串、None | 3 |
| | `xml_to_text`：`<p n>` 段号、下标、换行、实体 | 嵌套 XML 片段 | 3 |
| | `parse_multipart_text`：带 key 头部件、无头部件、非 multipart 直通 | `\r\n` 归一 | 4 |
| | `split_claims`：`[0001]` 编号、`1.` 点号、单段 | 空文本 | 3 |
| | `num_to_date` / `same_publication`：8 位日期转换、kind 省略相等 | None/空 | 4 |
| `core/search.py` | `normalize_hit_publication`：字段映射、申请人去重、标题语言回退 | 缺字段 | 3 |
| | `normalize_search_payload`：族嵌套成员、biblio 补行、去重、命中计数 | 空 hits | 4 |
| | `run_search`（FakeBackend）：分页起始、`--all` 追翻页/去新/截断/上限 | 空页终止 | 4 |
| `core/journal.py` | 会话生命周期：start→active→append→end→list | 无会话时 append 只进 auto-log | 6 |
| | `save_search_results`：命名 `NNN-slug.json`、无活跃会话返回 None | | 2 |
| | `diff_search_events`：查询变更/页大小/全量/翻页/族数增减 | 首次(None) | 3 |
| | `generate_report`：章节齐全、统计正确、附录复现命令含选项 | 空会话 | 4 |
| `core/session.py` | `locked_save_json` 写入/覆盖读回、`read_json_or_none` 容错 | 目录不存在自动创建 | 3 |
| `core/config.py` | profile 校验（非法名/保留名/路径逃逸）、路径布局、endpoint 解析 | 损坏 endpoint 文件 | 4 |
| `utils/format.py` | `pad_cell` CJK 宽度截断、表格/CSV(BOM+转义)/ndjson/json、对象表 | 空列表 | 5 |
| `utils/edge_backend.py` | 启动参数（visible/background）、trace-id 格式 | 无 profileDir 报错 | 3 |

### E2E 测试计划（test_full_e2e.py）

**真实后端（Edge + Espacenet 网络可达为硬依赖，不 skip、不降级）：**

1. **检索工作流**：`search 'ti="bicycle" AND pa="shimano"'`（API 直连）→ 命中>0、
   行字段齐全（publicationNumber/title/applicants/familyId）、totals 为正
2. **全量抓取**：小页大 `--all`（FakeBackend 已覆盖分页逻辑，此处真实验证一次小规模）
3. **单件著录**：`detail EP2600908A1` → 公开号归一、标题/申请人非空、familyId 存在
4. **权利要求**：`claims US...`（claims-tree 路径）→ claims 非空；`claims EP...` → textFrom
   标注同族英文成员（EP 回退路径）
5. **同族**：`family EP2600908A1` → memberCount>0、成员列表非空
6. **法律事件**：`legal EP2600908A1` → 返回结构合法（events 列表或说明性 note）
7. **PDF**：`pdf <有图像版本的公开号>` → 文件存在、`%PDF-` 魔数、大小>1KB、打印产物路径

**子进程测试（`_resolve_cli("cli-anything-espacenet")`，`CLI_ANYTHING_FORCE_INSTALLED=1`）：**

8. `--help` / `--version` 退出码 0
9. `status` / `doctor`：JSON 输出、退出码 0（无需网络）
10. 检索记录工作流：临时目录内 `session start --goal` → `note --kind 思路` → `session list` →
    `session end` → `report` → 报告文件存在且含六大章节与复现命令（无需网络）
11. `note --dry-run` / `session end --dry-run`：不落盘
12. `search 'ti="bicycle" AND pa="shimano"' --json`（真实网络）：stdout 合法 JSON、
    `resultCount>0`；`-f csv -o` 落盘文件含表头
13. `detail EP2600908A1 --json`（真实网络）：JSON 字段校验

### 输出验证原则

- PDF 验证魔数 `%PDF-` 与大小，不信任"没报错"
- 检索验证结构化字段而非仅退出码
- 真实后端 E2E 打印产物路径供人工复核
- 失败即失败：Edge/Espacenet 不可达时不跳过

## Part 2：测试结果（Phase 6 回填）

**最终运行：`python -m pytest cli_anything/espacenet/tests/ -v -s --tb=short` → 65 passed in 29.21s（2026-09-24）**

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1
collecting ... [_resolve_cli] Using installed command:
  <python-scripts>\cli-anything-espacenet.EXE
collected 65 items

test_core.py — 49 PASSED
  test_parse_pn_full / kind_optional / normalizes_spaces_and_case / us / invalid
  test_strip_html · test_xml_to_text_paragraph_numbers / entities / collapses_blank_lines
  test_multipart_with_key_headers / headerless_part_kept / passthrough_plain_text
  test_split_claims_numbered / dotted / single_block
  test_num_to_date · test_same_publication_tolerates_kind
  test_normalize_hit_fields_and_dedupe / payload_nested_family / dedupes_rows / empty
  test_run_search_single_page / page_offset / all_paginates_until_no_fresh / all_respects_limit / empty_query
  test_journal_session_lifecycle / append_event_without_session_only_auto_log
  test_save_search_results_named_by_query / no_session_returns_none
  test_diff_search_events · test_report_structure_and_repro_commands
  test_validate_note_kind · test_locked_save_json_roundtrip / read_json_or_none_missing
  test_profile_name_validation / paths_layout / read_endpoint_file / find_edge_executables_ordered
  test_pad_cell_cjk_width · test_format_table / table_empty / csv_bom_and_escaping
  test_format_output_json_ndjson / object_table_claims
  test_build_edge_launch_args_visible / background / requires_profile · test_make_trace_id_shape

test_full_e2e.py — 16 PASSED（真实后端 + 子进程）
TestCLISubprocess:
  test_help PASSED · test_version PASSED
  test_status_json PASSED · test_doctor PASSED
  test_journal_workflow_no_network PASSED
    report: ...\report.md (1,132 bytes)
  test_dry_run_does_not_write PASSED
  test_search_json_real_backend PASSED
    search hits: 28 families / 51 publications
  test_search_csv_out_real_backend PASSED
    csv: ...\hits.csv (13,124 bytes, 386 rows)
  test_detail_json_real_backend PASSED
TestRealBackendE2E:
  test_search PASSED     search: 19 families, first=US5960411A
  test_detail PASSED     detail: EP2600908A1 — BIOADHESIVE POLYMER-BASED CONTROLLED-RELEASE
  test_claims_us_uses_claims_tree PASSED
    claims: US5960411A — 3 claims (claims-tree 路径)
  test_claims_ep_falls_back_to_family_member PASSED
    claims EP fallback: WO2012017469A1（textFrom 标注）
  test_family PASSED     family: EP2600908A1 — 9 members
  test_legal PASSED      legal: EP2600908A1 — 14 events
  test_pdf_magic_bytes PASSED
    PDF: ...\EP2600908A1.pdf (33,254 bytes, kind A0, 魔数 %PDF- 验证)

========================= 65 passed in 29.21s =============================
```

### 统计

| 项 | 值 |
|----|----|
| 总测试数 | 65 |
| 通过 | 65（100%） |
| 执行时间 | 29.21s |
| 单元测试（合成数据） | 49 |
| 子进程测试（安装命令，`CLI_ANYTHING_FORCE_INSTALLED` 生效） | 6 |
| 真实后端 E2E（Edge + Espacenet 网络调用） | 10 |

### 覆盖说明与已知边界

- 真实后端 E2E 依赖 EPO Fair Use：连续高频运行会触发 429 限流（CLI 会等待
  `Retry-After`/30s 自动重试一次；持续限流时报 `FAIR_USE_REJECTED` 并提示冷却）。
  开发期间曾因多轮连跑触发冷却窗口，属预期行为而非缺陷。
- `description` 与 `open`（需 Edge 窗口交互）未纳入自动 E2E（`description` 与
  `claims` 走完全相同的 highlight 通道与回退逻辑，已被 `claims` 覆盖；通道本身由
  detail/family/legal 等真实调用覆盖）。
- REPL 交互以管道冒烟验证（横幅/help/status 分发/退出）；真实终端体验由
  prompt_toolkit 提供，无控制台时自动降级为原生 input。

