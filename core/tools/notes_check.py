"""practice_notes/ 去識別化檢查（禁字＋frontmatter）。由 rule_check.py 呼叫（push 前 hook 與 CI），也可單獨跑。

用法：python -X utf8 core/tools/notes_check.py [--repo-root <repo>]
結束碼：0 通過；1 有錯誤。

每篇 .md 必須：
  - 有 frontmatter，含 type、source_office（offices.yaml 內的代碼）、deidentified: true、updated（YYYY-MM-DD）
  - 不得標 sensitivity: restricted／confidential
  - 不得含：內網 IP、NAS 共享名、磁碟機或 UNC 實體路徑、公司行號全名（本公司除外）、地段地號、
    公文文號、案件代碼（C001、M035、S012 這類）
  - [[wikilink]] 只能連到 repo 內的筆記（practice_notes/、law_notes/）；連到 repo 外多半是案件筆記
例外：公開文件（例如已公告的解釋函文號）要引用時，把該字串原樣列在 frontmatter 的 allow_terms 清單，
     覆核時一眼可見。allow_terms 只豁免禁字，不豁免 wikilink 與 frontmatter 規則。

regex 只擋得住明顯格式；描述性可辨識資訊（例如「某縣唯一的太空中心案」）擋不住，仍靠撰寫者自律。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

NOTES_DIR = "practice_notes"
LINK_ROOTS = ("practice_notes", "law_notes")
REQUIRED = ("type", "source_office", "deidentified", "updated")
OWN_COMPANY = ("衍古開發顧問有限公司",)

BANNED: list[tuple[str, re.Pattern, str]] = [
    ("內網 IP", re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
     "改寫成 <NAS> 之類的占位字"),
    ("NAS 共享名", re.compile(r"Public-[A-Z]{2}\b"), "改寫成 <共享名>"),
    ("實體路徑", re.compile(r"(?<![A-Za-z<])[A-Za-z]:[\\/](?:Users|使用者)[\\/]|(?<![A-Za-z<])[D-Zd-z]:[\\/]"
                         r"|\\\\(?!<)[A-Za-z0-9][\w.-]*\\"),
     "改寫成 <磁碟>:\\…、\\\\<NAS>\\<共享名>\\… 之類的占位寫法"),
    ("公司行號", re.compile(r"[一-鿿A-Za-z0-9]{2,}(?:股份有限公司|有限公司)"),
     "改寫成「某開發商」「某光電業者」"),
    ("地段地號", re.compile(r"[一-鿿]{1,8}段\s*\d+(?:-\d+)?\s*(?:地號|等)?|\d+(?:-\d+)?\s*地號"),
     "拿掉具體地段地號，改寫成「某段某地號」"),
    ("公文文號", re.compile(r"字第\s*[0-9０-９]{5,}\s*號"),
     "拿掉；若是已公告的解釋函，把文號原樣列進 frontmatter allow_terms"),
    ("案件代碼", re.compile(r"(?<![A-Za-z0-9])[CMS]\d{3}(?![0-9])"), "拿掉案件代碼，改寫成案件類型描述"),
]

FRONT = re.compile(r"\A(?:﻿)?---\r?\n(.*?)\r?\n---\r?\n?", re.S)
LINK = re.compile(r"!?\[\[([^\]|#^]+)")


class NoteIssue:
    def __init__(self, file: str, item: str, message: str, fix: str):
        self.file, self.item, self.message, self.fix = file, item, message, fix

    def render(self) -> str:
        return f"錯誤 [{self.item}] {self.file}\n    {self.message}\n    修法：{self.fix}"


def _note_names(repo_root: Path) -> set[str]:
    names = set()
    for sub in LINK_ROOTS:
        base = repo_root / sub
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file():
                    names.add(path.stem.casefold() if path.suffix.lower() == ".md" else path.name.casefold())
    return names


def _is_date(value) -> bool:
    if isinstance(value, (dt.date, dt.datetime)):
        return True
    try:
        dt.date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def check_file(path: Path, rel: str, office_codes: set[str], known: set[str]) -> list[NoteIssue]:
    issues: list[NoteIssue] = []
    text = path.read_text(encoding="utf-8-sig")
    m = FRONT.match(text)
    meta: dict = {}
    if not m:
        issues.append(NoteIssue(rel, "frontmatter", "缺 frontmatter（--- 包起來的 YAML 檔頭）",
                                "補上 type、source_office、deidentified: true、updated"))
    else:
        try:
            loaded = yaml.safe_load(m.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as exc:
            issues.append(NoteIssue(rel, "frontmatter", f"YAML 解析失敗：{exc}", "修正檔頭格式"))
    if m:
        missing = [key for key in REQUIRED if key not in meta]
        if missing:
            issues.append(NoteIssue(rel, "frontmatter", f"缺欄位：{', '.join(missing)}", "補齊必填欄位"))
        if "source_office" in meta and meta["source_office"] not in office_codes:
            issues.append(NoteIssue(rel, "frontmatter", f"source_office {meta['source_office']!r} 不在 offices.yaml",
                                    f"填 {'、'.join(sorted(office_codes))} 之一"))
        if "deidentified" in meta and meta["deidentified"] is not True:
            issues.append(NoteIssue(rel, "frontmatter", "deidentified 必須是 true",
                                    "確認已去識別化後填 true；還沒處理完的筆記不要放進 practice_notes/"))
        if "updated" in meta and not _is_date(meta["updated"]):
            issues.append(NoteIssue(rel, "frontmatter", f"updated 不是日期：{meta['updated']!r}", "填 YYYY-MM-DD"))
        sens = str(meta.get("sensitivity", "")).strip().lower()
        if sens in {"restricted", "confidential", "限制級", "機密"}:
            issues.append(NoteIssue(rel, "敏感度", f"標了 sensitivity: {sens}", "限制級內容不得進 repo，移出"))
    allow = meta.get("allow_terms") or []
    if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
        issues.append(NoteIssue(rel, "frontmatter", "allow_terms 必須是字串清單", "改成 YAML 清單"))
        allow = []
    scrubbed = text
    for term in sorted(set(allow) | set(OWN_COMPANY), key=len, reverse=True):
        if term:
            scrubbed = scrubbed.replace(term, "")
    for label, pattern, fix in BANNED:
        hits = sorted({h.group(0).strip() for h in pattern.finditer(scrubbed)})
        if hits:
            shown = "、".join(hits[:5]) + (f" …另 {len(hits) - 5} 處" if len(hits) > 5 else "")
            issues.append(NoteIssue(rel, f"禁字：{label}", f"出現 {shown}", fix))
    bad_links = sorted({l.strip() for l in LINK.findall(text) if l.strip().casefold() not in known})
    if bad_links:
        shown = "、".join(bad_links[:5]) + (f" …另 {len(bad_links) - 5} 個" if len(bad_links) > 5 else "")
        issues.append(NoteIssue(rel, "repo 外連結", f"[[連結]] 指向 repo 外的筆記：{shown}",
                                "改成純文字描述（不含案名）或拿掉；只能連 practice_notes/、law_notes/ 內的筆記"))
    return issues


def check_tree(repo_root: Path, office_codes: set[str]) -> tuple[list[NoteIssue], int]:
    base = repo_root / NOTES_DIR
    if not base.is_dir():
        return [], 0
    known = _note_names(repo_root)
    issues: list[NoteIssue] = []
    count = 0
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        count += 1
        issues += check_file(path, rel, office_codes, known)
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() != ".md"
                       and p.name != ".gitkeep"):
        issues.append(NoteIssue(path.relative_to(repo_root).as_posix(), "檔案類型",
                                "practice_notes/ 只收 markdown", "附件不進 repo；圖片等改用文字描述"))
    return issues, count


def _office_codes(repo_root: Path) -> set[str]:
    data = yaml.safe_load((repo_root / "offices.yaml").read_text(encoding="utf-8")) or {}
    body = data.get("offices", data)
    if isinstance(body, list):
        return {str(item.get("code")) for item in body if isinstance(item, dict) and item.get("code")}
    return {str(key) for key in body}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    a = ap.parse_args(argv)
    root = a.repo_root.resolve()
    issues, count = check_tree(root, _office_codes(root))
    for issue in issues:
        print(issue.render())
    if issues:
        print(f"\n實務筆記檢查未通過：{len(issues)} 項（共 {count} 篇）。")
        return 1
    print(f"實務筆記檢查通過（{count} 篇）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
