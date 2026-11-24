"""rule_check 的 git 差異檢查、pre-push 模式與 install_hooks（暫存 git repo，push 到本機 bare repo，不連外網）。"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules_support as sup  # noqa: E402

pytestmark = pytest.mark.skipif(not sup.has_git(), reason="需要 git")
URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"
ZERO = "0" * 40


@pytest.fixture
def repo(tmp_path):
    root = sup.build_repo(tmp_path / "repo")
    sup.git(root, "init", "-q")
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL))
    sup.export(root)
    base = sup.commit_all(root, "base")
    return root, base


def pre_push(root, base, office, head=None):
    head = head or sup.git(root, "rev-parse", "HEAD").stdout.strip()
    stdin = f"refs/heads/main {head} refs/heads/main {base}\n"
    return sup.check(root, mode="pre-push", stdin_text=stdin, office_config=sup.write_office(root.parent, office))


def promote(root, reviewer="TN", target_added_by="HC", extra_change=False):
    sup.write_rule(root, "national", sup.make_rule("GEN-003", added_by=target_added_by, reviewed_by=reviewer,
                                                   reviewed_at="2026-11-21", source_url=URL))
    old = sup.make_rule("XHC-1", added_by="HC", source_url=URL, status="deprecated", superseded_by="GEN-003")
    if extra_change:
        old["條文要旨"] = "順手改了內容"
    sup.write_rule(root, "pending/HC", old)
    sup.export(root)
    return sup.commit_all(root, "promote")


def test_deleting_promoted_rule_blocked_ci(repo):
    root, base = repo
    (root / "rules/national/GEN-002.yaml").unlink()
    sup.export(root)
    sup.commit_all(root, "delete")
    code, out = sup.check(root, mode="ci", base=base)
    assert code == 1 and "[刪除轉正規則]" in out and "GEN-002" in out


def test_ci_without_base_uses_previous_commit(repo):
    root, _ = repo
    (root / "rules/national/GEN-002.yaml").unlink()
    sup.export(root)
    sup.commit_all(root, "delete")
    code, out = sup.check(root, mode="ci")
    assert code == 1 and "HEAD~1" in out and "[刪除轉正規則]" in out


def test_other_office_pending_edit_blocked(repo):
    root, base = repo
    data = sup.make_rule("XHC-1", added_by="HC", source_url=URL)
    data["條文要旨"] = "台北改了新竹的規則"
    sup.write_rule(root, "pending/HC", data)
    sup.commit_all(root, "edit")
    code, out = pre_push(root, base, "TP")
    assert code == 1 and "[他辦公室 pending]" in out
    code, out = pre_push(root, base, "HC")
    assert code == 0, out


def test_other_office_pending_format_only_allowed(tmp_path):
    """TP 以 --no-verify 推了格式不標準的 pending 檔；HC pull 後匯出自動整理，值不變 → 放行（避免死結）。"""
    root = sup.build_repo(tmp_path / "repo")
    sup.git(root, "init", "-q")
    data = sup.make_rule("XTP-1", added_by="TP", source_url=URL)
    path = sup.write_rule(root, "pending/TP", data)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n").replace("現行版本: 113.01.01".encode(),
                                                                       '現行版本: "113.01.01"'.encode()))
    base = sup.commit_all(root, "TP 格式不標準")
    import rulebook_export
    n, written = rulebook_export.export(root)
    assert "rules/pending/TP/XTP-1.yaml" in written
    sup.commit_all(root, "HC 匯出整理")
    code, out = pre_push(root, base, "HC")
    assert code == 0, out


def test_branch_and_origin_warnings(repo):
    root, base = repo
    sup.git(root, "checkout", "-q", "-b", "feature")
    code, out = sup.check(root, office_config=sup.write_office(root.parent, "HC"))
    assert code == 0, out
    assert "警告：目前分支是「feature」不是 main" in out and "警告：找不到 origin/main" in out


def test_other_office_pending_delete_blocked(repo):
    root, base = repo
    (root / "rules/pending/HC/XHC-1.yaml").unlink()
    sup.commit_all(root, "rm")
    code, out = pre_push(root, base, "TN")
    assert code == 1 and "刪除了 HC 辦公室的 pending 規則" in out


def test_promotion_exception_allowed(repo):
    root, base = repo
    promote(root)
    code, out = pre_push(root, base, "TN")
    assert code == 0, out


def test_promotion_with_extra_change_blocked(repo):
    root, base = repo
    promote(root, extra_change=True)
    code, out = pre_push(root, base, "TN")
    assert code == 1 and "[他辦公室 pending]" in out


def test_promotion_by_wrong_office_blocked(repo):
    root, base = repo
    promote(root, reviewer="TN")
    code, out = pre_push(root, base, "TP")   # 目標規則 reviewed_by=TN，但本機是 TP
    assert code == 1 and "[他辦公室 pending]" in out


def test_self_promotion_allowed(repo):
    """2026-11-23 起 HC 可自行轉正自己的 pending 規則（make_rule 依 reviewed_by＝added_by 帶 review_mode: self）。"""
    root, base = repo
    promote(root, reviewer="HC")
    code, out = pre_push(root, base, "HC")
    assert code == 0, out
    assert (root / "rules/national/GEN-003.yaml").read_text(encoding="utf-8").count("review_mode: self") == 1


def test_pre_push_checks_committed_tree_not_worktree(repo):
    root, base = repo
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-2", added_by="HC", source_url=None))
    sup.commit_all(root, "bad")
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-2", added_by="HC", source_url=URL))  # 只改工作區
    code, out = pre_push(root, base, "HC")
    assert code == 1 and "缺 source_url" in out and "未提交的變更" in out


def test_pre_push_first_push_static_only(repo):
    root, _ = repo
    head = sup.git(root, "rev-parse", "HEAD").stdout.strip()
    code, out = pre_push(root, ZERO, "HC", head=head)
    assert code == 0 and "只做靜態檢查" in out


def test_install_hook_and_real_push(tmp_path):
    import install_hooks
    root = sup.build_repo(tmp_path / "work", with_core=True)
    bare = tmp_path / "remote.git"
    sup.git(tmp_path, "init", "-q", "--bare", str(bare))
    sup.git(root, "init", "-q")
    sup.git(root, "remote", "add", "origin", str(bare))
    sup.write_office(root, "HC")
    (root / ".gitignore").write_text("office.yaml\nvault/\n__pycache__/\n", encoding="utf-8")
    sup.commit_all(root, "init")
    hook = Path(sup.git(root, "rev-parse", "--git-path", "hooks/pre-push").stdout.strip())
    hook = hook if hook.is_absolute() else root / hook
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    msg = install_hooks.install(root, sys.executable)
    assert "已備份" in msg
    assert list(hook.parent.glob("pre-push.bak-*"))
    assert b"\r\n" not in hook.read_bytes() and b"--pre-push" in hook.read_bytes()
    assert "已是最新" in install_hooks.install(root, sys.executable)
    env_note = os.environ.get("YKKB_OFFICE_CONFIG")
    os.environ.pop("YKKB_OFFICE_CONFIG", None)
    try:
        # 會被擋：新規則缺 source_url
        sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC"))
        sup.commit_all(root, "bad rule")
        res = sup.git(root, "push", "-q", "origin", "main", check=False)
        assert res.returncode != 0, res.stdout + res.stderr
        assert "缺 source_url" in res.stdout + res.stderr
        # 修好後通過
        sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL))
        sup.commit_all(root, "fix")
        res = sup.git(root, "push", "-q", "origin", "main", check=False)
        assert res.returncode == 0, res.stdout + res.stderr
    finally:
        if env_note is not None:
            os.environ["YKKB_OFFICE_CONFIG"] = env_note
