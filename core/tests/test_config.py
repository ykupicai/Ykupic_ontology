# -*- coding: utf-8 -*-
"""office.yaml 讀取與驗證：缺檔、代碼不在表內、vault 不存在等都要明確失敗。"""
from pathlib import Path

import pytest

from ykkb import config


def test_defaults_are_filled(make_office):
    cfg, office, vault = make_office()
    assert cfg["office_code"] == "HC"
    assert cfg["office_name"] == "新竹辦公室"
    assert Path(cfg["vault_root"]) == vault
    assert tuple(cfg["restricted_dir_names"]) == config.DEFAULT_RESTRICTED_DIR_NAMES
    assert cfg["shared_dirs"] == config.DEFAULT_SHARED_DIRS
    assert cfg["extra_export_targets"] == []
    assert cfg["office_codes"] == ["HC", "TN", "TP"]
    assert cfg["config_path"] == str(office)


def test_missing_config_file_explains_example(tmp_path):
    with pytest.raises(config.OfficeConfigError, match="office.example.yaml"):
        config.load_office_config(tmp_path / "office.yaml")


def test_env_var_overrides_default_path(tmp_path, monkeypatch, make_office):
    _, office, _ = make_office()
    monkeypatch.setenv(config.ENV_VAR, str(office))
    assert config.resolve_config_path() == office
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "不存在.yaml"))
    with pytest.raises(config.OfficeConfigError, match="找不到辦公室設定檔"):
        config.load_office_config()


def test_default_path_is_repo_root_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.resolve_config_path() == config.REPO_ROOT / "office.yaml"
    assert (config.REPO_ROOT / "core" / "ykkb" / "config.py").is_file()


def test_unknown_office_code(make_office, tmp_path):
    vault = (tmp_path / "vault")
    vault.mkdir()
    with pytest.raises(config.OfficeConfigError, match="不在辦公室代碼表內"):
        make_office(f"office_code: KH\nvault_root: {vault.as_posix()}\n")


def test_missing_office_code(make_office, tmp_path):
    with pytest.raises(config.OfficeConfigError, match="缺 office_code"):
        make_office(f"vault_root: {tmp_path.as_posix()}\n")


def test_vault_root_must_exist(make_office, tmp_path):
    with pytest.raises(config.OfficeConfigError, match="vault_root 不存在"):
        make_office(f"office_code: HC\nvault_root: {(tmp_path / 'nope').as_posix()}\n", create_vault=False)


@pytest.mark.parametrize("value", ["", "//<NAS>/<共享名>/知識庫/vault"])
def test_vault_root_required_and_not_placeholder(make_office, value):
    with pytest.raises(config.OfficeConfigError, match="vault_root"):
        make_office(f"office_code: HC\nvault_root: \"{value}\"\n")


def test_init_mode_allows_missing_vault_but_not_missing_parent(make_office, tmp_path):
    cfg, _, vault = make_office(create_vault=False, require_vault_exists=False)
    assert not vault.exists() and cfg["vault_root"] == vault.as_posix()
    deep = tmp_path / "a" / "b" / "vault"
    with pytest.raises(config.OfficeConfigError, match="上層資料夾不存在"):
        make_office(f"office_code: HC\nvault_root: {deep.as_posix()}\n", create_vault=False,
                    require_vault_exists=False)


def test_unknown_key_rejected(make_office, tmp_path):
    with pytest.raises(config.OfficeConfigError, match="無法辨識的欄位"):
        make_office(f"office_code: HC\nvault_roots: x\nvault_root: {(tmp_path / 'vault').as_posix()}\n")


def test_restricted_dir_names_from_config(make_office, tmp_path):
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: TP\nvault_root: {vault.as_posix()}\n"
                            "restricted_dir_names: [30_committees, 99_機密]\n")
    assert cfg["restricted_dir_names"] == ["30_committees", "99_機密"]
    assert config.restricted_dir_names(cfg) == ("30_committees", "99_機密")


@pytest.mark.parametrize("value", ["[]", "30_committees", "[a/b]", "[\"\"]"])
def test_restricted_dir_names_invalid(make_office, tmp_path, value):
    with pytest.raises(config.OfficeConfigError, match="restricted_dir_names"):
        make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\n"
                    f"restricted_dir_names: {value}\n")


@pytest.mark.parametrize("shared, message", [
    ("{rules: /abs/path}", "相對路徑"),
    ("{rules: C:/abs}", "相對路徑"),
    ("{rules: ../outside}", "相對路徑"),
    ("{rules: a/b, law_notes: a/b/c}", "互相包含"),
    ("{rules: x/30_Committees/_shared}", "限制級目錄"),
    ("{other: x}", "只接受"),
])
def test_shared_dirs_validation(make_office, tmp_path, shared, message):
    with pytest.raises(config.OfficeConfigError, match=message):
        make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\nshared_dirs: {shared}\n")


def test_shared_dirs_partial_override_keeps_default(make_office, tmp_path):
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\n"
                            "shared_dirs: {rules: '70_法規索引\\_shared'}\n")
    assert cfg["shared_dirs"]["rules"] == "70_法規索引/_shared"
    assert cfg["shared_dirs"]["law_notes"] == config.DEFAULT_SHARED_DIRS["law_notes"]


def test_extra_export_targets_must_be_absolute(make_office, tmp_path):
    with pytest.raises(config.OfficeConfigError, match="絕對路徑"):
        make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\n"
                    "extra_export_targets: [relative/dir]\n")
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\n"
                            f"extra_export_targets: ['{tmp_path.as_posix()}', '//nas/share/x']\n")
    assert len(cfg["extra_export_targets"]) == 2


def test_offices_yaml_list_and_top_level_forms(tmp_path):
    listed = tmp_path / "list.yaml"
    listed.write_text("offices:\n  - {code: TN, name: 臺南}\n  - {office_code: HC}\n", encoding="utf-8")
    assert set(config.load_office_codes(listed)) == {"TN", "HC"}
    top = tmp_path / "top.yaml"
    top.write_text("TN: 臺南\nTP: {name: 台北}\n", encoding="utf-8")
    assert set(config.load_office_codes(top)) == {"TN", "TP"}
    empty = tmp_path / "empty.yaml"
    empty.write_text("offices: {}\n", encoding="utf-8")
    with pytest.raises(config.OfficeConfigError, match="沒有任何有效代碼"):
        config.load_office_codes(empty)
    with pytest.raises(config.OfficeConfigError, match="找不到辦公室代碼表"):
        config.load_office_codes(tmp_path / "none.yaml")


def test_duplicate_key_in_office_yaml_fails(make_office, tmp_path):
    with pytest.raises(config.OfficeConfigError, match="格式錯誤"):
        make_office(f"office_code: HC\noffice_code: TP\nvault_root: {(tmp_path / 'vault').as_posix()}\n")


def test_repo_offices_yaml_parses_if_present():
    """repo 根的 offices.yaml（由手冊作者維護）必須能被本模組讀出 TN/HC/TP。"""
    path = config.REPO_ROOT / config.OFFICES_NAME
    if not path.is_file():
        pytest.skip("repo 根尚無 offices.yaml")
    assert {"TN", "HC", "TP"} <= set(config.load_office_codes(path))


def test_repo_example_config_has_only_known_keys():
    path = config.REPO_ROOT / config.EXAMPLE_NAME
    if not path.is_file():
        pytest.skip("repo 根尚無 office.example.yaml")
    from ykkb.metadata import load_yaml
    data = load_yaml(path.read_text(encoding="utf-8"))
    assert set(data) <= config.ALLOWED_KEYS


def test_require_office_field_must_be_bool(make_office, tmp_path):
    vault = (tmp_path / "vault").as_posix()
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {vault}\nrequire_office_field: true\n")
    assert cfg["require_office_field"] is True
    with pytest.raises(config.OfficeConfigError, match="require_office_field"):
        make_office(f"office_code: HC\nvault_root: {vault}\nrequire_office_field: 'yes'\n")


def test_sync_backup_dir_must_be_absolute(make_office, tmp_path):
    vault = (tmp_path / "vault").as_posix()
    with pytest.raises(config.OfficeConfigError, match="sync_backup_dir"):
        make_office(f"office_code: HC\nvault_root: {vault}\nsync_backup_dir: relative/bk\n")
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {vault}\nsync_backup_dir: {(tmp_path / 'bk').as_posix()}\n")
    assert Path(cfg["sync_backup_dir"]) == tmp_path / "bk"


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="需要 git")
def test_gitignore_rules(tmp_path):
    """office.yaml 及其副本、office_*.yaml、_sync_backups/ 要被忽略；offices.yaml 與範本不可被擋。"""
    import shutil
    import subprocess
    shutil.copy(config.REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    def ignored(rel):
        return subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q", rel]).returncode == 0

    for rel in ("office.yaml", "office.yaml.bak", "office.yaml.bak_20261117", "office_tn.yaml",
                "_sync_backups/sync_x/a.md", "_build/x", "core/__pycache__/a.pyc"):
        assert ignored(rel), rel
    for rel in ("offices.yaml", "office.example.yaml", "core/knowledge_schema.yaml", "exports/法令檢核規則庫.csv",
                "CHANGELOG.md"):
        assert not ignored(rel), rel


def test_gitattributes_changelog_union():
    text = (config.REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "CHANGELOG.md merge=union" in text