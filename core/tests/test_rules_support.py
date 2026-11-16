"""規則庫測試共用：在暫存目錄建一個最小的假 repo（不依賴 NAS、不動真 repo）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
for p in (CORE, CORE / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ykkb import rules as rl  # noqa: E402

COLUMNS = rl.load_fields(REPO)["columns"]


def make_rule(rule_id, **ext):
    data = {c: "—" for c in COLUMNS}
    data.update({"rule_id": rule_id, "法規": "測試法規", "法規代碼": "D0060013", "現行版本": "113.01.01",
                 "編": "—", "條號": "第一條", "條文要旨": f"{rule_id} 要旨", "適用辦理方式": "變更編定",
                 "回答型態": "6實質計算", "進綜理表": "是", "核對狀態": "已核對"})
    base = {"status": "active", "superseded_by": None, "added_by": "TN", "reviewed_by": None,
            "reviewed_at": None, "source_url": None, "legacy_import": False}
    base.update(ext)
    data.update(base)
    return data


def write_rule(root: Path, rel_dir: str, data: dict, name: str | None = None) -> Path:
    d = root / "rules" / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name or data['rule_id']}.yaml"
    p.write_bytes(rl.dump_rule(data).encode("utf-8"))
    return p


def build_repo(root: Path, with_core: bool = False) -> Path:
    """建立假 repo：真 _fields.yaml、2 條匯入規則、1 條非匯入正式規則、精簡 _meta，並產生 exports。"""
    (root / "rules/_meta").mkdir(parents=True)
    shutil.copy2(REPO / "rules/_fields.yaml", root / "rules/_fields.yaml")
    shutil.copy2(REPO / "offices.yaml", root / "offices.yaml")
    for o in ("TN", "HC", "TP"):
        (root / "rules/pending" / o).mkdir(parents=True)
        (root / "rules/pending" / o / ".gitkeep").write_bytes(b"")
    (root / "rules/_meta/workbook.yaml").write_text(rl.dump_yaml({"sheets": [
        {"name": "00_說明", "file": "00_說明.yaml", "layout": {"freeze_panes": "A2"}},
        {"name": "20_規則庫", "source": "rules", "layout": {"column_widths": {"A": 12.0}, "freeze_panes": "A2"}},
    ]}), encoding="utf-8", newline="\n")
    (root / "rules/_meta/00_說明.yaml").write_text(rl.dump_yaml({
        "sheet": "00_說明", "format": "records", "width": 2, "columns": ["項目", "內容"],
        "rows": [{"項目": "文件", "內容": "測試\n第二行"}, {"項目": "空白", "內容": None}]}),
        encoding="utf-8", newline="\n")
    legacy = []
    for rid, folder in (("GEN-001", "national"), ("TNN-001", "local/TNN")):
        data = make_rule(rid, legacy_import=True)
        if rid == "TNN-001":
            data["法規代碼"] = "GL000306(臺南市)"
        write_rule(root, folder, data)
        legacy.append({"rule_id": rid, "content_sha256": rl.content_digest(data, COLUMNS)})
    (root / rl.LEGACY_FILE).write_text(rl.dump_yaml({"rules": legacy}), encoding="utf-8", newline="\n")
    write_rule(root, "national", make_rule("GEN-002", added_by="HC", reviewed_by="TN", reviewed_at="2026-11-20",
                                           source_url="https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"))
    if with_core:
        shutil.copytree(CORE, root / "core", ignore=shutil.ignore_patterns("__pycache__", "tests", ".pytest_cache"))
    export(root)
    return root


def export(root: Path):
    import rulebook_export
    rulebook_export.export(root)


def check(root: Path, mode="local", stdin_text=None, office_config=None, base=None):
    """跑 rule_check.run，回 (結束碼, 輸出文字)。"""
    import contextlib
    import io

    import rule_check
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = rule_check.run(root, mode, base, office_config, stdin_text)
    return code, buf.getvalue()


def write_office(root: Path, code: str) -> Path:
    (root / "vault").mkdir(exist_ok=True)
    p = root / "office.yaml"
    p.write_text(f"office_code: {code}\nvault_root: {(root / 'vault').as_posix()}\n", encoding="utf-8")
    return p


GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}


def git(root: Path, *args, check=True, input_text=None):
    res = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", *args], cwd=root,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=GIT_ENV, input=input_text)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{res.stdout}{res.stderr}")
    return res


def commit_all(root: Path, msg="c") -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def has_git() -> bool:
    return shutil.which("git") is not None
