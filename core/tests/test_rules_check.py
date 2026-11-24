"""rule_check 靜態檢查（不需要 git）。每個情境在乾淨假 repo 上只製造一種錯誤。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules_support as sup  # noqa: E402

URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"


@pytest.fixture
def repo(tmp_path):
    return sup.build_repo(tmp_path / "repo")


def run(root):
    return sup.check(root)


def test_clean_repo_passes(repo):
    code, out = run(repo)
    assert code == 0, out


def test_real_repo_passes():
    code, out = sup.check(sup.REPO)
    assert code == 0, out


def test_valid_pending_rule_passes(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL))
    code, out = run(repo)
    assert code == 0, out


def test_duplicate_id_blocked(repo):
    sup.write_rule(repo, "local/TNN", sup.make_rule("GEN-002", added_by="HC", reviewed_by="TN",
                                                    reviewed_at="2026-11-20", source_url=URL))
    code, out = run(repo)
    assert code == 1 and "[ID 重複]" in out


def test_filename_not_id_blocked(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL), name="XHC-2")
    code, out = run(repo)
    assert code == 1 and "[檔名≠ID]" in out


def test_pending_prefix_folder_mismatch_blocked(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XTP-1", added_by="HC", source_url=URL))
    code, out = run(repo)
    assert code == 1 and "[pending 前綴]" in out


def test_new_rule_missing_source_url_blocked(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=None))
    code, out = run(repo)
    assert code == 1 and "[source_url]" in out and "缺 source_url" in out


@pytest.mark.parametrize("url", ["https://www.rootlaw.com.tw/LawContent.aspx?LawID=A040040011010700",
                                 "https://6laws.net/6law/law/x.htm", "ftp://law.moj.gov.tw/x",
                                 "https://law.moj.gov.tw.evil.example/x"])
def test_non_official_domain_blocked(repo, url):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=url))
    code, out = run(repo)
    assert code == 1 and "[source_url]" in out


@pytest.mark.parametrize("url", ["https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=",
                                 "https://glrs.moi.gov.tw/LawContent.aspx?id=", "https://law.moj.gov.tw/x?pcode=D0060013&flno="])
def test_blank_query_value_blocked(repo, url):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=url))
    code, out = run(repo)
    assert code == 1 and "沒有值" in out


def test_national_prefix_must_be_registered(repo):
    sup.write_rule(repo, "national", sup.make_rule("ZZZ-001", added_by="HC", reviewed_by="TN",
                                                   reviewed_at="2026-11-20", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "[ID 前綴]" in out and "總部" in out
    (repo / "rules/national/ZZZ-001.yaml").unlink()
    sup.write_rule(repo, "national", sup.make_rule("LUR-9001", added_by="HC", reviewed_by="TN",
                                                   reviewed_at="2026-11-20", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 0, out


@pytest.mark.parametrize("url", ["https://glrs.moi.gov.tw/LawContent.aspx?id=FL003635",
                                 "https://law01.tainan.gov.tw/glrsnewsout/LawContent.aspx?id=GL000306",
                                 "https://ptlaw.pthg.gov.tw/x", "https://outlaw.hsinchu.gov.tw/x"])
def test_official_domains_pass(repo, url):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=url))
    code, out = run(repo)
    assert code == 0, out


def test_deleted_legacy_rule_blocked(repo):
    (repo / "rules/national/GEN-001.yaml").unlink()
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "[刪除轉正規則]" in out


def test_reviewed_by_equals_added_by_needs_self_mode(repo):
    """2026-11-23 起可自行轉正：reviewed_by＝added_by 要搭配 review_mode: self；標成 peer 仍擋。"""
    sup.write_rule(repo, "national", sup.make_rule("GEN-003", added_by="HC", reviewed_by="HC",
                                                   reviewed_at="2026-11-20", review_mode="peer", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "review_mode 應為 self" in out
    sup.write_rule(repo, "national", sup.make_rule("GEN-003", added_by="HC", reviewed_by="HC",
                                                   reviewed_at="2026-11-20", review_mode="self", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 0, out


def test_promoted_rule_without_review_blocked(repo):
    sup.write_rule(repo, "national", sup.make_rule("GEN-003", added_by="HC", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "必須有 reviewed_by" in out


def test_exports_stale_blocked(repo):
    sup.write_rule(repo, "national", sup.make_rule("GEN-003", added_by="HC", reviewed_by="TN",
                                                   reviewed_at="2026-11-20", source_url=URL))
    code, out = run(repo)
    assert code == 1 and "[exports 未同步]" in out
    sup.export(repo)
    assert run(repo)[0] == 0


def test_legacy_flag_on_new_rule_blocked(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", legacy_import=True))
    code, out = run(repo)
    assert code == 1 and "[匯入標記]" in out


def test_modified_legacy_rule_needs_source_url(repo):
    path = repo / "rules/national/GEN-001.yaml"
    data = sup.rl.load_rule_text(path.read_text(encoding="utf-8"))
    data["條文要旨"] = "改過的要旨"
    path.write_bytes(sup.rl.dump_rule(data).encode("utf-8"))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "匯入規則的 21 欄內容已修改" in out
    data["source_url"] = URL
    path.write_bytes(sup.rl.dump_rule(data).encode("utf-8"))
    sup.export(repo)  # source_url 也出現在匯出 xlsx 的 90_規則狀態
    code, out = run(repo)
    assert code == 0, out


def test_enum_and_type_errors_blocked(repo):
    data = sup.make_rule("XHC-1", added_by="HC", source_url=URL)
    data["回答型態"] = "隨便寫"
    data["條號"] = 10
    sup.write_rule(repo, "pending/HC", data)
    code, out = run(repo)
    assert code == 1 and "[enum 非法]" in out and "不是文字" in out


def test_missing_field_and_bad_yaml_blocked(repo):
    data = sup.make_rule("XHC-1", added_by="HC", source_url=URL)
    del data["觸發條件"]
    sup.write_rule(repo, "pending/HC", data)
    (repo / "rules/pending/HC/XHC-2.yaml").write_text("rule_id: XHC-2\n法規: [未關閉\n", encoding="utf-8")
    code, out = run(repo)
    assert code == 1 and "[欄位缺]" in out and "[格式錯]" in out


def test_bad_id_format_blocked(repo):
    sup.write_rule(repo, "national", sup.make_rule("GEN-ABC", added_by="HC", reviewed_by="TN",
                                                   reviewed_at="2026-11-20", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "[ID 格式]" in out


def test_deprecated_needs_superseded_by_and_target_exists(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL, status="deprecated"))
    code, out = run(repo)
    assert code == 1 and "沒填 superseded_by" in out
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL, status="deprecated",
                                                     superseded_by="GEN-999"))
    code, out = run(repo)
    assert code == 1 and "不存在" in out
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL, status="deprecated",
                                                     superseded_by="GEN-002"))
    assert run(repo)[0] == 0


def test_local_folder_prefix_rules(repo):
    sup.write_rule(repo, "local/TNN", sup.make_rule("KCG-099", added_by="HC", reviewed_by="TN",
                                                    reviewed_at="2026-11-20", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "local/TNN/ 的規則 ID 應以" in out


def test_pending_id_reused_by_promoted_rule_blocked(repo):
    sup.write_rule(repo, "pending/HC", sup.make_rule("XHC-1", added_by="HC", source_url=URL, status="deprecated",
                                                     superseded_by="GEN-002"))
    sup.write_rule(repo, "national", sup.make_rule("XHC-1", added_by="HC", reviewed_by="TN",
                                                   reviewed_at="2026-11-20", source_url=URL))
    sup.export(repo)
    code, out = run(repo)
    assert code == 1 and "[ID 重複]" in out and "不可使用 pending 形式 ID" in out
