# -*- coding: utf-8 -*-
r"""
vault_audit.py — vault 連結、metadata、時效與 runtime artifact 審計（唯讀，不改任何檔）

vault 位置讀 repo 根的 office.yaml（或 --config／環境變數 YKKB_OFFICE_CONFIG 指定的檔）。

檢查項目（依輸出段落順序）：
  0. 解析與格式錯誤：YAML 解析錯誤、enum 錯誤、欄位型別／日期／時間／官方網址／辦公室代碼格式錯誤
     （有任一項時結束碼為 1）；另列暫存區（80_Inbox／81_Processed／82_Review）獨立統計，不併入健康度。
  1. 限制級資料未標記：限制級目錄（office.yaml 的 restricted_dir_names，任一層命中）內的筆記
     須標 `sensitivity: restricted`。
  2. sensitivity 欄位值分布、限制級總數，以及無法辨識的值（比照限制級擋下檢索，需改為標準值）。
  3. 壞連結：[[wikilink]] 指向不存在的筆記（Obsidian 以「檔名不含.md」解析）。
     共用唯讀區（shared_dirs 或任一層名為 _shared 的資料夾）內的壞連結另列「共用區連結未解析」，
     屬資訊、不算錯誤：共用法規筆記會連到總部的案件筆記，在其他辦公室本來就解析不到。
  4. 同名衝突：同一檔名出現在多個資料夾 → wikilink 會歧義（CLAUDE.md、README_唯讀.md 為預期例外）。
     其中一份在共用區者另列「共用區與本地同名」。
  5. 非預期孤兒：入站與出站連結皆為 0 的筆記；已排除刻意設計者（02 審議層 Cases、限制級目錄、
     Inbox/Processed/Review、_ 前綴工作檔、00_Index 入口／索引資料夾、共用唯讀區）。
  6. 知識深度債務（frontmatter `depth:`）：骨架→待補卷、文件萃取→待落地、深度訪談→已落地；另列非標準值。
  7. 案件 schema 遷移：`lifecycle/source_depth/authority/as_of` 缺漏篇數。
  8. 執行中案件時效（03_案件經驗知識層/50_執行中案件；資料夾不存在則略過）：以 `as_of` 判斷，
     超過 14 日列待重掃；缺 `as_of` 者列「待承辦確認」，不以 `updated` 代填。
  9. 法規 schema 遷移：`legal_status/jurisdiction/verified_at/official_url` 原始缺漏與相容讀取後仍缺篇數。
  10. skills 快照中的 runtime artifact（01_AI協作共用知識/20_Workflows/claude-skills；不存在則略過）。
  11. 共用唯讀區同步狀態：.sync_manifest.json（或 README_唯讀.md）記錄的來源 commit 與 repo HEAD
      不同時示警「vault 落後於 repo」（資訊，不算錯誤）。
  office.yaml 設 require_office_field: true 時，案件筆記缺 office、office 不符或 case_id 未以
  「<office_code>-」開頭，列為格式錯誤。

用法：python -X utf8 core/tools/vault_audit.py [--config office.yaml]
結束碼：0 = 無格式錯誤；1 = 有格式錯誤；2 = 設定錯誤或找不到 vault。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ykkb import config as office_config  # noqa: E402
from ykkb.metadata import (COMMITTEE_LAYER, in_restricted_dir, is_restricted,  # noqa: E402
                           is_restricted_dir_name, normalize_metadata, sensitivity_state,
                           split_frontmatter)
from ykkb.validation import load_schema, strict_date, validate_metadata  # noqa: E402

# claude-skills：技能包（參考檔用相對路徑不用 wikilink），屬工具非知識庫筆記，不納入連結審計。
# build artifact（.pytest_cache/__pycache__/node_modules 等）：投放程式碼時會夾帶，一律略過。
SKIP_DIRS = {
    ".obsidian", ".trash", "90_Archive", "claude-skills",
    ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".ipynb_checkpoints", "node_modules", ".venv", "venv", ".git",
}
# sync_to_vault.py 中斷時可能留下的暫存／舊資料夾（.<名稱>.sync_tmp_<時間>），不算筆記
SYNC_TEMP_MARKS = (".sync_tmp_", ".sync_old_")
SHARED_SEGMENT = "_shared"
SHARED_README_STEM = "README_唯讀"
DUP_EXEMPT = {"CLAUDE", SHARED_README_STEM}

link_re = re.compile(r'\[\[([^\]\|#\n]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]')
code_fence = re.compile(r'```.*?```', re.S)
inline_code = re.compile(r'`[^`\n]*`')

CASE_LAYER = "03_案件經驗知識層"
CASE_DIR_PREFIXES = tuple(
    f"{CASE_LAYER}/{name}"
    for name in (
        "10_變更編定", "11_開發許可", "12_變更開發計畫", "13_容許使用",
        "14_漁電共生", "15_變更環評", "16_興辦事業計畫變更", "50_執行中案件",
    )
)
ACTIVE_CASE_PREFIX = f"{CASE_LAYER}/50_執行中案件"
LEGAL_NOTE_PREFIX = f"{CASE_LAYER}/71_核心法規全文"
SKILLS_SNAPSHOT_REL = "01_AI協作共用知識/20_Workflows/claude-skills"
# 入口／索引資料夾（任一層名為 00_Index）：新建 vault 的總入口還沒有任何連結，屬刻意設計，不列孤兒
INDEX_DIR = "00_Index"
ORPHAN_BY_DESIGN_PREFIX = (f"{COMMITTEE_LAYER}/10_Cases", "80_Inbox", "81_Processed", "82_Review")
RUNTIME_DIRS = {
    "cache", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".ipynb_checkpoints", "node_modules", ".venv", "venv",
}
RUNTIME_SUFFIXES = {".pyc", ".pyo"}
CASE_SCHEMA_FIELDS = ("lifecycle", "source_depth", "authority", "as_of")
LEGAL_SCHEMA_FIELDS = ("legal_status", "jurisdiction", "verified_at", "official_url")
VALID_LEGACY_DEPTHS = {"骨架", "骨架（待補卷）", "文件萃取", "深度訪談"}
ACTIVE_STALE_DAYS = 14
STAGING_PREFIXES = ("80_Inbox", "81_Processed", "82_Review")
TERMINAL_LIFECYCLES = {"terminated", "rejected", "completed", "archived"}


def _rel(path: str, vault: str) -> str:
    return PurePosixPath(*Path(os.path.relpath(path, vault)).parts).as_posix()


def make_shared_matcher(shared_dirs):
    """共用唯讀區判定：位於 office.yaml shared_dirs 底下，或任一層目錄名為 _shared（不分大小寫）。"""
    prefixes = tuple(value.casefold().rstrip("/") + "/" for value in (shared_dirs or {}).values())

    def is_shared(rel: str) -> bool:
        folded = rel.casefold()
        if folded.startswith(prefixes):
            return True
        return any(part.casefold() == SHARED_SEGMENT for part in PurePosixPath(rel).parts[:-1])

    return is_shared


def scan_runtime_artifacts(vault: str):
    """回傳 skills 快照內 runtime artifact 的路徑、檔案數與 bytes；快照資料夾不存在回傳 None。"""
    snapshot = os.path.join(vault, *SKILLS_SNAPSHOT_REL.split("/"))
    if not os.path.isdir(snapshot):
        return None
    found = []
    for root, dirs, fnames in os.walk(snapshot):
        for dirname in list(dirs):
            if dirname in RUNTIME_DIRS:
                path = os.path.join(root, dirname)
                file_count = 0
                total_bytes = 0
                for subroot, _, subfiles in os.walk(path):
                    for name in subfiles:
                        file_count += 1
                        try:
                            total_bytes += os.path.getsize(os.path.join(subroot, name))
                        except OSError:
                            pass
                found.append((_rel(path, vault), file_count, total_bytes))
                dirs.remove(dirname)
        for name in fnames:
            if os.path.splitext(name)[1].lower() in RUNTIME_SUFFIXES:
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                found.append((_rel(path, vault), 1, size))
    return found


SYNC_MANIFEST = ".sync_manifest.json"
SYNC_README = "README_唯讀.md"
_README_COMMIT = re.compile(r"來源 commit：\s*(\S+)")


def git_head(repo_root) -> str:
    """repo 目前的 commit；取不到回傳 unknown。"""
    try:
        result = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    head = result.stdout.strip()
    return head if result.returncode == 0 and len(head) >= 7 else "unknown"


def recorded_commit(target: str) -> str | None:
    """唯讀區記錄的來源 commit：先讀 .sync_manifest.json，再退回 README_唯讀.md；都沒有回傳 None。"""
    manifest = os.path.join(target, SYNC_MANIFEST)
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as handle:
                value = json.load(handle).get("source_commit")
            if isinstance(value, str) and value:
                return value
        except (OSError, ValueError, AttributeError):
            pass
    readme = os.path.join(target, SYNC_README)
    if os.path.isfile(readme):
        with open(readme, encoding="utf-8", errors="replace") as handle:
            match = _README_COMMIT.search(handle.read())
        if match:
            return match[1]
    return None


def sync_status_lines(cfg: dict, *, repo_head=git_head) -> list[str]:
    """比對各唯讀區記錄的來源 commit 與 repo HEAD，落後時示警（不算錯誤）。"""
    vault = cfg["vault_root"]
    head = repo_head(cfg.get("repo_root") or office_config.REPO_ROOT)
    lines = []
    for key, rel in sorted((cfg.get("shared_dirs") or {}).items()):
        target = os.path.join(vault, *rel.split("/"))
        if not os.path.isdir(target):
            lines.append(f"[{key}] 尚未同步（{rel} 不存在）；請跑 python -X utf8 core/tools/sync_to_vault.py")
            continue
        recorded = recorded_commit(target)
        if recorded is None:
            lines.append(f"[{key}] 找不到同步紀錄（{SYNC_MANIFEST}／{SYNC_README}）；請跑 sync_to_vault.py")
        elif head == "unknown":
            lines.append(f"[{key}] 同步自 {recorded[:12]}；無法取得 repo commit，未比對")
        elif recorded == "unknown" or recorded != head:
            lines.append(f"[{key}] ⚠ vault 落後於 repo（同步自 {recorded[:12]}，repo 為 {head[:12]}），"
                         "請跑 python -X utf8 core/tools/sync_to_vault.py")
        else:
            lines.append(f"[{key}] 已與 repo 同步（{head[:12]}）")
    return lines


def run_audit(cfg: dict, *, skip_restricted_dirs: bool = False, today: date | None = None,
              repo_head=git_head) -> int:
    vault = cfg["vault_root"]
    if not os.path.isdir(vault):
        print(f"[錯誤] 找不到 vault：{vault}")
        return 2
    restricted_names = tuple(cfg.get("restricted_dir_names") or office_config.restricted_dir_names())
    office_codes = set(cfg.get("office_codes") or ()) or None
    required_office = cfg.get("office_code") if cfg.get("require_office_field") else None
    is_shared = make_shared_matcher(cfg.get("shared_dirs"))

    notes = {}     # basename(no .md) -> [relpath, ...]
    files = []     # (relpath, fullpath)
    staging_files = []
    for root, dirs, fnames in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and not any(mark in d for mark in SYNC_TEMP_MARKS)
                   and not (skip_restricted_dirs and is_restricted_dir_name(d, restricted_names))]
        for fn in fnames:
            if fn.lower().endswith(".md"):
                p = os.path.join(root, fn)
                rel = _rel(p, vault)
                if rel.startswith(STAGING_PREFIXES):
                    staging_files.append((rel, p))
                    continue
                files.append((rel, p))
                notes.setdefault(fn[:-3], []).append(rel)

    links = []       # (src_rel, target)
    skeletons, pending, done = [], [], []
    case_notes = []
    active_stale = []
    terminal_stale = []
    yaml_errors = []
    enum_errors = []
    field_errors = []
    full_schema_missing = collections.Counter()
    active_missing_as_of = []
    active_pending_owner = []
    active_missing_source_last_modified = []
    active_review_status = collections.Counter()
    unknown_depths = []
    case_schema_missing = collections.Counter()
    legal_schema_missing = collections.Counter()
    legal_compatible_missing = collections.Counter()
    restricted_unmarked = []
    sensitivity_values = collections.Counter()
    sensitivity_unrecognized = []
    restricted_total = 0
    shared_notes = 0
    schema = load_schema()
    today = today or date.today()
    for rel, p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        try:
            meta = split_frontmatter(txt)[0]
        except ValueError as exc:
            yaml_errors.append((rel, str(exc)))
            meta = {}
        if is_shared(rel):
            shared_notes += 1
        depth_value = meta.get("depth")
        # 只認已解析的 frontmatter（不對全文做正則，避免內文程式碼範例裡的 depth: 行誤計）
        depth_text = depth_value.strip() if isinstance(depth_value, str) else ""
        if depth_text.startswith("骨架"):
            skeletons.append(rel)
        elif depth_text.startswith("文件萃取"):
            pending.append(rel)
        elif depth_text.startswith("深度訪談"):
            done.append(rel)
        if depth_value and (not isinstance(depth_value, str) or depth_value not in VALID_LEGACY_DEPTHS):
            unknown_depths.append((rel, depth_value))
        basename = os.path.basename(rel)
        if (in_restricted_dir(PurePosixPath(rel).parts[:-1], restricted_names) and basename != "CLAUDE.md"
                and not basename.startswith("_") and sensitivity_state(meta) != "restricted"):
            restricted_unmarked.append(rel)
        state = sensitivity_state(meta)
        if state != "absent":
            raw = meta.get("sensitivity")
            sensitivity_values[repr(raw) if isinstance(raw, str) else f"<{type(raw).__name__}>"] += 1
            if state == "unrecognized":
                sensitivity_unrecognized.append((rel, raw))
        if is_restricted(meta):
            restricted_total += 1
        is_case_note = (
            rel.startswith(CASE_DIR_PREFIXES)
            and basename != "CLAUDE.md"
            and not basename.startswith("_")
            and "總索引" not in basename
        )
        if is_case_note:
            validation = validate_metadata(meta, 'case_note', schema, rel, office_codes, required_office)
            for issue in validation['errors']:
                bucket = enum_errors if issue['code'] == 'invalid_enum' else field_errors
                bucket.append((rel, issue['field'], issue['code']))
            full_schema_missing.update(('case_note.' + field) for field in validation['raw_missing'])
            case_notes.append(rel)
            for field in CASE_SCHEMA_FIELDS:
                if not meta.get(field):
                    case_schema_missing[field] += 1
            if rel.startswith(ACTIVE_CASE_PREFIX):
                if not meta.get("as_of"):
                    active_missing_as_of.append(rel)
                if not meta.get("source_last_modified"):
                    active_missing_source_last_modified.append(rel)
                review = meta.get("review_status")
                active_review_status[(review or "missing") if isinstance(review, str) or review is None else 'invalid_type'] += 1
                # as_of 缺漏：列「待承辦確認」，不以 updated 代填判斷逾期
                snapshot_date = strict_date(meta.get("as_of"))
                stale_bucket = terminal_stale if meta.get("lifecycle") in tuple(TERMINAL_LIFECYCLES) else active_stale
                if not meta.get("as_of"):
                    active_pending_owner.append(rel)
                elif snapshot_date is None:
                    stale_bucket.append((rel, None))
                else:
                    age = (today - snapshot_date).days
                    if age > ACTIVE_STALE_DAYS:
                        stale_bucket.append((rel, age))
        if rel.startswith(LEGAL_NOTE_PREFIX) and basename != "CLAUDE.md" and not basename.startswith("_") and meta.get("type") != "index":
            validation = validate_metadata(meta, 'legal_note', schema, rel, office_codes)
            for issue in validation['errors']:
                bucket = enum_errors if issue['code'] == 'invalid_enum' else field_errors
                bucket.append((rel, issue['field'], issue['code']))
            full_schema_missing.update(('legal_note.' + field) for field in validation['raw_missing'])
            normalized = normalize_metadata(meta, rel)
            for field in LEGAL_SCHEMA_FIELDS:
                # 無公開官方來源且填了理由者（schema required_alternatives）不算缺漏
                if field not in validation['raw_missing'] and not meta.get(field):
                    continue
                if not meta.get(field):
                    legal_schema_missing[field] += 1
                if not normalized.get(field):
                    legal_compatible_missing[field] += 1
        body = inline_code.sub("", code_fence.sub("", txt))
        for m in link_re.finditer(body):
            t = m.group(1).strip()
            if t:
                links.append((rel, t))

    broken = collections.defaultdict(list)
    shared_unresolved = collections.defaultdict(list)
    staging_broken = set()
    staging_names = {Path(p).stem for _, p in staging_files}
    for rel, p in staging_files:
        txt = Path(p).read_text(encoding="utf-8", errors="replace")
        for match in link_re.finditer(inline_code.sub("", code_fence.sub("", txt))):
            target = match.group(1).strip()
            if target not in notes and target not in staging_names:
                staging_broken.add(target)
    for s, t in links:
        if t not in notes:
            (shared_unresolved if is_shared(s) else broken)[t].append(s)

    inbound = collections.Counter(t for _, t in links if t in notes)
    outbound = collections.Counter(s for s, t in links if t in notes)
    all_dups = {b: ps for b, ps in notes.items() if len(ps) > 1 and b not in DUP_EXEMPT}
    shared_dups = {b: ps for b, ps in all_dups.items() if any(is_shared(p) for p in ps)}
    dups = {b: ps for b, ps in all_dups.items() if b not in shared_dups}

    orphans = []
    for b, ps in sorted(notes.items()):
        rel = ps[0]
        if inbound[b] == 0 and outbound[rel] == 0:
            if (b == "CLAUDE" or b.startswith("_") or rel.startswith(ORPHAN_BY_DESIGN_PREFIX)
                    or in_restricted_dir(PurePosixPath(rel).parts[:-1], restricted_names)
                    or is_shared(rel) or INDEX_DIR in PurePosixPath(rel).parts[:-1]):
                continue
            orphans.append(rel)

    office = cfg.get("office_code", "?")
    print("=" * 64)
    if skip_restricted_dirs:
        print("⚠ 已依 --skip-restricted-dirs 略過限制級目錄：該目錄的標記檢查未執行，僅供不讀限制級資料的對照用。")
    print(f"暫存區獨立統計：{len(staging_files)} 篇、{len(staging_broken)} 個斷鏈目標（不併入正式健康度）")
    print(f"YAML 解析錯誤：{len(yaml_errors)}；enum 錯誤：{len(enum_errors)}")
    print(f"欄位型別／日期／時間／官方網址格式錯誤：{len(field_errors)}（不包含證據缺漏）")
    for error in yaml_errors + enum_errors + field_errors:
        print("   ", error)
    print("完整 schema 必填缺漏（逐欄篇數，不是錯誤值）：" + str(dict(sorted(full_schema_missing.items()))))
    print(f"vault 審計（{office}）｜筆記 {len(files)} 篇（共用唯讀區 {shared_notes} 篇）、wikilink {len(links)} 個")
    print("=" * 64)

    print(f"\n■ 限制級資料未標記（應有 sensitivity: restricted）：{len(restricted_unmarked)} 篇")
    if restricted_unmarked:
        print("   ⚠ 這些筆記只靠目錄名擋住檢索，資料層過濾擋不到——目錄一改名即外洩。")
        for rel in sorted(restricted_unmarked)[:12]:
            print(f"        {rel}")
        if len(restricted_unmarked) > 12:
            print(f"        …另 {len(restricted_unmarked) - 12} 篇")

    print(f"\n■ sensitivity 欄位值分布（限制級總數 {restricted_total} 篇，含無法辨識值）：")
    if sensitivity_values:
        for value, count in sorted(sensitivity_values.items()):
            print(f"   {value}: {count} 篇")
    else:
        print("   （全 vault 無 sensitivity 欄位）")
    print(f"■ sensitivity 值無法辨識（已比照限制級擋下檢索，需改為標準值）：{len(sensitivity_unrecognized)} 篇")
    for rel, raw in sorted(sensitivity_unrecognized, key=lambda item: item[0]):
        print(f"        {rel} → {raw!r}")

    print(f"\n■ 壞連結（指向不存在筆記）：{len(broken)} 個目標")
    for t in sorted(broken):
        print(f"   [[{t}]] ← 被 {len(set(broken[t]))} 檔引用")
        for s in sorted(set(broken[t]))[:8]:
            print(f"        {s}")

    print(f"\n■ 共用區連結未解析（資訊，不算錯誤；共用筆記連到其他辦公室的筆記）：{len(shared_unresolved)} 個目標")
    for t in sorted(shared_unresolved)[:20]:
        print(f"   [[{t}]] ← 被 {len(set(shared_unresolved[t]))} 檔引用")
    if len(shared_unresolved) > 20:
        print(f"   …另 {len(shared_unresolved) - 20} 個目標")

    print(f"\n■ 同名衝突（CLAUDE.md、README_唯讀.md 除外）：{len(dups)} 組")
    for b, ps in sorted(dups.items()):
        print(f"   {b}")
        for x in ps:
            print(f"        {x}")
    print(f"■ 共用區與本地同名（wikilink 會歧義；建議移除或改名本地副本，共用區勿改）：{len(shared_dups)} 組")
    for b, ps in sorted(shared_dups.items()):
        print(f"   {b}")
        for x in ps:
            print(f"        {x}")

    print(f"\n■ 非預期孤兒（已排除刻意設計者）：{len(orphans)} 篇")
    for rel in orphans:
        print(f"   {rel}")

    print(f"\n■ 待補卷（depth: 骨架，尚未讀原始書件）：{len(skeletons)} 篇")
    for rel in sorted(skeletons):
        print(f"   {rel}")

    print(f"\n■ 待落地（depth: 文件萃取，文件已備、待與承辦同仁深度訪談）：{len(pending)} 篇")
    for rel in sorted(pending):
        print(f"   {rel}")

    print(f"\n■ 已落地（depth: 深度訪談）：{len(done)} 篇")
    for rel in sorted(done):
        print(f"   {rel}")

    print(f"\n■ 案件 schema 遷移（規格：core/knowledge_schema.yaml）：{len(case_notes)} 篇納管")
    for field in CASE_SCHEMA_FIELDS:
        print(f"   缺 {field}: {case_schema_missing[field]} 篇")
    print(f"   非標準 legacy depth: {len(unknown_depths)} 篇")
    for rel, value in sorted(unknown_depths, key=lambda item: item[0]):
        print(f"        {rel} → {value}")

    active_dir = os.path.join(vault, *ACTIVE_CASE_PREFIX.split("/"))
    if not os.path.isdir(active_dir):
        print(f"\n■ 執行中案件時效：略過（本 vault 無 {ACTIVE_CASE_PREFIX} 資料夾）")
    else:
        print(f"\n■ 執行中案件時效（>{ACTIVE_STALE_DAYS} 日未確認）：{len(active_stale)} 篇")
        print(f"   終局案件另列定期覆核：{len(terminal_stale)} 篇（不算執行中逾期；核准 approved 不自動視為結案）")
        print(f"   缺 as_of（不以 updated 代填，不納入逾期判斷）：{len(active_missing_as_of)} 篇")
        print(f"   待承辦確認（as_of 缺漏、時效未判）：{len(active_pending_owner)} 篇")
        for rel in sorted(active_pending_owner)[:20]:
            print(f"        {rel}")
        if len(active_pending_owner) > 20:
            print(f"        …另 {len(active_pending_owner) - 20} 篇")
        print(f"   缺 source_last_modified：{len(active_missing_source_last_modified)} 篇")
        print("   review_status：" + "｜".join(
            f"{status} {count}" for status, count in sorted(active_review_status.items())
        ))
        for rel, age in sorted(active_stale, key=lambda item: (-1 if item[1] is None else -item[1], item[0]))[:20]:
            label = "日期無法判讀" if age is None else f"{age} 日"
            print(f"        {rel} → {label}")
        if len(active_stale) > 20:
            print(f"        …另 {len(active_stale) - 20} 篇")

    print("\n■ 法規 schema 遷移（71_核心法規全文，含共用唯讀區）")
    for field in LEGAL_SCHEMA_FIELDS:
        print(f"   原始缺 {field}: {legal_schema_missing[field]} 篇；相容讀取後仍缺 {legal_compatible_missing[field]} 篇")

    runtime_artifacts = scan_runtime_artifacts(vault)
    if runtime_artifacts is None:
        runtime_artifacts = []
        print(f"\n■ skills runtime artifact：略過（本 vault 無 {SKILLS_SNAPSHOT_REL} 資料夾）")
    else:
        runtime_files = sum(item[1] for item in runtime_artifacts)
        runtime_bytes = sum(item[2] for item in runtime_artifacts)
        print(f"\n■ skills runtime artifact：{len(runtime_artifacts)} 個路徑｜{runtime_files} 檔｜{runtime_bytes / 1024 / 1024:.1f} MB")
        for rel, count, size in sorted(runtime_artifacts, key=lambda item: item[2], reverse=True):
            print(f"   {rel} → {count} 檔／{size / 1024 / 1024:.1f} MB")
    runtime_bytes = sum(item[2] for item in runtime_artifacts)

    print("\n■ 共用唯讀區同步狀態（資訊，不算錯誤）")
    for line in sync_status_lines(cfg, repo_head=repo_head):
        print("   " + line)

    print("\n" + "=" * 64)
    healthy =(len(broken) == 0 and len(dups) == 0 and len(orphans) == 0)
    print("連結健康度：" + ("✓ 乾淨" if healthy else "⚠ 有待處理項（見上）"))
    print(f"知識深度債務：待補卷 {len(skeletons)} 篇｜待落地 {len(pending)} 篇｜已落地 {len(done)} 篇")
    print(
        f"治理遷移：案件缺 lifecycle {case_schema_missing['lifecycle']} 篇｜"
        f"執行中待重讀 {active_review_status['needs_source_refresh']} 篇｜"
        f"執行中逾期 {len(active_stale)} 篇｜runtime artifact {runtime_bytes / 1024 / 1024:.1f} MB"
    )
    errors = len(yaml_errors) + len(enum_errors) + len(field_errors)
    print(f"格式錯誤合計：{errors}（結束碼 {1 if errors else 0}）")
    print("=" * 64)
    return 1 if errors else 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="vault 健檢（唯讀）")
    parser.add_argument("--config", help="office.yaml 路徑（預設 repo 根 office.yaml 或環境變數 YKKB_OFFICE_CONFIG）")
    parser.add_argument("--skip-restricted-dirs", action="store_true",
                        help="不進入限制級目錄（對照或分享報告用；會略過限制級標記檢查）")
    args = parser.parse_args(argv)
    try:
        cfg = office_config.load_office_config(args.config)
    except office_config.OfficeConfigError as exc:
        print(f"[設定錯誤] {exc}")
        return 2
    return run_audit(cfg, skip_restricted_dirs=args.skip_restricted_dirs)


if __name__ == "__main__":
    sys.exit(main())
