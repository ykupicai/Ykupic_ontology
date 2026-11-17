# -*- coding: utf-8 -*-
"""notes_check：practice_notes/ 的 frontmatter、禁字、allow_terms 豁免、repo 外連結。"""
from pathlib import Path

import notes_check as nc

CODES = {"TN", "HC", "TP"}
HEAD = "---\ntype: lesson\nsource_office: TN\ndeidentified: true\nupdated: 2026-11-17\n{extra}---\n"


def make(tmp_path: Path, body: str, extra: str = "", name: str = "教訓.md", head: str | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "practice_notes" / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "law_notes").mkdir(exist_ok=True)
    (root / "law_notes" / "甲法-重點.md").write_text("x", encoding="utf-8")
    text = (HEAD.format(extra=extra) if head is None else head) + body
    (root / "practice_notes" / "lessons" / name).write_text(text, encoding="utf-8")
    return root


def items(root):
    issues, _ = nc.check_tree(root, CODES)
    return [i.item for i in issues], issues


def test_clean_note_passes(tmp_path):
    root = make(tmp_path, "見 [[甲法-重點]] 與 [[教訓]]；路徑寫 \\\\<NAS>\\<共享名>\\專案、<磁碟>:\\資料。\n"
                          "本公司衍古開發顧問有限公司的作法。")
    assert items(root)[0] == []


def test_frontmatter_required(tmp_path):
    root = make(tmp_path, "內容", head="---\ntype: lesson\nsource_office: XX\ndeidentified: false\n---\n")
    got, issues = items(root)
    text = " ".join(i.message for i in issues)
    assert "缺欄位：updated" in text and "不在 offices.yaml" in text and "deidentified 必須是 true" in text
    root2 = make(tmp_path / "b", "沒有檔頭", head="")
    assert items(root2)[0] == ["frontmatter"]


def test_restricted_blocked(tmp_path):
    root = make(tmp_path, "x", extra="sensitivity: restricted\n")
    assert "敏感度" in items(root)[0]


def test_banned_terms(tmp_path):
    body = ("NAS 在 192.168.1.134 的 Public-TN；存到 Z:\\8. AI協作 與 C:\\Users\\someone；\n"
            "業主某某能源股份有限公司；基地在臺南某某段123-4地號；來文府農字第1140227888號；見案件 C003。")
    got, _ = items(make(tmp_path, body))
    for label in ("內網 IP", "NAS 共享名", "實體路徑", "公司行號", "地段地號", "公文文號", "案件代碼"):
        assert f"禁字：{label}" in got, label


def test_allow_terms_exempts_public_reference(tmp_path):
    body = "依內政部台內地字第1100181578號函釋。"
    assert "禁字：公文文號" in items(make(tmp_path / "a", body))[0]
    assert items(make(tmp_path / "b", body, extra="allow_terms:\n  - 台內地字第1100181578號\n"))[0] == []


def test_link_outside_repo_blocked(tmp_path):
    got, issues = items(make(tmp_path, "見 [[臺南某段-某能源光電]] 與 [[甲法-重點|甲法]]"))
    assert got == ["repo 外連結"] and "臺南某段-某能源光電" in issues[0].message


def test_non_markdown_blocked(tmp_path):
    root = make(tmp_path, "x")
    (root / "practice_notes" / "lessons" / "圖.png").write_bytes(b"\x89PNG")
    assert "檔案類型" in items(root)[0]


def test_missing_dir_is_fine(tmp_path):
    assert nc.check_tree(tmp_path, CODES) == ([], 0)
