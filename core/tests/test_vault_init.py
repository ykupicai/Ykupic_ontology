# -*- coding: utf-8 -*-
"""init_vault：從範本建骨架、不覆蓋既有檔、替換佔位字串、dry-run 不寫入。"""
import contextlib
import io
from pathlib import Path

import pytest

import init_vault
import vault_audit


@pytest.fixture
def template(tmp_path):
    root = tmp_path / "template"
    (root / "00_Index").mkdir(parents=True)
    (root / "03_案件經驗知識層" / "10_變更編定").mkdir(parents=True)
    (root / "03_案件經驗知識層" / "10_變更編定" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "00_Index" / "總入口.md").write_text(
        "---\ntype: index\noffice: {{OFFICE_CODE}}\n---\n# {{OFFICE_NAME}} 知識庫總入口\r\n", encoding="utf-8")
    (root / "設定.yaml").write_text("office: {{OFFICE_CODE}}\n", encoding="utf-8")
    (root / "圖.png").write_bytes(b"\x89PNG{{OFFICE_CODE}}")
    return root


def test_creates_skeleton_and_replaces_placeholders(make_office, template):
    cfg, _, vault = make_office(create_vault=False, require_vault_exists=False)
    result = init_vault.init_vault(cfg, template=template)
    entry = (vault / "00_Index" / "總入口.md").read_bytes().decode("utf-8")
    assert "office: HC" in entry and "# 新竹辦公室 知識庫總入口\n" in entry
    assert "\r\n" not in entry
    assert (vault / "設定.yaml").read_text(encoding="utf-8") == "office: HC\n"
    assert (vault / "圖.png").read_bytes() == b"\x89PNG{{OFFICE_CODE}}"   # 二進位檔不替換
    assert (vault / "03_案件經驗知識層" / "10_變更編定").is_dir()
    assert not (vault / "03_案件經驗知識層" / "10_變更編定" / ".gitkeep").exists()
    assert result["skipped"] == []


def test_existing_files_are_never_overwritten(make_office, template):
    cfg, _, vault = make_office()
    (vault / "00_Index").mkdir()
    mine = vault / "00_Index" / "總入口.md"
    mine.write_text("我自己改過的內容\n", encoding="utf-8")
    result = init_vault.init_vault(cfg, template=template)
    assert mine.read_text(encoding="utf-8") == "我自己改過的內容\n"
    assert mine in result["skipped"]
    # 第二次執行：全部略過、不出錯
    again = init_vault.init_vault(cfg, template=template)
    assert again["files"] == [] and len(again["skipped"]) == 3


def test_dry_run_writes_nothing(make_office, template):
    cfg, _, vault = make_office(create_vault=False, require_vault_exists=False)
    result = init_vault.init_vault(cfg, template=template, dry_run=True)
    assert not vault.exists()
    assert vault in result["dirs"] and len(result["files"]) == 3


def test_main_dry_run_and_real_run(make_office, template, tmp_path, monkeypatch):
    from ykkb import config
    cfg, office_path, vault = make_office(create_vault=False, require_vault_exists=False)
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert init_vault.main(["--config", str(office_path), "--template", str(template), "--dry-run"]) == 0
    assert "dry-run" in out.getvalue() and not vault.exists()
    with contextlib.redirect_stdout(io.StringIO()):
        assert init_vault.main(["--config", str(office_path), "--template", str(template)]) == 0
    assert (vault / "00_Index" / "總入口.md").is_file()


def test_fresh_vault_from_template_audits_clean(make_office, template):
    cfg, _, vault = make_office(create_vault=False, require_vault_exists=False)
    init_vault.init_vault(cfg, template=template)
    with contextlib.redirect_stdout(io.StringIO()):
        assert vault_audit.run_audit(cfg) == 0


def test_repo_template_if_present_audits_clean(make_office):
    """repo 的 templates/vault（由手冊作者維護）建出的空 vault 健檢必須 0 錯誤。"""
    if not init_vault.TEMPLATE_DIR.is_dir():
        pytest.skip("repo 尚無 templates/vault")
    cfg, _, vault = make_office(create_vault=False, require_vault_exists=False)
    init_vault.init_vault(cfg)
    leftover = [p for p in vault.rglob("*") if p.is_file() and p.suffix in {".md", ".yaml", ".yml"}
                and "{{OFFICE_" in p.read_text(encoding="utf-8")]
    assert leftover == []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert vault_audit.run_audit(cfg) == 0, out.getvalue()
    assert "連結健康度：✓ 乾淨" in out.getvalue(), out.getvalue()


def test_missing_template_fails(make_office, tmp_path):
    cfg, _, _ = make_office()
    with pytest.raises(FileNotFoundError):
        init_vault.init_vault(cfg, template=tmp_path / "none")
