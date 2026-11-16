# -*- coding: utf-8 -*-
"""ykkb.metadata：由臺南 tests/test_knowledge_metadata.py、test_restricted_dir_single_source.py、
test_sensitivity_single_gate.py 移植適用部分（檢索、LINE Bot、備份相關的不在本 repo）。"""
import re
from pathlib import Path

import pytest

from ykkb import config
from ykkb import metadata as km

CORE = Path(__file__).resolve().parents[1]


# --- YAML 與相容讀取 -------------------------------------------------------------

def test_unnumbered_legacy_record_is_retained(tmp_path):
    path = tmp_path / "progress.yaml"
    path.write_text('done:\n  "20260716清潔隊": {method: none}\n', encoding="utf-8")
    record = km.load_eval_progress(path)["20260716清潔隊"]
    assert record["identity_status"] == "needs_case_id"
    assert km.eval_progress_status(record) == "needs_source"


def test_legacy_normalization_preserves_scope_and_date():
    original = {"depth": "深度訪談", "verified": "2026-07-02（部分條文）", "type": "law-digest",
                "source": "https://law.moj.gov.tw/example"}
    result = km.normalize_metadata(original)
    assert result["source_depth"] == "interview_validated"
    assert result["verified_at"] == "2026-07-02"
    assert result["legal_status"] == "unknown"
    assert result["verification_scope"] == original["verified"]
    assert "verified_at" not in original


def test_duplicate_yaml_fails_closed():
    with pytest.raises(ValueError):
        km.load_yaml("done: {}\ndone: {}\n")


def test_unhashable_yaml_key_is_value_error():
    with pytest.raises(ValueError):
        km.load_yaml('? [a, b]\n: value\n')


def test_yaml_dates_and_multiline_are_supported():
    meta, body = km.split_frontmatter("---\nas_of: 2026-09-14\nnext_action: >-\n  重讀來源\n  確認狀態\n---\n本文")
    assert meta["as_of"] == "2026-09-14"
    assert meta["next_action"] == "重讀來源 確認狀態"
    assert body == "本文"


def test_unclosed_frontmatter_fails():
    with pytest.raises(ValueError, match="Unclosed"):
        km.split_frontmatter("---\ntype: x\n本文\n")


def test_inline_and_block_progress_both_count(tmp_path):
    path = tmp_path / "progress.yaml"
    path.write_text("done:\n  EV-A: {method: none}\n  EV-B:\n    method: pdf\n    confidence: 低\n  EV-C: {method: docx}\n",
                    encoding="utf-8")
    records = km.load_eval_progress(path)
    assert [km.eval_progress_status(r) for r in records.values()] == ["needs_source", "needs_review", "read_recorded"]


# --- 限制級目錄名：唯一來源是 config ---------------------------------------------

def test_matching_is_case_insensitive_and_layer_independent():
    assert km.is_restricted_dir_name("30_committees")
    assert km.is_restricted_dir_name("30_COMMITTEES")
    assert km.is_restricted_dir_name("30_Committees")
    assert km.in_restricted_dir(("03_案件經驗知識層", "30_Committees", "x.md"))
    assert not km.in_restricted_dir(("02_審議資料庫知識層", "10_Cases", "x.md"))
    assert not km.is_restricted_dir_name("30_Committees_備份說明")   # 整段比對，非子字串


def test_restricted_names_come_from_config():
    names = ["99_機密"]
    assert km.is_restricted_dir_name("99_機密", names)
    assert not km.is_restricted_dir_name("30_Committees", names)
    assert km.in_restricted_dir(("a", "99_機密", "x.md"), names)


def test_restricted_dir_name_is_not_hardcoded_elsewhere():
    """限制級目錄名只能出現在 ykkb/config.py；其他程式一律經由設定取得。"""
    pattern = re.compile("|".join(re.escape(n) for n in config.DEFAULT_RESTRICTED_DIR_NAMES), re.IGNORECASE)
    definition = CORE / "ykkb" / "config.py"
    offenders = []
    for path in list((CORE / "ykkb").glob("*.py")) + list((CORE / "tools").glob("*.py")):
        if path == definition:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "請改用 ykkb.config／ykkb.metadata 的函式：\n" + "\n".join(offenders)


# --- sensitivity 判定 fail-closed ----------------------------------------------------

@pytest.mark.parametrize("value", [
    "restricted", "Restricted", "RESTRICTED", " restricted", "restricted ", "\trestricted\n",
])
def test_restricted_spellings(value):
    assert km.sensitivity_state({"sensitivity": value}) == "restricted"
    assert km.is_restricted({"sensitivity": value})


@pytest.mark.parametrize("value", [
    "secret", "限制級", "", "   ", "restrict", "restricted-ish", None, 1, True, ["restricted"],
    {"level": "restricted"},
])
def test_unrecognized_values_fail_closed(value):
    assert km.sensitivity_state({"sensitivity": value}) == "unrecognized"
    assert km.is_restricted({"sensitivity": value})


@pytest.mark.parametrize("value", ["public", "internal", " Internal ", "PUBLIC"])
def test_non_restricted_values(value):
    assert km.sensitivity_state({"sensitivity": value}) == "non_restricted"
    assert not km.is_restricted({"sensitivity": value})


def test_absent_field_is_not_restricted():
    assert km.sensitivity_state({"type": "case"}) == "absent"
    assert not km.is_restricted({})


def test_unparsed_marker_detected():
    text = "\n---\nsensitivity: restricted\n---\n本文"
    meta, _ = km.split_frontmatter(text)
    assert meta == {}
    assert km.has_unparsed_sensitivity_marker(text, meta)
    assert not km.has_unparsed_sensitivity_marker("---\nsensitivity: restricted\n---\n", {"sensitivity": "restricted"})
