# -*- coding: utf-8 -*-
"""sync_to_vault.py — 把 repo 的共用成果放進本辦公室 vault 的唯讀區。

- repo `exports/` 頂層的 .csv／.xlsx → vault 的 shared_dirs.rules
- repo `law_notes/` 整棵             → vault 的 shared_dirs.law_notes
- repo `practice_notes/` 整棵        → vault 的 shared_dirs.practice_notes（去識別化的共用實務筆記）
- 目的資料夾整個替換，但**不會無聲吃掉本地內容**：
  1. 每次同步在目的資料夾寫 `.sync_manifest.json`（相對路徑＋SHA256＋同步時間＋來源 commit）。
  2. 下次同步前比對：有清單以外的檔、或清單內的檔被改過 → 中止並列出，不寫任何東西
     （`--force` 可略過，仍會先備份）。
  3. 目的地非空但沒有清單（第一次同步、或既有資料夾首次改由同步管理）→ 中止，
     除非加 `--adopt`（明確表示目的地內容可被 repo 版本取代；仍會先備份）。
  4. 被替換的舊資料夾一律先完整複製到 vault 外的備份區（office.yaml 的 sync_backup_dir，
     預設 repo 根 `_sync_backups/`），只保留最近 10 份本腳本建立的備份。
- 同步前另檢查：exports 與 rules/ 一致（rulebook_export.check）、git 工作區 exports/、law_notes/、
  practice_notes/ 沒有未提交修改。這兩項 `--force` 不略過。
- 替換採「暫存資料夾寫完並驗 SHA256 → 換名」，中途失敗時原目的資料夾保持原樣。
- office.yaml 的 extra_export_targets 有值時，另把 exports 的 csv／xlsx 複製過去；
  覆蓋內容不同的同名檔前先改名留 `<檔名>.bak_<時間戳>`，內容相同則略過。

用法：python -X utf8 core/tools/sync_to_vault.py [--dry-run] [--force] [--adopt] [--config office.yaml]
結束碼：0 = 完成；1 = 中止或失敗（vault 未被改動，或只有已完成的那一區被替換）；2 = 設定錯誤。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ykkb import config as office_config  # noqa: E402

REPO_ROOT = office_config.REPO_ROOT
EXPORT_SUFFIXES = {".csv", ".xlsx"}
README_NAME = "README_唯讀.md"
MANIFEST_NAME = ".sync_manifest.json"
STAGING_MARK = ".sync_tmp_"
OLD_MARK = ".sync_old_"
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}
IGNORED_DIRS = {"__pycache__", ".git", ".obsidian", ".trash"}
BACKUP_KEEP = 10
BACKUP_NAME = re.compile(r"^sync_\d{8}-\d{6}-\d{6}_[A-Z][A-Z0-9]*$")
SYNC_SOURCES = ("exports", "law_notes", "practice_notes")


class SyncError(RuntimeError):
    pass


class SyncBlocked(SyncError):
    """同步前檢查不通過：vault 未被寫入任何東西。"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ignored(name: str) -> bool:
    return name in IGNORED_NAMES or name.startswith("~$")


def _posix(path: Path, base: Path) -> str:
    return PurePosixPath(*path.relative_to(base).parts).as_posix()


def collect_exports(exports_dir: Path) -> list[tuple[Path, str]]:
    if not exports_dir.is_dir():
        raise SyncError(f"找不到匯出資料夾：{exports_dir}")
    items = [(path, path.name) for path in sorted(exports_dir.iterdir())
             if path.is_file() and path.suffix.lower() in EXPORT_SUFFIXES and not _ignored(path.name)]
    if not items:
        raise SyncError(f"{exports_dir} 內沒有 csv／xlsx 可同步（請先跑 rulebook_export.py）。")
    return items


def collect_tree(source_dir: Path) -> list[tuple[Path, str]]:
    if not source_dir.is_dir():
        raise SyncError(f"找不到來源資料夾：{source_dir}")
    items = []
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(files):
            if _ignored(name):
                continue
            path = Path(root) / name
            items.append((path, _posix(path, source_dir)))
    if not items:
        raise SyncError(f"{source_dir} 內沒有檔案可同步。")
    return items


def _list_files(directory: Path) -> dict[str, Path]:
    """目的資料夾現有檔案（略過系統雜檔與清單本身）。"""
    found = {}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in files:
            if _ignored(name):
                continue
            path = Path(root) / name
            rel = _posix(path, directory)
            if rel != MANIFEST_NAME:
                found[rel] = path
    return found


# --- repo 端檢查 ------------------------------------------------------------------

def source_commit(repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and len(commit) >= 7 else "unknown"


def check_exports(repo_root: Path) -> list[str]:
    """呼叫 rulebook_export.check()；回傳問題清單（空＝一致）。"""
    module_path = Path(__file__).with_name("rulebook_export.py")
    if not module_path.is_file():
        return [f"找不到 {module_path.name}，無法確認 exports 與 rules/ 一致"]
    spec = importlib.util.spec_from_file_location("_ykkb_rulebook_export", module_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return list(module.check(repo_root))
    except Exception as exc:  # noqa: BLE001 — 檢查本身失敗也必須擋下同步
        return [f"一致性檢查執行失敗：{type(exc).__name__}: {exc}"]


def check_git_clean(repo_root: Path) -> tuple[list[str], str | None]:
    """回傳 (exports/、law_notes/、practice_notes/ 未提交修改清單, 略過說明)。不在 git repo 內時略過。"""
    try:
        result = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain", "--", *SYNC_SOURCES],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"無法執行 git（{type(exc).__name__}），略過未提交修改檢查"
    if result.returncode != 0:
        return [], "repo 不在 git 版控內，略過未提交修改檢查"
    return [line for line in result.stdout.splitlines() if line.strip()], None


# --- 目的地檢查 -------------------------------------------------------------------

def read_manifest(target: Path) -> dict | None:
    path = target / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyncBlocked(f"{path} 無法解析（{exc}）；請確認後加 --adopt 重新接管。") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise SyncBlocked(f"{path} 格式不符；請確認後加 --adopt 重新接管。")
    return data


def inspect_target(target: Path) -> dict:
    """回傳目的地狀態：state = new｜managed｜unmanaged，及本地新增／修改／刪除清單。"""
    if not target.exists():
        return {"state": "new", "extra": [], "modified": [], "deleted": [], "existing": 0}
    if not target.is_dir():
        raise SyncBlocked(f"同步目的地已存在但不是資料夾：{target}")
    files = _list_files(target)
    manifest = read_manifest(target) if (target / MANIFEST_NAME).exists() else None
    if manifest is None:
        return {"state": "unmanaged" if files else "new", "extra": sorted(files), "modified": [],
                "deleted": [], "existing": len(files)}
    recorded = manifest["files"]
    extra = sorted(rel for rel in files if rel not in recorded)
    modified = sorted(rel for rel, path in files.items() if rel in recorded and sha256(path) != recorded[rel])
    deleted = sorted(rel for rel in recorded if rel not in files)
    return {"state": "managed", "extra": extra, "modified": modified, "deleted": deleted,
            "existing": len(files), "manifest": manifest}


def _listing(paths, limit=15):
    lines = [f"      {p}" for p in paths[:limit]]
    if len(paths) > limit:
        lines.append(f"      …另 {len(paths) - limit} 檔")
    return lines


def judge_target(key: str, target: Path, status: dict, *, force: bool, adopt: bool) -> list[str]:
    """回傳擋下原因（空＝可同步）。"""
    if status["state"] == "unmanaged" and not adopt:
        return [f"[{key}] 目的地 {target} 已有 {status['existing']} 個檔，但沒有同步清單 {MANIFEST_NAME}"
                "（第一次同步，或這個資料夾以前不是由同步腳本管理）。",
                *_listing(status["extra"]),
                "   處理：確認這些內容都已在 repo（或已移到本地補充區）後，加 --adopt 重跑；"
                "被取代的舊內容會先備份到 vault 外的備份區。"]
    if status["state"] == "managed" and (status["extra"] or status["modified"]) and not force:
        lines = [f"[{key}] 目的地 {target} 有同步後的本地變動，下次同步會被覆蓋："]
        if status["extra"]:
            lines.append(f"   本地新增 {len(status['extra'])} 檔：")
            lines += _listing(status["extra"])
        if status["modified"]:
            lines.append(f"   本地修改 {len(status['modified'])} 檔：")
            lines += _listing(status["modified"])
        lines.append("   處理：把要保留的內容併進 repo（law_notes/、practice_notes/ 或 rules/）後 push，"
                     "或移到本地補充區（例：同層的 _local/），再重跑同步；"
                     "確定不要這些變動可加 --force（仍會先備份）。")
        return lines
    return []


# --- 備份 ------------------------------------------------------------------------

def backup_root(cfg: dict) -> Path:
    raw = cfg.get("sync_backup_dir") or str(REPO_ROOT / "_sync_backups")
    root = Path(raw)
    vault = os.path.normcase(os.path.abspath(cfg["vault_root"]))
    candidate = os.path.normcase(os.path.abspath(root))
    if candidate == vault or candidate.startswith(vault.rstrip("\\/") + os.sep):
        raise SyncBlocked(f"備份區 {root} 位於 vault 內；請在 office.yaml 設定 vault 外的 sync_backup_dir。")
    return root


def backup_dir(source: Path, destination: Path) -> int:
    """完整複製並逐檔核對 SHA256；回傳檔數。"""
    shutil.copytree(source, destination)
    original = _list_files(source)
    copied = _list_files(destination)
    if set(original) != set(copied) or any(sha256(original[rel]) != sha256(copied[rel]) for rel in original):
        raise SyncError(f"備份核對不符：{destination}（未替換 vault 內容）")
    return len(original)


def prune_backups(root: Path, keep: int = BACKUP_KEEP) -> list[Path]:
    """只刪名稱符合本腳本格式的備份資料夾，保留最新 keep 份；其他東西不碰。"""
    if not root.is_dir():
        return []
    ours = sorted((entry for entry in root.iterdir() if entry.is_dir() and BACKUP_NAME.match(entry.name)),
                  key=lambda entry: entry.name)
    removed = []
    for entry in ours[:-keep] if len(ours) > keep else []:
        shutil.rmtree(entry)
        removed.append(entry)
    return removed


# --- 替換 ------------------------------------------------------------------------

def readme_text(*, label: str, source: str, count: int, office: str, commit: str, synced_at: str) -> str:
    return (
        "---\n"
        "type: index\n"
        "generated_by: sync_to_vault\n"
        "---\n"
        f"# 唯讀：{label}\n\n"
        "**此資料夾由同步腳本 `core/tools/sync_to_vault.py` 每次整個覆蓋，勿在此編輯、勿在此新增筆記。**\n"
        "要修改內容請改共用 repo，push 後各辦公室 pull 再重新同步。在這裡新增或修改檔案，"
        "下次同步會被擋下並要求處理（本地補充內容請放在同步範圍以外的資料夾）。\n\n"
        f"- 同步時間：{synced_at}\n"
        f"- 來源 commit：{commit}\n"
        f"- 來源：repo 的 `{source}`\n"
        f"- 辦公室：{office}\n"
        f"- 檔案數：{count}（不含本檔與 {MANIFEST_NAME}）\n"
    )


def _cleanup_leftovers(target: Path) -> list[Path]:
    """清掉先前中斷留下的同名暫存／舊資料夾（只認本腳本的命名格式）。"""
    removed = []
    if not target.parent.is_dir():
        return removed
    prefix_tmp, prefix_old = f".{target.name}{STAGING_MARK}", f".{target.name}{OLD_MARK}"
    for entry in target.parent.iterdir():
        if entry.is_dir() and entry.name.startswith((prefix_tmp, prefix_old)):
            shutil.rmtree(entry)
            removed.append(entry)
    return removed


def replace_dir(target: Path, items: list[tuple[Path, str]], readme: str, *, manifest_meta: dict | None = None,
                backup_to: Path | None = None, copier=shutil.copy2) -> dict:
    """把 items 寫成新的 target（暫存→驗證→備份舊版→換名）。失敗時 target 保持原樣。

    target 已存在且非空時必須給 backup_to（舊版先完整複製到該處並核對）。"""
    items = [(src, rel) for src, rel in items if rel not in (README_NAME, MANIFEST_NAME)]
    had_old = target.is_dir() and bool(_list_files(target))
    if had_old and backup_to is None:
        raise SyncError(f"{target} 有既有內容，未指定備份位置，拒絕替換")
    removed = _cleanup_leftovers(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    staging = target.parent / f".{target.name}{STAGING_MARK}{stamp}"
    old = target.parent / f".{target.name}{OLD_MARK}{stamp}"
    try:
        staging.mkdir()
        expected = {}
        for src, rel in items:
            dst = staging.joinpath(*rel.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            copier(src, dst)
            expected[rel] = sha256(src)
        with open(staging / README_NAME, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(readme)
        actual = {rel: sha256(path) for rel, path in _list_files(staging).items() if rel != README_NAME}
        if set(actual) != set(expected):
            raise SyncError(f"暫存資料夾檔數不符：預期 {len(expected)}、實際 {len(actual)}")
        mismatched = sorted(rel for rel in expected if actual[rel] != expected[rel])
        if mismatched:
            raise SyncError(f"暫存資料夾 SHA256 不符：{mismatched[:5]}")
        files = dict(expected)
        files[README_NAME] = sha256(staging / README_NAME)
        manifest = dict(manifest_meta or {}, generated_by="sync_to_vault", files=dict(sorted(files.items())))
        with open(staging / MANIFEST_NAME, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        backed_up = backup_dir(target, backup_to) if had_old else 0
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    exists = target.exists()
    if exists:
        os.rename(target, old)
    try:
        os.rename(staging, target)
    except BaseException:
        if exists and not target.exists():
            os.rename(old, target)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    leftover = None
    if exists:
        try:
            shutil.rmtree(old)
        except OSError:
            leftover = old  # 新資料夾已就位；舊副本刪不掉只提示，下次同步會再清
    return {"target": target, "count": len(items), "replaced": had_old, "backed_up": backed_up,
            "cleaned": removed, "leftover": leftover}


def copy_extra(items: list[tuple[Path, str]], target_dir: Path, stamp: str, *, dry_run: bool = False) -> list[str]:
    log = []
    for src, name in items:
        dst = target_dir / name
        if dst.exists():
            if sha256(dst) == sha256(src):
                log.append(f"相同略過 {name}")
                continue
            backup = dst.with_name(f"{name}.bak_{stamp}")
            log.append(f"覆蓋 {name}（舊檔留 {backup.name}）")
            if not dry_run:
                os.rename(dst, backup)
        else:
            log.append(f"新增 {name}")
        if not dry_run:
            shutil.copy2(src, dst)
            if sha256(dst) != sha256(src):
                raise SyncError(f"額外匯出目標寫入後 SHA256 不符：{dst}")
    return log


# --- 主流程 ----------------------------------------------------------------------

def sync(cfg: dict, *, repo_root: Path = REPO_ROOT, dry_run: bool = False, force: bool = False,
         adopt: bool = False, commit: str | None = None, export_check=check_exports,
         git_check=check_git_clean) -> list[str]:
    """先做全部檢查（任何一項不過就丟 SyncBlocked，vault 一個檔都不寫），再逐區替換。"""
    vault = Path(cfg["vault_root"])
    log = []
    problems = export_check(repo_root)
    if problems:
        raise SyncBlocked("exports/ 與 rules/ 不一致，請先跑 python -X utf8 core/tools/rulebook_export.py 並 commit：\n"
                          + "\n".join(f"   {p}" for p in problems[:15]))
    dirty, git_note = git_check(repo_root)
    if dirty:
        raise SyncBlocked("exports/、law_notes/ 或 practice_notes/ 有未提交的修改；同步內容必須是已 commit 的版本：\n"
                          + "\n".join(f"   {line}" for line in dirty[:15]))
    if git_note:
        log.append(f"註：{git_note}")
    exports = collect_exports(repo_root / "exports")
    law_notes = collect_tree(repo_root / "law_notes")
    practice_notes = collect_tree(repo_root / "practice_notes")
    extras = [Path(item) for item in cfg.get("extra_export_targets") or []]
    missing = [str(path) for path in extras if not path.is_dir()]
    if missing:
        raise SyncBlocked(f"extra_export_targets 資料夾不存在（不自動建立）：{missing}")
    backups = backup_root(cfg)

    jobs = [
        ("rules", "法令檢核規則庫匯出", "exports/", exports),
        ("law_notes", "核心法規重點筆記", "law_notes/", law_notes),
        ("practice_notes", "共用實務筆記（去識別化）", "practice_notes/", practice_notes),
    ]
    blocked = []
    plans = []
    for key, label, source, items in jobs:
        target = vault.joinpath(*cfg["shared_dirs"][key].split("/"))
        status = inspect_target(target)
        blocked += judge_target(key, target, status, force=force, adopt=adopt)
        plans.append((key, label, source, items, target, status))
    if blocked:
        raise SyncBlocked("同步已中止，vault 未寫入任何檔案：\n" + "\n".join(blocked))

    commit = commit or source_commit(repo_root)
    synced_at = datetime.now().astimezone().isoformat(timespec="seconds")
    office = cfg.get("office_code", "?")
    run_dir = backups / f"sync_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}_{office}"
    for key, label, source, items, target, status in plans:
        note = {"new": "新建", "managed": "替換", "unmanaged": "接管（--adopt）"}[status["state"]]
        if status["state"] == "managed" and (status["extra"] or status["modified"]):
            note += f"（--force：覆蓋本地新增 {len(status['extra'])}、修改 {len(status['modified'])} 檔）"
        if dry_run:
            log.append(f"[{key}] 將以 {len(items)} 檔（＋{README_NAME}、{MANIFEST_NAME}）{note} {target}"
                       f"（現有 {status['existing']} 檔{'，會先備份' if status['existing'] else ''}）")
            continue
        count = len([i for i in items if i[1] not in (README_NAME, MANIFEST_NAME)])
        readme = readme_text(label=label, source=source, count=count, office=office, commit=commit, synced_at=synced_at)
        meta = {"synced_at": synced_at, "source_commit": commit, "office": office, "source": source}
        result = replace_dir(target, items, readme, manifest_meta=meta, backup_to=run_dir / key)
        log.append(f"[{key}] 已同步 {result['count']} 檔 → {target}（{note}）")
        if result["backed_up"]:
            log.append(f"   舊內容 {result['backed_up']} 檔已備份到 {run_dir / key}")
        for path in result["cleaned"]:
            log.append(f"   已清除先前中斷留下的暫存資料夾 {path.name}")
        if result["leftover"]:
            log.append(f"   ⚠ 舊副本刪除失敗，請手動刪除：{result['leftover']}")
    if not dry_run:
        for path in prune_backups(backups):
            log.append(f"   已刪除較舊的同步備份 {path.name}（保留最近 {BACKUP_KEEP} 份）")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for target_dir in extras:
        log.append(f"[extra] {target_dir}")
        log.extend("   " + line for line in copy_extra(exports, target_dir, stamp, dry_run=dry_run))
    log.append(f"來源 commit：{commit}")
    return log


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="把 repo 的 exports、law_notes、practice_notes 同步到 vault 唯讀區")
    parser.add_argument("--dry-run", action="store_true", help="只做檢查並列出會做的事，不寫入")
    parser.add_argument("--force", action="store_true",
                        help="目的地有本地新增／修改時仍覆蓋（會先備份；不略過 exports 一致性與 git 檢查）")
    parser.add_argument("--adopt", action="store_true",
                        help="目的地非空但沒有同步清單時，確認可由 repo 版本取代（會先備份）")
    parser.add_argument("--config", help="office.yaml 路徑")
    args = parser.parse_args(argv)
    try:
        cfg = office_config.load_office_config(args.config)
    except office_config.OfficeConfigError as exc:
        print(f"[設定錯誤] {exc}")
        return 2
    try:
        log = sync(cfg, dry_run=args.dry_run, force=args.force, adopt=args.adopt)
    except SyncBlocked as exc:
        print(f"[同步中止] {exc}")
        return 1
    except (SyncError, OSError) as exc:
        print(f"[同步失敗] {exc}（失敗的那一區維持原樣；修正後重跑即可）")
        return 1
    for line in log:
        print(line)
    if args.dry_run:
        print("（dry-run：未寫入任何檔案）")
    else:
        print("下一步：python -X utf8 core/tools/vault_audit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
