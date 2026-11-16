# -*- coding: utf-8 -*-
"""init_vault.py — 依 office.yaml 從 templates/vault/ 建立 vault 骨架。

- 範本整棵複製到 vault_root；**已存在的檔一律不覆蓋**（列出略過清單）。
- .md／.yaml／.yml 內的 {{OFFICE_CODE}}、{{OFFICE_NAME}} 佔位字串在複製時替換。
- .gitkeep 只是讓 git 保留空資料夾，不複製進 vault（資料夾照建）。
- vault_root 本身可以還不存在，但它的上層資料夾必須存在（不自動建多層路徑，避免打錯字建出整串資料夾）。

用法：python -X utf8 core/tools/init_vault.py [--dry-run] [--config office.yaml]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ykkb import config as office_config  # noqa: E402

TEMPLATE_DIR = office_config.REPO_ROOT / "templates" / "vault"
TEXT_SUFFIXES = {".md", ".yaml", ".yml"}
SKIP_NAMES = {".gitkeep"}


def render(text: str, cfg: dict) -> str:
    return (text.replace("{{OFFICE_CODE}}", cfg["office_code"])
                .replace("{{OFFICE_NAME}}", cfg["office_name"]))


def plan(template: Path, vault: Path):
    """回傳 (要建的資料夾, 要建的檔 [(src, dst)], 略過的既有檔 [dst])。"""
    new_dirs, new_files, skipped = [], [], []
    if not vault.exists():
        new_dirs.append(vault)
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        dst = vault / rel
        if src.is_dir():
            if not dst.exists():
                new_dirs.append(dst)
        elif src.name in SKIP_NAMES:
            continue
        elif dst.exists():
            skipped.append(dst)
        else:
            new_files.append((src, dst))
    return new_dirs, new_files, skipped


def init_vault(cfg: dict, *, template: Path = TEMPLATE_DIR, dry_run: bool = False) -> dict:
    template = Path(template)
    if not template.is_dir():
        raise FileNotFoundError(f"找不到 vault 範本資料夾：{template}")
    vault = Path(cfg["vault_root"])
    if vault.exists() and not vault.is_dir():
        raise NotADirectoryError(f"vault_root 已存在但不是資料夾：{vault}")
    new_dirs, new_files, skipped = plan(template, vault)
    if not dry_run:
        vault.mkdir(parents=False, exist_ok=True)  # 上層不存在時明確失敗
        for directory in new_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        for src, dst in new_files:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() in TEXT_SUFFIXES:
                text = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
                # 'x' 模式：萬一檢查後才出現同名檔，也不覆蓋
                with open(dst, "x", encoding="utf-8", newline="\n") as handle:
                    handle.write(render(text, cfg))
            else:
                if dst.exists():
                    skipped.append(dst)
                    continue
                shutil.copy2(src, dst)
    return {"dirs": new_dirs, "files": [dst for _, dst in new_files], "skipped": skipped}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="依 office.yaml 建立 vault 骨架（不覆蓋既有檔）")
    parser.add_argument("--dry-run", action="store_true", help="只列出會建立的資料夾與檔案")
    parser.add_argument("--config", help="office.yaml 路徑")
    parser.add_argument("--template", default=str(TEMPLATE_DIR), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        cfg = office_config.load_office_config(args.config, require_vault_exists=False)
    except office_config.OfficeConfigError as exc:
        print(f"[設定錯誤] {exc}")
        return 2
    try:
        result = init_vault(cfg, template=Path(args.template), dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"[錯誤] {exc}")
        return 1
    vault = Path(cfg["vault_root"])
    verb = "將建立" if args.dry_run else "已建立"
    print(f"vault：{cfg['vault_root']}（{cfg['office_code']} {cfg['office_name']}）")
    print(f"{verb}資料夾 {len(result['dirs'])} 個、檔案 {len(result['files'])} 個；略過既有檔 {len(result['skipped'])} 個")
    for path in result["dirs"]:
        print(f"   [資料夾] {path.relative_to(vault) if path != vault else '.'}")
    for path in result["files"]:
        print(f"   [檔案]   {path.relative_to(vault)}")
    if result["skipped"]:
        print("略過（已存在，不覆蓋）：")
        for path in result["skipped"]:
            print(f"   {path.relative_to(vault)}")
    if args.dry_run:
        print("（dry-run：未寫入任何檔案）")
    else:
        print("下一步：python -X utf8 core/tools/vault_audit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
