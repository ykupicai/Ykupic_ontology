"""往返不失真：規則檔 YAML 讀寫穩定、真 repo 的 exports 與 rules/ 同步、假 repo 匯出內容逐格正確。"""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules_support as sup  # noqa: E402

rl = sup.rl


def test_real_repo_exports_in_sync():
    import rulebook_export
    assert rulebook_export.check(sup.REPO) == []


def test_real_rule_files_yaml_stable():
    fields = rl.load_fields(sup.REPO)
    files = rl.load_all_rules(sup.REPO)
    assert files, "rules/ 底下沒有規則檔"
    for rf in files:
        assert rf.error is None, rf.rel
        text = rl.read_text(rf.path)
        assert rl.dump_rule(rf.data) == text, f"{rf.rel} 不是穩定輸出格式"
        assert list(rf.data)[: len(fields["columns"])] == fields["columns"]


def test_real_csv_matches_rules():
    fields = rl.load_fields(sup.REPO)
    raw = (sup.REPO / "exports" / rl.CSV_NAME).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == fields["columns"]
    exported = rl.exported_rules(sup.REPO, fields)
    assert [r[0] for r in rows[1:]] == [r["rule_id"] for r in exported]


def test_multiline_backslash_and_null_roundtrip(tmp_path):
    root = sup.build_repo(tmp_path / "repo")
    data = sup.make_rule("GEN-003", added_by="HC", reviewed_by="TN", reviewed_at="2026-11-20",
                         source_url="https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013")
    data["條文要旨"] = "第一行\n  縮排第二行\n結尾有反斜線 C:\\temp\n"
    data["手段門檻"] = None
    data["現行版本"] = "113.02.05"
    sup.write_rule(root, "national", data)
    assert rl.load_rule_text(rl.dump_rule(data)) == data
    sup.export(root)
    rows = list(csv.reader(io.StringIO((root / "exports" / rl.CSV_NAME).read_text(encoding="utf-8-sig"))))
    row = dict(zip(rows[0], rows[-1]))
    assert row["條文要旨"] == "第一行\\n  縮排第二行\\n結尾有反斜線 C:\\\\temp\\n"
    assert row["手段門檻"] == ""
    grids = rl.read_workbook_grids(root / "exports" / rl.XLSX_NAME)
    assert list(grids)[:2] == ["00_說明", "20_規則庫"]
    last = dict(zip(grids["20_規則庫"][0], grids["20_規則庫"][-1]))
    assert last["條文要旨"] == data["條文要旨"] and last["手段門檻"] is None
    assert grids["00_說明"][1] == ["文件", "測試\n第二行"]


def test_export_order_legacy_first_then_natural(tmp_path):
    root = sup.build_repo(tmp_path / "repo")
    for rid in ("ABC-10", "ABC-2"):
        sup.write_rule(root, "national", sup.make_rule(rid, added_by="HC", reviewed_by="TN", reviewed_at="2026-11-20",
                                                       source_url="https://law.moj.gov.tw/x"))
    sup.write_rule(root, "pending/HC", sup.make_rule("XHC-1", added_by="HC",
                                                     source_url="https://law.moj.gov.tw/x"))
    ids = [r["rule_id"] for r in rl.exported_rules(root)]
    assert ids == ["GEN-001", "TNN-001", "ABC-2", "ABC-10", "GEN-002"]  # pending 不進匯出


def _handwritten(rule_id="XHC-1", added_by="HC") -> bytes:
    """模擬手寫：範本註解、雙引號、CRLF、BOM。"""
    data = sup.make_rule(rule_id, added_by=added_by, source_url="https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013")
    lines = ["# 手寫的規則"]
    for k, v in data.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f'{k}: "{v}"')
    lines[lines.index('現行版本: "113.01.01"')] = '現行版本: "115.05.27"'
    return b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8") + b"\r\n"


def test_handwritten_rule_normalized_by_export(tmp_path):
    import rulebook_export
    root = sup.build_repo(tmp_path / "repo")
    path = root / "rules/pending/HC/XHC-1.yaml"
    path.write_bytes(_handwritten())
    # 整理前：--check 與 rule_check 都判為不標準
    assert any("不是標準格式" in p for p in rulebook_export.check(root))
    assert rulebook_export.main(["--check", "--repo-root", str(root)]) == 1
    code, out = sup.check(root)
    assert code == 1 and "[格式不標準]" in out
    before = rl.load_rule_text(rl.read_text(path))
    n, written = rulebook_export.export(root)
    assert "rules/pending/HC/XHC-1.yaml" in written
    raw = path.read_bytes()
    assert b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    rf = rl.load_rule_file(path, root)
    assert rf.data == before and rf.data["現行版本"] == "115.05.27"
    assert rl.dump_rule(rf.data) == rl.read_text(path)  # 與 test_real_rule_files_yaml_stable 同一判準
    assert rulebook_export.check(root) == []
    code, out = sup.check(root)
    assert code == 0, out
    assert rulebook_export.export(root)[1] == []  # 再跑一次不改任何檔


def test_handwritten_promoted_rule_normalized(tmp_path):
    import rulebook_export
    root = sup.build_repo(tmp_path / "repo")
    raw = _handwritten("LUR-9001", added_by="HC").decode("utf-8-sig")
    raw = raw.replace('reviewed_by: null', 'reviewed_by: "TP"').replace(
        'reviewed_at: null', "reviewed_at: '2026-11-20'\r\nreview_mode: \"peer\"")
    (root / "rules/national").mkdir(exist_ok=True)
    (root / "rules/national/LUR-9001.yaml").write_text(raw, encoding="utf-8", newline="")
    rulebook_export.export(root)
    code, out = sup.check(root)
    assert code == 0, out
    rf = rl.load_rule_file(root / "rules/national/LUR-9001.yaml", root)
    assert rl.dump_rule(rf.data) == rl.read_text(rf.path) and rf.path.read_bytes() == rl.dump_rule(rf.data).encode()


def test_export_reproducible(tmp_path):
    import rulebook_export
    root = sup.build_repo(tmp_path / "repo")
    _, grids, _ = rulebook_export.render_all(root)
    assert rulebook_export.xlsx_bytes(grids) == rulebook_export.xlsx_bytes(grids)
    assert rulebook_export.check(root) == []
    assert rulebook_export.main(["--check", "--repo-root", str(root)]) == 0
