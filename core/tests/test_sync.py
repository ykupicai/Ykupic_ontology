# -*- coding: utf-8 -*-
"""sync_to_vault：同步清單與中止機制、--adopt／--force、vault 外備份區、同步前一致性檢查、
中途失敗不破壞原資料夾、額外匯出留 .bak。全部在暫存目錄，不寫 repo 根。"""
import contextlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import sync_to_vault as sync
import vault_audit

CLEAN = {"export_check": lambda root: [], "git_check": lambda root: ([], None)}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "exports").mkdir(parents=True)
    (root / "exports" / "法令檢核規則庫.csv").write_bytes("﻿規則ID,名稱\r\nA-1,測試\r\n".encode("utf-8"))
    (root / "exports" / "法令檢核規則庫.xlsx").write_bytes(b"PK\x03\x04fake-xlsx")
    (root / "exports" / "說明.txt").write_text("不同步", encoding="utf-8")
    notes = root / "law_notes"
    (notes / "_附表原檔").mkdir(parents=True)
    (notes / "甲法-重點.md").write_text("---\ntype: law-digest\n---\n見 [[總部案件]]\n", encoding="utf-8")
    (notes / "乙法-重點.md").write_text("---\ntype: law-digest\n---\n見 [[甲法-重點]]\n", encoding="utf-8")
    (notes / "_附表原檔" / "附表.pdf").write_bytes(b"%PDF-1.4 fake")
    return root


@pytest.fixture
def office(make_office, tmp_path):
    cfg, office_path, vault = make_office()
    assert Path(cfg["sync_backup_dir"]) == tmp_path / "sync_backups"
    return cfg, vault


def do_sync(cfg, repo, **kwargs):
    options = dict(CLEAN, commit="abc1234def")
    options.update(kwargs)
    return sync.sync(cfg, repo_root=repo, **options)


def targets(cfg):
    vault = Path(cfg["vault_root"])
    return (vault.joinpath(*cfg["shared_dirs"]["rules"].split("/")),
            vault.joinpath(*cfg["shared_dirs"]["law_notes"].split("/")))


def backups(cfg):
    root = Path(cfg["sync_backup_dir"])
    return sorted(root.iterdir()) if root.is_dir() else []


# --- 基本同步與清單 -------------------------------------------------------------------

def test_sync_places_files_readme_and_manifest(office, repo):
    cfg, vault = office
    do_sync(cfg, repo)
    rules, laws = targets(cfg)
    assert sorted(p.name for p in rules.iterdir()) == [".sync_manifest.json", "README_唯讀.md",
                                                      "法令檢核規則庫.csv", "法令檢核規則庫.xlsx"]
    assert (rules / "法令檢核規則庫.csv").read_bytes() == (repo / "exports" / "法令檢核規則庫.csv").read_bytes()
    assert (laws / "_附表原檔" / "附表.pdf").read_bytes() == b"%PDF-1.4 fake"
    readme = (laws / "README_唯讀.md").read_text(encoding="utf-8")
    assert "勿在此編輯" in readme and "abc1234def" in readme and "檔案數：3" in readme
    manifest = json.loads((laws / ".sync_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == "abc1234def" and manifest["synced_at"]
    assert set(manifest["files"]) == {"甲法-重點.md", "乙法-重點.md", "_附表原檔/附表.pdf", "README_唯讀.md"}
    assert manifest["files"]["甲法-重點.md"] == sync.sha256(repo / "law_notes" / "甲法-重點.md")
    assert backups(cfg) == []          # 第一次同步、目的地不存在 → 不用備份


def test_resync_unchanged_target_succeeds_and_backs_up(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    (repo / "law_notes" / "甲法-重點.md").write_text("---\ntype: law-digest\n---\n新版\n", encoding="utf-8")
    do_sync(cfg, repo)
    _, laws = targets(cfg)
    assert "新版" in (laws / "甲法-重點.md").read_text(encoding="utf-8")
    runs = backups(cfg)
    assert len(runs) == 1 and sync.BACKUP_NAME.match(runs[0].name)
    assert "見 [[總部案件]]" in (runs[0] / "law_notes" / "甲法-重點.md").read_text(encoding="utf-8")


def test_local_addition_blocks_sync_and_writes_nothing(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    rules, laws = targets(cfg)
    (laws / "同事新增.md").write_text("手寫補充", encoding="utf-8")
    before = {p: p.read_bytes() for p in laws.rglob("*") if p.is_file()}
    with pytest.raises(sync.SyncBlocked) as info:
        do_sync(cfg, repo, commit="def5678abc")
    message = str(info.value)
    assert "同事新增.md" in message and "併進 repo" in message and "--force" in message
    assert {p: p.read_bytes() for p in laws.rglob("*") if p.is_file()} == before
    assert "abc1234def" in (rules / "README_唯讀.md").read_text(encoding="utf-8")   # 另一區也沒動
    assert backups(cfg) == []


def test_local_modification_blocks_sync(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    _, laws = targets(cfg)
    (laws / "乙法-重點.md").write_text("被手改", encoding="utf-8")
    with pytest.raises(sync.SyncBlocked, match="本地修改 1 檔"):
        do_sync(cfg, repo)
    assert (laws / "乙法-重點.md").read_text(encoding="utf-8") == "被手改"


def test_local_deletion_does_not_block(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    _, laws = targets(cfg)
    (laws / "乙法-重點.md").unlink()
    do_sync(cfg, repo)
    assert (laws / "乙法-重點.md").is_file()


def test_force_overrides_but_backs_up_first(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    _, laws = targets(cfg)
    (laws / "同事新增.md").write_text("手寫補充", encoding="utf-8")
    log = do_sync(cfg, repo, force=True)
    assert not (laws / "同事新增.md").exists()
    assert any("--force" in line for line in log)
    saved = backups(cfg)[0] / "law_notes" / "同事新增.md"
    assert saved.read_text(encoding="utf-8") == "手寫補充"


def test_unmanaged_nonempty_target_requires_adopt(office, repo):
    """第一次切換：目的地已有內容（含 _local/）但沒有清單 → 擋下；--adopt 才接管，且先備份。"""
    cfg, _ = office
    _, laws = targets(cfg)
    (laws / "_local").mkdir(parents=True)
    (laws / "_local" / "本地補充.md").write_text("本地", encoding="utf-8")
    (laws / "舊法規.md").write_text("舊", encoding="utf-8")
    with pytest.raises(sync.SyncBlocked, match="--adopt") as info:
        do_sync(cfg, repo)
    assert "_local/本地補充.md" in str(info.value)
    assert (laws / "_local" / "本地補充.md").is_file()
    with pytest.raises(sync.SyncBlocked):
        do_sync(cfg, repo, force=True)            # --force 不等於 --adopt
    log = do_sync(cfg, repo, adopt=True)
    assert any("接管（--adopt）" in line for line in log)
    assert not (laws / "_local").exists()
    saved = backups(cfg)[0] / "law_notes"
    assert (saved / "_local" / "本地補充.md").read_text(encoding="utf-8") == "本地"
    assert (saved / "舊法規.md").read_text(encoding="utf-8") == "舊"


def test_empty_existing_target_is_treated_as_new(office, repo):
    cfg, _ = office
    rules, laws = targets(cfg)
    laws.mkdir(parents=True)
    (laws / "Thumbs.db").write_bytes(b"x")       # 系統雜檔不算內容
    do_sync(cfg, repo)
    assert (laws / ".sync_manifest.json").is_file()


def test_broken_manifest_requires_adopt(office, repo):
    cfg, _ = office
    do_sync(cfg, repo)
    _, laws = targets(cfg)
    (laws / ".sync_manifest.json").write_text("{壞掉", encoding="utf-8")
    with pytest.raises(sync.SyncBlocked, match="--adopt"):
        do_sync(cfg, repo)


# --- 同步前 repo 檢查 ------------------------------------------------------------------

def test_export_inconsistency_blocks_even_with_force(office, repo):
    cfg, vault = office
    with pytest.raises(sync.SyncBlocked, match="rulebook_export.py"):
        do_sync(cfg, repo, force=True, export_check=lambda root: ["exports/法令檢核規則庫.csv 與 rules/ 不一致"])
    assert list(vault.iterdir()) == []


def test_uncommitted_changes_block_even_with_force(office, repo):
    cfg, vault = office
    with pytest.raises(sync.SyncBlocked, match="未提交"):
        do_sync(cfg, repo, force=True, adopt=True, git_check=lambda root: ([" M law_notes/甲法-重點.md"], None))
    assert list(vault.iterdir()) == []


def test_not_a_git_repo_is_skipped_with_note(office, repo):
    cfg, _ = office
    dirty, note = sync.check_git_clean(repo)
    assert dirty == [] and "略過" in note
    log = do_sync(cfg, repo, git_check=sync.check_git_clean)
    assert any("略過未提交修改檢查" in line for line in log)


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_git_dirty_detection_in_real_repo(repo):
    run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    run("init", "-q")
    run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    assert sync.check_git_clean(repo) == ([], None)
    (repo / "law_notes" / "甲法-重點.md").write_text("改", encoding="utf-8")
    dirty, note = sync.check_git_clean(repo)
    assert note is None and any("law_notes" in line for line in dirty)


def test_real_export_check_reports_failure_instead_of_crashing(tmp_path):
    problems = sync.check_exports(tmp_path)       # 沒有 rules/ 的資料夾
    assert problems


# --- 備份區 ------------------------------------------------------------------------

def test_backup_dir_inside_vault_is_rejected(make_office, tmp_path):
    from ykkb import config
    vault = tmp_path / "vault"
    with pytest.raises(config.OfficeConfigError, match="不可位於 vault_root 內"):
        make_office(f"office_code: HC\nvault_root: {vault.as_posix()}\nsync_backup_dir: {(vault / 'bk').as_posix()}\n")


def test_default_backup_dir_is_repo_root(make_office, tmp_path):
    from ykkb import config
    cfg, _, _ = make_office(f"office_code: HC\nvault_root: {(tmp_path / 'vault').as_posix()}\n")
    assert Path(cfg["sync_backup_dir"]) == config.REPO_ROOT / "_sync_backups"


def test_prune_keeps_latest_ten_and_ignores_foreign_dirs(tmp_path):
    root = tmp_path / "bk"
    names = [f"sync_202611{day:02d}-120000-000000_HC" for day in range(1, 14)]
    for name in names:
        (root / name).mkdir(parents=True)
    (root / "我的資料").mkdir()
    (root / "sync_亂取名").mkdir()
    (root / "sync_20261101-120000-000000_HC.txt").write_text("檔案不是資料夾", encoding="utf-8")
    removed = sync.prune_backups(root)
    assert [p.name for p in removed] == names[:3]
    left = {p.name for p in root.iterdir()}
    assert set(names[3:]) <= left and {"我的資料", "sync_亂取名", "sync_20261101-120000-000000_HC.txt"} <= left


# --- 失敗安全 ----------------------------------------------------------------------

def test_failure_midway_keeps_original(office, repo, tmp_path):
    cfg, _ = office
    _, laws = targets(cfg)
    laws.mkdir(parents=True)
    (laws / "原本.md").write_text("原內容", encoding="utf-8")
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("模擬網路中斷")
        return shutil.copy2(src, dst)

    items = sync.collect_tree(repo / "law_notes")
    with pytest.raises(OSError, match="模擬網路中斷"):
        sync.replace_dir(laws, items, "readme", backup_to=tmp_path / "bk" / "x", copier=flaky)
    assert sorted(p.name for p in laws.iterdir()) == ["原本.md"]
    assert (laws / "原本.md").read_text(encoding="utf-8") == "原內容"
    assert [p for p in laws.parent.iterdir() if ".sync_" in p.name] == []


def test_replace_refuses_without_backup_location(office, repo):
    cfg, _ = office
    rules, _ = targets(cfg)
    rules.mkdir(parents=True)
    (rules / "舊.csv").write_text("舊", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="備份"):
        sync.replace_dir(rules, sync.collect_exports(repo / "exports"), "readme")
    assert [p.name for p in rules.iterdir()] == ["舊.csv"]


def test_hash_mismatch_aborts_and_keeps_original(office, repo, tmp_path):
    cfg, _ = office
    rules, _ = targets(cfg)
    rules.mkdir(parents=True)
    (rules / "舊.csv").write_text("舊", encoding="utf-8")

    def corrupting(src, dst):
        Path(dst).write_bytes(b"corrupted")

    with pytest.raises(sync.SyncError, match="SHA256"):
        sync.replace_dir(rules, sync.collect_exports(repo / "exports"), "readme",
                         backup_to=tmp_path / "bk" / "x", copier=corrupting)
    assert [p.name for p in rules.iterdir()] == ["舊.csv"]


def test_missing_sources_abort_before_touching_vault(office, repo):
    cfg, _ = office
    rules, _ = targets(cfg)
    rules.mkdir(parents=True)
    (rules / "舊.csv").write_text("舊", encoding="utf-8")
    shutil.rmtree(repo / "law_notes")
    with pytest.raises(sync.SyncError, match="找不到來源資料夾"):
        do_sync(cfg, repo)
    assert [p.name for p in rules.iterdir()] == ["舊.csv"]


def test_dry_run_writes_nothing_but_still_checks(office, repo):
    cfg, vault = office
    log = do_sync(cfg, repo, dry_run=True)
    assert any("將以 3 檔" in line for line in log)
    assert list(vault.iterdir()) == []
    _, laws = targets(cfg)
    laws.mkdir(parents=True)
    (laws / "x.md").write_text("x", encoding="utf-8")
    with pytest.raises(sync.SyncBlocked):
        do_sync(cfg, repo, dry_run=True)


def test_leftover_staging_from_previous_crash_is_cleaned(office, repo):
    cfg, _ = office
    _, laws = targets(cfg)
    stale = laws.parent / f".{laws.name}.sync_tmp_20260101-000000-000000"
    stale.mkdir(parents=True)
    (stale / "半套.md").write_text("x", encoding="utf-8")
    log = do_sync(cfg, repo)
    assert not stale.exists()
    assert any("已清除先前中斷留下的暫存資料夾" in line for line in log)


# --- 額外匯出目標 -------------------------------------------------------------------

def test_extra_export_targets_keep_backup(make_office, repo, tmp_path):
    extra = tmp_path / "下游工具"
    extra.mkdir()
    (extra / "法令檢核規則庫.csv").write_text("舊版", encoding="utf-8")
    (extra / "法令檢核規則庫.xlsx").write_bytes(b"PK\x03\x04fake-xlsx")   # 內容相同 → 不留 bak
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: TN\nvault_root: {vault.as_posix()}\n"
                            f"sync_backup_dir: {(tmp_path / 'bk').as_posix()}\n"
                            f"extra_export_targets: ['{extra.as_posix()}']\n")
    log = do_sync(cfg, repo)
    assert (extra / "法令檢核規則庫.csv").read_bytes() == (repo / "exports" / "法令檢核規則庫.csv").read_bytes()
    found = list(extra.glob("法令檢核規則庫.csv.bak_*"))
    assert len(found) == 1 and found[0].read_text(encoding="utf-8") == "舊版"
    assert list(extra.glob("法令檢核規則庫.xlsx.bak_*")) == []
    assert any("相同略過 法令檢核規則庫.xlsx" in line for line in log)
    assert not (extra / "說明.txt").exists()


def test_missing_extra_target_aborts_before_vault_write(make_office, repo, tmp_path):
    vault = tmp_path / "vault"
    cfg, _, _ = make_office(f"office_code: TN\nvault_root: {vault.as_posix()}\n"
                            f"sync_backup_dir: {(tmp_path / 'bk').as_posix()}\n"
                            f"extra_export_targets: ['{(tmp_path / 'none').as_posix()}']\n")
    with pytest.raises(sync.SyncBlocked, match="不存在"):
        do_sync(cfg, repo)
    assert list(vault.iterdir()) == []


# --- 與健檢的整合 -------------------------------------------------------------------

def test_synced_vault_audits_clean_and_reports_lag(office, repo):
    cfg, _ = office
    do_sync(cfg, repo, commit="a" * 40)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert vault_audit.run_audit(cfg, repo_head=lambda root: "a" * 40) == 0
    report = out.getvalue()
    assert "■ 壞連結（指向不存在筆記）：0 個目標" in report
    assert "共用筆記連到其他辦公室的筆記）：1 個目標" in report
    assert "已與 repo 同步" in report and "落後" not in report
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert vault_audit.run_audit(cfg, repo_head=lambda root: "b" * 40) == 0   # 落後只示警
    assert out.getvalue().count("⚠ vault 落後於 repo") == 2


def test_audit_lag_falls_back_to_readme_and_reports_unsynced(office):
    cfg, vault = office
    rules, _ = targets(cfg)
    rules.mkdir(parents=True)
    (rules / "README_唯讀.md").write_text("- 來源 commit：c0ffee12345\n", encoding="utf-8")
    lines = vault_audit.sync_status_lines(cfg, repo_head=lambda root: "c0ffee12345")
    assert any(line.startswith("[rules] 已與 repo 同步") for line in lines)
    assert any(line.startswith("[law_notes] 尚未同步") for line in lines)
    lines = vault_audit.sync_status_lines(cfg, repo_head=lambda root: "unknown")
    assert any("無法取得 repo commit" in line for line in lines)


def test_source_commit_unknown_outside_git(tmp_path):
    assert sync.source_commit(tmp_path) == "unknown"


def test_main_returns_2_on_bad_config(tmp_path):
    with contextlib.redirect_stdout(io.StringIO()):
        assert sync.main(["--config", str(tmp_path / "none.yaml")]) == 2
