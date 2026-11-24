"""自行轉正（review_mode: self）與抽查欄（2026-11-23 起）。暫存假 repo，不動真 repo、不連外網。"""
import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules_support as sup  # noqa: E402
from ykkb import rules as rl  # noqa: E402

URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"


@pytest.fixture
def repo(tmp_path):
    return sup.build_repo(tmp_path / "repo")


def promoted(rule_id="GEN-003", **ext):
    base = {"added_by": "HC", "reviewed_by": "HC", "reviewed_at": "2026-11-23", "source_url": URL}
    base.update(ext)
    return sup.make_rule(rule_id, **base)


def write_and_check(root, data, folder="national"):
    sup.write_rule(root, folder, data)
    sup.export(root)
    return sup.check(root)


# ---------------------------------------------------------------- 靜態檢查

def test_self_review_passes(repo):
    code, out = write_and_check(repo, promoted(review_mode="self"))
    assert code == 0, out


def test_self_review_local_passes(repo):
    data = promoted("TNN-900", added_by="TN", reviewed_by="TN", review_mode="self")
    data["法規代碼"] = "GL000306(臺南市)"
    code, out = write_and_check(repo, data, folder="local/TNN")
    assert code == 0, out


def test_same_office_marked_peer_blocked(repo):
    code, out = write_and_check(repo, promoted(review_mode="peer"))
    assert code == 1 and "[轉正]" in out and "review_mode 應為 self" in out


def test_other_office_marked_self_blocked(repo):
    code, out = write_and_check(repo, promoted(reviewed_by="TN", review_mode="self"))
    assert code == 1 and "[轉正]" in out and "review_mode 應為 peer" in out


@pytest.mark.parametrize("drop_key", [False, True])
def test_reviewed_without_mode_blocked(repo, drop_key):
    data = promoted(reviewed_by="TN", review_mode=None)
    if drop_key:
        del data["review_mode"]
    code, out = write_and_check(repo, data)
    assert code == 1 and "缺 review_mode" in out and "review_mode: peer" in out


def test_mode_without_reviewer_blocked(repo):
    data = sup.make_rule("XHC-1", added_by="HC", source_url=URL, review_mode="self")
    code, out = write_and_check(repo, data, folder="pending/HC")
    assert code == 1 and "reviewed_by 空白，review_mode 卻填了" in out


def test_invalid_mode_blocked(repo):
    code, out = write_and_check(repo, promoted(review_mode="自己"))
    assert code == 1 and "[enum 非法]" in out and "review_mode" in out


def test_legacy_rule_needs_no_mode(repo):
    code, out = sup.check(repo)   # build_repo 的 GEN-001、TNN-001 是 legacy、沒有 review_mode
    assert code == 0, out
    assert "review_mode" not in (repo / "rules/national/GEN-001.yaml").read_text(encoding="utf-8")


def test_spot_check_on_self_rule_passes(repo):
    data = promoted(review_mode="self", spot_checked_at="2026-12-01", spot_check_note="與官方原文一致")
    code, out = write_and_check(repo, data)
    assert code == 0, out


def test_spot_check_on_peer_rule_blocked(repo):
    data = promoted(reviewed_by="TN", review_mode="peer", spot_checked_at="2026-12-01")
    code, out = write_and_check(repo, data)
    assert code == 1 and "[抽查]" in out


def test_spot_note_on_peer_rule_blocked(repo):
    data = promoted(reviewed_by="TN", review_mode="peer", spot_check_note="與官方原文一致")
    code, out = write_and_check(repo, data)
    assert code == 1 and "[抽查]" in out


def test_spot_check_on_pending_rule_blocked(repo):
    data = sup.make_rule("XHC-1", added_by="HC", source_url=URL, spot_checked_at="2026-12-01")
    code, out = write_and_check(repo, data, folder="pending/HC")
    assert code == 1 and "[抽查]" in out


@pytest.mark.parametrize("value", ["2026/12/01", "2026-13-01", "上週"])
def test_spot_check_date_format_blocked(repo, value):
    code, out = write_and_check(repo, promoted(review_mode="self", spot_checked_at=value))
    assert code == 1 and "spot_checked_at" in out and "YYYY-MM-DD" in out


def test_ci_mode_applies_same_rule(repo):
    sup.write_rule(repo, "national", promoted(review_mode="peer"))
    sup.export(repo)
    code, out = sup.check(repo, mode="ci")
    assert code == 1 and "review_mode 應為 self" in out


# ---------------------------------------------------------------- pre-push（git）

needs_git = pytest.mark.skipif(not sup.has_git(), reason="需要 git")


@pytest.fixture
def git_repo(tmp_path):
    root = sup.build_repo(tmp_path / "repo")
    sup.git(root, "init", "-q")
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL))
    sup.write_rule(root, "pending/TP", sup.make_rule("XTP-1", added_by="TP", source_url=URL))
    sup.export(root)
    base = sup.commit_all(root, "base")
    return root, base


def pre_push(root, base, office):
    head = sup.git(root, "rev-parse", "HEAD").stdout.strip()
    stdin = f"refs/heads/main {head} refs/heads/main {base}\n"
    return sup.check(root, mode="pre-push", stdin_text=stdin, office_config=sup.write_office(root.parent, office))


def self_promote(root, pending_office="HC", pending_id="XHC-1", new_id="GEN-003"):
    sup.write_rule(root, "national", promoted(new_id, added_by=pending_office, reviewed_by=pending_office,
                                              review_mode="self"))
    sup.write_rule(root, f"pending/{pending_office}",
                   sup.make_rule(pending_id, added_by=pending_office, source_url=URL,
                                 status="deprecated", superseded_by=new_id))
    sup.export(root)
    return sup.commit_all(root, "self promote")


@needs_git
def test_pre_push_self_promotion_own_pending_passes(git_repo):
    root, base = git_repo
    self_promote(root)
    code, out = pre_push(root, base, "HC")
    assert code == 0, out
    code, out = sup.check(root, mode="ci", base=base)
    assert code == 0, out


@needs_git
def test_pre_push_self_promotion_of_other_office_blocked(git_repo):
    """TN 冒充 HC 自行轉正（正式規則 added_by=reviewed_by=HC）：改到 HC 的 pending 檔仍被擋。"""
    root, base = git_repo
    self_promote(root)
    code, out = pre_push(root, base, "TN")
    assert code == 1 and "[他辦公室 pending]" in out and "XHC-1" in out


@needs_git
def test_pre_push_adding_file_in_other_office_pending_blocked(git_repo):
    root, base = git_repo
    sup.write_rule(root, "pending/TP", sup.make_rule("XTP-2", added_by="TP", source_url=URL))
    sup.commit_all(root, "HC 在 TP 資料夾放檔")
    code, out = pre_push(root, base, "HC")
    assert code == 1 and "新增了 TP 辦公室的 pending 規則" in out


@needs_git
def test_pre_push_peer_promotion_still_allowed(git_repo):
    root, base = git_repo
    sup.write_rule(root, "national", promoted("GEN-003", added_by="HC", reviewed_by="TN", review_mode="peer"))
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL,
                                                     status="deprecated", superseded_by="GEN-003"))
    sup.export(root)
    sup.commit_all(root, "peer promote")
    code, out = pre_push(root, base, "TN")
    assert code == 0, out


# ---------------------------------------------------------------- 匯出

def test_export_status_sheet_has_new_columns_csv_unchanged(repo):
    sup.write_rule(repo, "national", promoted(review_mode="self", spot_checked_at="2026-12-01",
                                              spot_check_note="與官方原文一致"))
    sup.export(repo)
    fields = rl.load_fields(repo)
    rows = list(csv.reader(io.StringIO((repo / "exports" / rl.CSV_NAME).read_text(encoding="utf-8-sig"))))
    assert rows[0] == fields["columns"] and len(rows[0]) == 21
    assert all(len(r) == 21 for r in rows)
    grids = rl.read_workbook_grids(repo / "exports" / rl.XLSX_NAME)
    assert grids["20_規則庫"][0] == fields["columns"]
    head = grids[rl.STATUS_SHEET][0]
    assert head[head.index("reviewed_at") + 1:head.index("reviewed_at") + 3] == ["review_mode", "spot_checked_at"]
    row = dict(zip(head, next(r for r in grids[rl.STATUS_SHEET][1:] if r[0] == "GEN-003")))
    assert row["review_mode"] == "self" and row["spot_checked_at"] == "2026-12-01"
    peer = dict(zip(head, next(r for r in grids[rl.STATUS_SHEET][1:] if r[0] == "GEN-002")))
    assert peer["review_mode"] == "peer" and peer["spot_checked_at"] is None
