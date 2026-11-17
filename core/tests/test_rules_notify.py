"""通知留言產生邏輯（notify_text）：假資料單元測試＋暫存 git repo 實測。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules_support as sup  # noqa: E402

import notify_text as nt  # noqa: E402

URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"
RUN = "https://github.com/example/repo/actions/runs/1"


def test_classify_changes_fake_data():
    old = {"rules/pending/HC/XHC-1.yaml": {"status": "active", "a": 1},
           "rules/national/GEN-001.yaml": {"status": "active", "a": 1},
           "rules/national/GEN-002.yaml": {"status": "active", "a": 1}}
    new = {"rules/pending/HC/XHC-1.yaml": {"status": "deprecated", "superseded_by": "LUR-9001", "a": 1},
           "rules/national/GEN-001.yaml": {"status": "active", "a": 2},
           "rules/national/GEN-002.yaml": {"status": "active", "a": 1}}
    entries = nt.parse_name_status("A\trules/national/LUR-9001.yaml\nM\trules/pending/HC/XHC-1.yaml\n"
                                   "M\trules/national/GEN-001.yaml\nM\trules/national/GEN-002.yaml\n"
                                   "D\trules/local/TNN/TNN-099.yaml\nM\trules/_fields.yaml\n")
    ch = nt.classify_rule_changes(entries, old.get, new.get)
    assert ch.added == ["`LUR-9001`（中央）"]
    assert ch.deleted == ["`TNN-099`（地方 TNN）"]
    assert ch.modified == ["`GEN-001`（中央）"]
    assert ch.format_only == ["`GEN-002`（中央）"]
    assert ch.status_changed == ["`XHC-1`（待轉正 HC）：active → deprecated，取代者 `LUR-9001`"]


def test_build_message_success_and_failure():
    ch = nt.RuleChanges(added=["`XHC-1`（待轉正 HC）"])
    msg = nt.build_message(ok=True, pusher="hc-maintainer", commits=[("abc1234", "新增規則 XHC-1")], changes=ch,
                           law_notes_changed=True, total_rule_files=None, run_url=RUN)
    assert "規則庫已更新" in msg and "`abc1234` 新增規則 XHC-1" in msg and "新增（1）" in msg
    assert "law_notes" in msg and "有變動" in msg and "sync_to_vault.py" in msg and "git pull" in msg
    bad = nt.build_message(ok=False, pusher="x", commits=[("abc1234", "m")], changes=ch,
                           law_notes_changed=False, total_rule_files=None, run_url=RUN)
    assert "⚠ 檢查未通過" in bad and RUN in bad and "sync_to_vault" not in bad
    first = nt.build_message(ok=True, pusher="x", commits=[], changes=None, law_notes_changed=None,
                             total_rule_files=346, run_url=RUN)
    assert "共 346 個規則檔" in first and "未比對" in first


@pytest.mark.skipif(not sup.has_git(), reason="需要 git")
def test_collect_from_git(tmp_path):
    root = sup.build_repo(tmp_path / "repo")
    sup.git(root, "init", "-q")
    base = sup.commit_all(root, "base")
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL))
    (root / "law_notes").mkdir()
    (root / "law_notes/a.md").write_text("x\n", encoding="utf-8")
    after = sup.commit_all(root, "新增規則 XHC-1")
    commits, more, ch, law, practice, total = nt.collect(root, base, after)
    assert [m for _, m in commits] == ["新增規則 XHC-1"] and more == 0
    assert ch.added == ["`XHC-1`（待轉正 HC）"] and law is True and practice is False and total is None
    (root / "practice_notes").mkdir()
    (root / "practice_notes/b.md").write_text("y\n", encoding="utf-8")
    after2 = sup.commit_all(root, "新增實務筆記")
    _, _, _, law, practice, _ = nt.collect(root, after, after2)
    assert law is False and practice is True
    commits, _, ch, law, practice, total = nt.collect(root, "0" * 40, after)
    assert ch is None and law is None and practice is None and total == 4 and len(commits) == 1


def test_build_message_lists_practice_notes():
    msg = nt.build_message(ok=True, pusher="x", commits=[], changes=nt.RuleChanges(), law_notes_changed=False,
                           total_rule_files=None, run_url=RUN, practice_notes_changed=True)
    assert "practice_notes" in msg and msg.count("有變動") == 1
