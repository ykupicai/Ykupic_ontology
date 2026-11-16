# -*- coding: utf-8 -*-
"""vault_audit：由臺南 test_vault_audit_*.py、test_sensitivity_single_gate.py（稽核段）、
test_knowledge_validation.py（稽核結束碼）移植，另加共用區、空骨架、設定讀取等測試。"""
import contextlib
import io
from datetime import date
from pathlib import Path

import pytest

import vault_audit as audit

CASES = Path("03_案件經驗知識層") / "10_變更編定"
ACTIVE = Path("03_案件經驗知識層") / "50_執行中案件"
LAWS = Path("03_案件經驗知識層") / "71_核心法規全文"
SHARED_LAWS = LAWS / "_shared"
COMMITTEE = Path("02_審議資料庫知識層") / "30_Committees"
GENERAL = Path("03_案件經驗知識層") / "30_通用實務"

RESTRICTED_HEADER = "■ 限制級資料未標記（應有 sensitivity: restricted）："
DIST_HEADER = "■ sensitivity 欄位值分布（限制級總數 "
UNRECOGNIZED_HEADER = "■ sensitivity 值無法辨識（已比照限制級擋下檢索，需改為標準值）："
BROKEN_HEADER = "■ 壞連結（指向不存在筆記）："
SHARED_HEADER = "■ 共用區連結未解析（資訊，不算錯誤；共用筆記連到其他辦公室的筆記）："


def write(vault, folder, name, fm, body="# 筆記\n"):
    path = Path(vault) / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((f"---\n{fm}\n---\n" if fm is not None else "") + body, encoding="utf-8")
    return path


def run(cfg, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = audit.run_audit(cfg, **kwargs)
    return code, out.getvalue()


def count(report, header):
    line = next(l for l in report.splitlines() if l.startswith(header))
    return int(line[len(header):].split(" ")[0])


@pytest.fixture
def office(make_office):
    cfg, _, vault = make_office()
    return cfg, vault


# --- 空骨架、設定 -----------------------------------------------------------------

def test_empty_skeleton_vault_has_zero_errors(office):
    cfg, vault = office
    for folder in ("00_Index", CASES, ACTIVE, LAWS / "_local", COMMITTEE, "80_Inbox_同事投放", "90_Archive"):
        (vault / folder).mkdir(parents=True, exist_ok=True)
    write(vault, "00_Index", "總入口.md", "type: index", "# 入口\n")
    write(vault, "03_案件經驗知識層", "CLAUDE.md", None, "# 規則\n")
    code, report = run(cfg)
    assert code == 0
    assert "格式錯誤合計：0（結束碼 0）" in report
    assert "skills runtime artifact：略過" in report
    assert "連結健康度：✓ 乾淨" in report   # 00_Index 的總入口沒有連結也不算孤兒


def test_main_reads_config_and_returns_2_on_bad_config(make_office, tmp_path, monkeypatch):
    cfg, office_path, vault = make_office()
    from ykkb import config
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)   # 用暫存 offices.yaml
    assert audit.main(["--config", str(office_path)]) == 0
    assert audit.main(["--config", str(tmp_path / "none.yaml")]) == 2


def test_missing_active_folder_is_skipped_with_note(office):
    cfg, vault = office
    write(vault, CASES, "甲.md", "type: case")
    code, report = run(cfg)
    assert code == 0
    assert "執行中案件時效：略過（本 vault 無 03_案件經驗知識層/50_執行中案件 資料夾）" in report


def test_runtime_artifacts_reported_when_snapshot_exists(office):
    cfg, vault = office
    cache = vault / "01_AI協作共用知識" / "20_Workflows" / "claude-skills" / "skill-a" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "x.pyc").write_bytes(b"0" * 10)
    _, report = run(cfg)
    assert "■ skills runtime artifact：1 個路徑｜1 檔" in report


# --- 深度與時效（臺南 test_vault_audit_depth_asof.py） --------------------------------

def test_depth_counted_from_frontmatter_not_body(office):
    cfg, vault = office
    write(vault, CASES, "甲.md", "type: case\ndepth: 骨架（待補卷）")
    write(vault, CASES, "乙.md", "type: case\ndepth: 文件萃取")
    write(vault, CASES, "丙.md", "type: case\ndepth: 深度訪談")
    write(vault, CASES, "丁.md", "type: case", "# 範例\ndepth: 骨架\ndepth: 深度訪談\n")
    _, report = run(cfg)
    assert "■ 待補卷（depth: 骨架，尚未讀原始書件）：1 篇" in report
    assert "■ 待落地（depth: 文件萃取，文件已備、待與承辦同仁深度訪談）：1 篇" in report
    assert "■ 已落地（depth: 深度訪談）：1 篇" in report
    assert "丁.md" not in report.split("■ 待補卷", 1)[1].split("■ 案件 schema", 1)[0]


def test_non_string_depth_does_not_crash(office):
    cfg, vault = office
    write(vault, CASES, "戊.md", "type: case\ndepth: [骨架]")
    _, report = run(cfg)
    assert "■ 待補卷（depth: 骨架，尚未讀原始書件）：0 篇" in report


def test_missing_as_of_not_judged_by_updated(office):
    cfg, vault = office
    write(vault, ACTIVE, "無日期.md", "type: case-active\nlifecycle: active\nupdated: 2020-01-01")
    write(vault, ACTIVE, "舊日期.md", "type: case-active\nlifecycle: active\nas_of: 2020-01-01")
    _, report = run(cfg, today=date(2026, 11, 16))
    assert "■ 執行中案件時效（>14 日未確認）：1 篇" in report
    assert "待承辦確認（as_of 缺漏、時效未判）：1 篇" in report
    assert "缺 as_of（不以 updated 代填，不納入逾期判斷）：1 篇" in report
    stale = report.split("■ 執行中案件時效", 1)[1].split("■ 法規", 1)[0]
    assert "舊日期.md → " in stale


# --- 限制級（臺南 test_vault_audit_restricted.py、test_sensitivity_single_gate.py） -------

def test_unmarked_committee_note_is_reported(office):
    cfg, vault = office
    write(vault, COMMITTEE, "M001 已標記.md", "type: committee-profile\nsensitivity: restricted")
    write(vault, COMMITTEE, "M002 漏標記.md", "type: committee-profile")
    _, report = run(cfg)
    assert count(report, RESTRICTED_HEADER) == 1
    section = report.split(RESTRICTED_HEADER, 1)[1].split("■", 1)[0]
    assert "M002 漏標記.md" in section and "M001 已標記.md" not in section


def test_wrong_value_counts_as_unmarked(office):
    cfg, vault = office
    write(vault, COMMITTEE, "M003 標錯值.md", "type: committee-profile\nsensitivity: internal")
    assert count(run(cfg)[1], RESTRICTED_HEADER) == 1


def test_fully_marked_directory_reports_zero_not_skipped(office):
    cfg, vault = office
    write(vault, COMMITTEE, "M001.md", "type: committee-profile\nsensitivity: restricted")
    _, report = run(cfg)
    assert RESTRICTED_HEADER in report
    assert count(report, RESTRICTED_HEADER) == 0


def test_restricted_dir_names_read_from_config(make_office, tmp_path):
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: TP\nvault_root: {vault.as_posix()}\nrestricted_dir_names: [99_機密]\n")
    write(vault, "99_機密", "甲.md", "type: x")
    write(vault, COMMITTEE, "乙.md", "type: x")   # 不在本辦公室設定的限制級目錄名內
    _, report = run(cfg)
    assert count(report, RESTRICTED_HEADER) == 1
    section = report.split(RESTRICTED_HEADER, 1)[1].split("■", 1)[0]
    assert "甲.md" in section and "乙.md" not in section


def test_skip_restricted_dirs_does_not_enter(office):
    cfg, vault = office
    write(vault, COMMITTEE, "M002 漏標記.md", "type: committee-profile")
    code, report = run(cfg, skip_restricted_dirs=True)
    assert "M002" not in report
    assert "已依 --skip-restricted-dirs 略過限制級目錄" in report


def test_audit_reports_distribution_and_unrecognized(office):
    cfg, vault = office
    write(vault, GENERAL, "A.md", "sensitivity: restricted")
    write(vault, GENERAL, "B.md", "sensitivity: restricted")
    write(vault, GENERAL, "C.md", "sensitivity: Restricted")
    write(vault, GENERAL, "D.md", "sensitivity: secret")
    write(vault, GENERAL, "E.md", "sensitivity: internal")
    write(vault, GENERAL, "F.md", "sensitivity: [x]")
    write(vault, GENERAL, "G.md", None)
    _, report = run(cfg)
    dist_line = next(l for l in report.splitlines() if l.startswith(DIST_HEADER))
    assert dist_line.startswith(DIST_HEADER + "5 篇")
    assert "   'restricted': 2 篇" in report
    assert "   'Restricted': 1 篇" in report
    assert "   'internal': 1 篇" in report
    assert "   <list>: 1 篇" in report
    assert count(report, UNRECOGNIZED_HEADER) == 2
    section = report.split(UNRECOGNIZED_HEADER, 1)[1].split("■", 1)[0]
    assert "D.md" in section and "F.md" in section and "C.md" not in section


def test_audit_reports_zero_when_no_sensitivity(office):
    cfg, vault = office
    write(vault, GENERAL, "G.md", None)
    _, report = run(cfg)
    assert DIST_HEADER + "0 篇" in report
    assert UNRECOGNIZED_HEADER + "0 篇" in report


# --- 格式錯誤 → 結束碼 1（臺南 test_audit_and_status_agree_on_invalid_law） -----------

def test_invalid_law_returns_1_and_does_not_modify(office):
    cfg, vault = office
    original = '---\ntype: law-digest\nlegal_status: typo\nverified_at: "2026-02-30"\n---\n本文不變\n'
    path = vault / LAWS / "測試法規.md"
    path.parent.mkdir(parents=True)
    path.write_text(original, encoding="utf-8")
    code, report = run(cfg)
    assert code == 1
    assert path.read_text(encoding="utf-8") == original


def test_yaml_error_returns_1(office):
    cfg, vault = office
    write(vault, GENERAL, "壞.md", "a: 1\na: 2")
    assert run(cfg)[0] == 1


def test_invalid_office_code_in_note_is_error(office):
    cfg, vault = office
    write(vault, CASES, "甲.md", "type: case\noffice: KH")
    code, report = run(cfg)
    assert code == 1 and "invalid_office" in report
    write(vault, CASES, "甲.md", "type: case\noffice: HC\nschema_version: 3.1")
    assert run(cfg)[0] == 0


# --- 共用唯讀區 --------------------------------------------------------------------

def test_shared_broken_links_are_info_not_errors(office):
    cfg, vault = office
    write(vault, SHARED_LAWS, "某法-重點.md", "type: law-digest",
          "見 [[總部案件甲]]、[[另一法-重點]]、[[總部案件乙|別名]]\n")
    write(vault, SHARED_LAWS, "另一法-重點.md", "type: law-digest", "回 [[某法-重點]]\n")
    write(vault, CASES, "本地案.md", "type: case", "連 [[某法-重點]] 與 [[不存在筆記]]\n")
    code, report = run(cfg)
    assert code == 0
    assert count(report, BROKEN_HEADER) == 1
    broken = report.split(BROKEN_HEADER, 1)[1].split("■", 1)[0]
    assert "[[不存在筆記]]" in broken and "總部案件甲" not in broken
    assert count(report, SHARED_HEADER) == 2
    shared = report.split(SHARED_HEADER, 1)[1].split("■", 1)[0]
    assert "[[總部案件甲]]" in shared and "[[總部案件乙]]" in shared


def test_shared_segment_anywhere_counts_as_shared(office):
    cfg, vault = office
    write(vault, Path("01_AI協作共用知識") / "_shared", "共用.md", None, "[[不存在]]\n")
    _, report = run(cfg)
    assert count(report, BROKEN_HEADER) == 0
    assert count(report, SHARED_HEADER) == 1


def test_custom_shared_dir_from_config(make_office, tmp_path):
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {vault.as_posix()}\n"
                            "shared_dirs: {rules: 共用/規則, law_notes: 共用/法規}\n")
    write(vault, Path("共用") / "法規", "法.md", None, "[[總部案件]]\n")
    _, report = run(cfg)
    assert count(report, BROKEN_HEADER) == 0
    assert count(report, SHARED_HEADER) == 1


def test_shared_orphans_and_readme_duplicates_not_reported(office):
    cfg, vault = office
    write(vault, SHARED_LAWS, "孤立法規.md", "type: law-digest", "無連結\n")
    write(vault, SHARED_LAWS, "README_唯讀.md", "type: index", "# 唯讀\n")
    write(vault, Path("03_案件經驗知識層") / "70_法規索引" / "_shared", "README_唯讀.md", "type: index", "# 唯讀\n")
    _, report = run(cfg)
    assert "■ 非預期孤兒（已排除刻意設計者）：0 篇" in report
    assert "■ 同名衝突（CLAUDE.md、README_唯讀.md 除外）：0 組" in report


def test_shared_vs_local_duplicate_listed_separately(office):
    cfg, vault = office
    write(vault, SHARED_LAWS, "某法-重點.md", "type: law-digest")
    write(vault, LAWS, "某法-重點.md", "type: law-digest")
    write(vault, CASES, "甲.md", "type: case", "[[某法-重點]]\n")
    write(vault, CASES / "子", "甲.md", "type: case", "[[某法-重點]]\n")
    _, report = run(cfg)
    assert "■ 同名衝突（CLAUDE.md、README_唯讀.md 除外）：1 組" in report
    assert "■ 共用區與本地同名（wikilink 會歧義；建議移除或改名本地副本，共用區勿改）：1 組" in report


def test_sync_leftover_temp_dirs_are_ignored(office):
    cfg, vault = office
    write(vault, Path("03_案件經驗知識層") / "71_核心法規全文" / "._shared.sync_tmp_20261116", "x.md", "a: 1\na: 2")
    assert run(cfg)[0] == 0


def test_links_in_code_are_ignored(office):
    cfg, vault = office
    write(vault, GENERAL, "說明.md", None, "```\n[[程式碼內]]\n```\n`[[行內]]`\n")
    _, report = run(cfg)
    assert count(report, BROKEN_HEADER) == 0


# --- require_office_field 與健檢 ---------------------------------------------------

def test_require_office_field_makes_case_notes_strict(make_office, tmp_path):
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {vault.as_posix()}\nrequire_office_field: true\n")
    write(vault, CASES, "缺欄.md", "type: case\ncase_id: HC-1")
    write(vault, CASES, "他辦.md", "type: case\noffice: TP\ncase_id: TP-1")
    write(vault, CASES, "正確.md", "type: case\noffice: HC\ncase_id: HC-2026-001")
    code, report = run(cfg)
    assert code == 1
    assert "office_required" in report and "office_mismatch" in report and "id_prefix_mismatch" in report
    assert "正確.md" not in report.split("格式錯誤：", 1)[1].split("完整 schema", 1)[0]


def test_require_office_field_false_keeps_legacy_notes_valid(office):
    cfg, vault = office
    assert cfg["require_office_field"] is False
    write(vault, CASES, "舊案.md", "type: case\ncase_id: 2025-舊案")
    assert run(cfg)[0] == 0