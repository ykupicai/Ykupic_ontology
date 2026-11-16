"""安裝 git pre-push hook：每次 git push 前自動跑 core/tools/rule_check.py --pre-push。

用法：python -X utf8 core/tools/install_hooks.py
- hook 不隨 repo 同步，每台電腦 clone 後各裝一次；重跑會更新成最新版。
- 已有不同內容的 pre-push hook 時，先備份成 pre-push.bak-<時間>，再寫入新的。
- Windows 的 git 用內建 sh 執行 hook；hook 依序嘗試「安裝時的 Python」、python3、python、py，
  採用第一個能執行且版本 ≥ 3.12 的（Windows 市集版 python3 假捷徑會被版本檢查排除）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

MARKER = "# ykkb-pre-push-hook"

HOOK_TEMPLATE = """#!/bin/sh
{marker}（由 core/tools/install_hooks.py 產生；要更新請重跑該程式，不要手改）
# push 前跑規則檢查；未通過就擋下 push。
repo_root="$(git rev-parse --show-toplevel)" || exit 1
script="$repo_root/core/tools/rule_check.py"
if [ ! -f "$script" ]; then
  echo "pre-push：找不到 $script，略過規則檢查" >&2
  exit 0
fi
for py in {candidates}; do
  if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
    exec "$py" -X utf8 "$script" --pre-push "$@"
  fi
done
echo "pre-push：找不到 Python 3.12 以上（試過 {candidates_text}），無法執行規則檢查，已擋下 push。" >&2
echo "請安裝 Python 3.12+，或重跑 python -X utf8 core/tools/install_hooks.py。" >&2
exit 1
"""


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def render_hook(python_exe: str | None = None) -> str:
    cands = []
    if python_exe:
        cands.append(Path(python_exe).as_posix())
    cands += ["python3", "python", "py"]
    seen, uniq = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return HOOK_TEMPLATE.format(marker=MARKER, candidates=" ".join(_sh_quote(c) for c in uniq),
                                candidates_text="、".join(uniq))


def hook_path(repo_root: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--git-path", "hooks/pre-push"], cwd=repo_root,
                         capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"{repo_root} 不是 git repo（或 git 無法執行）：{out.stderr.strip()}")
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else (repo_root / path)


def install(repo_root: Path, python_exe: str | None = None) -> str:
    path = hook_path(repo_root)
    content = render_hook(python_exe)
    data = content.encode("utf-8")
    if path.is_file():
        old = path.read_bytes()
        if old == data:
            return f"pre-push hook 已是最新：{path}"
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"pre-push.bak-{stamp}")
        n = 1
        while backup.exists():
            backup = path.with_name(f"pre-push.bak-{stamp}-{n}")
            n += 1
        backup.write_bytes(old)
        note = f"（原 hook 已備份為 {backup.name}）"
    else:
        note = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)   # LF 換行；Windows 的 git sh 遇到 CRLF 會失敗
    try:
        path.chmod(0o755)
    except OSError:
        pass
    return f"已安裝 pre-push hook：{path}{note}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2], help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        print(install(a.repo_root.resolve(), sys.executable))
    except RuntimeError as exc:
        print(f"安裝失敗：{exc}")
        return 1
    print("之後每次 git push 前會自動跑規則檢查；不要用 git push --no-verify 跳過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
