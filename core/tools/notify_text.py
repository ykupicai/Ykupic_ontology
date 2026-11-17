"""產生「規則庫更新通知」issue 留言內容（GitHub Actions 的 notify job 呼叫；也可本機試跑）。

用法：
  python -X utf8 core/tools/notify_text.py --before <push 前 SHA> --after <push 後 SHA> \
      --pusher <帳號> --run-url <Actions 連結> [--failed]
輸出 Markdown 到 stdout，不連網、不改檔。before 為全零（新分支、第一次 push）時改列規則檔總數。
留言文字由 build_message() 產生，可用假資料單元測試。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ykkb import rules as rl  # noqa: E402

ISSUE_TITLE = "規則庫更新通知"
ZERO_SHA = re.compile(r"^0*$")
MAX_COMMITS = 30


@dataclass
class RuleChanges:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    status_changed: list[str] = field(default_factory=list)
    format_only: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.added or self.modified or self.deleted or self.status_changed or self.format_only)


def parse_name_status(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0][0], parts[-1]))
    return out


def _label(rel: str) -> str:
    cat, group = rl.classify_rel(rel)
    stem = PurePosixPath(rel).stem
    where = {"national": "中央", "local": f"地方 {group}", "pending": f"待轉正 {group}"}.get(cat, rel)
    return f"`{stem}`（{where}）"


def classify_rule_changes(entries, load_old, load_new) -> RuleChanges:
    """entries：[(A|M|D, 路徑)]；load_old／load_new(路徑) → 解析後 dict 或 None。只看 rules/ 底下的規則檔。"""
    ch = RuleChanges()
    for status, rel in entries:
        if rl.classify_rel(rel)[0] == "unknown" or not rel.endswith((".yaml", ".yml")):
            continue
        label = _label(rel)
        if status == "A":
            ch.added.append(label)
        elif status == "D":
            ch.deleted.append(label)
        else:
            old, new = load_old(rel), load_new(rel)
            if old is None or new is None:
                ch.modified.append(label)
            elif old.get("status") != new.get("status"):
                extra = f"，取代者 `{new.get('superseded_by')}`" if new.get("superseded_by") else ""
                ch.status_changed.append(f"{label}：{old.get('status')} → {new.get('status')}{extra}")
            elif old != new:
                ch.modified.append(label)
            else:
                ch.format_only.append(label)
    return ch


def build_message(*, ok: bool, pusher: str, commits: list[tuple[str, str]], changes: RuleChanges | None,
                  law_notes_changed: bool | None, total_rule_files: int | None, run_url: str,
                  more_commits: int = 0, practice_notes_changed: bool | None = None) -> str:
    lines = []
    if ok:
        lines.append(f"### 規則庫已更新（推送者：{pusher}）")
    else:
        lines += [f"### ⚠ 檢查未通過（推送者：{pusher}）", "",
                  f"這次 push 到 main 的規則檢查或測試失敗，請推送者盡快修正；其他辦公室先不要 pull 這版。",
                  f"詳細記錄：{run_url}"]
    lines += ["", "**Commit**", ""]
    lines += [f"- `{sha}` {msg}" for sha, msg in commits] or ["- （無）"]
    if more_commits:
        lines.append(f"- ……另有 {more_commits} 個 commit 未列出")
    lines += ["", "**規則變動**", ""]
    if changes is None:
        lines.append(f"- 第一次推送或找不到比對基準，不列明細；目前共 {total_rule_files} 個規則檔。")
    elif changes.empty():
        lines.append("- 無規則檔變動")
    else:
        for title, items in (("新增", changes.added), ("修改", changes.modified), ("刪除", changes.deleted),
                             ("狀態變更", changes.status_changed), ("僅格式整理", changes.format_only)):
            if items:
                lines.append(f"- {title}（{len(items)}）：" + "、".join(items))
    lines += ["", "**法規筆記（law_notes/）**", ""]
    lines.append({True: "- 有變動", False: "- 無變動", None: "- 第一次推送，未比對"}[law_notes_changed])
    lines += ["", "**共用實務筆記（practice_notes/）**", ""]
    lines.append({True: "- 有變動", False: "- 無變動", None: "- 第一次推送，未比對"}[practice_notes_changed])
    if ok:
        lines += ["", "請各辦公室：`git pull` 後執行 `python -X utf8 core/tools/sync_to_vault.py`，"
                      "把規則、法規筆記與實務筆記同步到自己的 vault。"]
    lines += ["", f"Actions 記錄：{run_url}"] if ok else []
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- git 取資料

def _git(root: Path, *args) -> str | None:
    res = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True, check=False)
    return res.stdout.decode("utf-8", "replace") if res.returncode == 0 else None


def _show(root: Path, rev: str, rel: str):
    raw = _git(root, "show", f"{rev}:{rel}")
    if raw is None:
        return None
    try:
        return rl.load_rule_text(raw.lstrip("﻿"), rel)
    except rl.RuleFileError:
        return None


def collect(root: Path, before: str, after: str):
    valid_before = not ZERO_SHA.match(before or "") and _git(root, "rev-parse", "--verify", "--quiet",
                                                             f"{before}^{{commit}}") is not None
    if valid_before:
        log = _git(root, "log", "--no-merges", "--format=%h%x09%s", f"{before}..{after}") or ""
    else:
        log = _git(root, "log", "-1", "--format=%h%x09%s", after) or ""
    commits = [tuple(line.split("\t", 1)) for line in log.splitlines() if "\t" in line]
    more = max(0, len(commits) - MAX_COMMITS)
    commits = commits[:MAX_COMMITS]
    if not valid_before:
        listing = _git(root, "ls-tree", "-r", "--name-only", after, "--", "rules") or ""
        total = sum(1 for p in listing.splitlines() if rl.classify_rel(p)[0] != "unknown" and p.endswith(".yaml"))
        return commits, more, None, None, None, total
    entries = parse_name_status(_git(root, "diff", "--name-status", "--no-renames", before, after, "--", "rules/") or "")
    changes = classify_rule_changes(entries, lambda rel: _show(root, before, rel), lambda rel: _show(root, after, rel))
    law = bool((_git(root, "diff", "--name-only", before, after, "--", "law_notes/") or "").strip())
    practice = bool((_git(root, "diff", "--name-only", before, after, "--", "practice_notes/") or "").strip())
    return commits, more, changes, law, practice, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", default="")
    ap.add_argument("--after", default="HEAD")
    ap.add_argument("--pusher", default="(unknown)")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--failed", action="store_true", help="檢查未通過時的留言")
    ap.add_argument("--repo-root", type=Path, default=rl.REPO_ROOT)
    a = ap.parse_args(argv)
    commits, more, changes, law, practice, total = collect(a.repo_root.resolve(), a.before, a.after)
    sys.stdout.write(build_message(ok=not a.failed, pusher=a.pusher, commits=commits, changes=changes,
                                   law_notes_changed=law, total_rule_files=total, run_url=a.run_url,
                                   more_commits=more, practice_notes_changed=practice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
