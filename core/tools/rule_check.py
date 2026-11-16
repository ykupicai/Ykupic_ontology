"""規則庫檢查（push 前／CI）。規格見 rules/_fields.yaml。

用法：
  python -X utf8 core/tools/rule_check.py              檢查工作區（靜態檢查＋若在 git repo 內，比對 origin/main 或前一個 commit）
  python -X utf8 core/tools/rule_check.py --pre-push   由 git pre-push hook 呼叫：讀 stdin 的 push 範圍，檢查「要推上去的 commit」
  python -X utf8 core/tools/rule_check.py --ci         CI 用：比對 --base（或 origin/main、前一個 commit），略過本機辦公室檢查

靜態檢查（不需要 git）：YAML 格式、是否為標準輸出格式（與 rulebook_export 整理結果相同）、欄位缺漏／多餘／順序、值型別、enum、規則 ID 格式與唯一、檔名＝ID、
放置位置（national／local/<縣市>／pending/<辦公室>）、pending 前綴、狀態與 superseded_by、新增／覆核辦公室、
轉正規則 reviewed_by ≠ added_by、source_url 必填與官方網域、匯入規則被刪除或內容被改、exports/ 是否與 rules/ 同步。
差異檢查（需要 git 與比對基準）：已轉正規則（national／local）被刪檔；本機另擋修改其他辦公室的 pending 資料夾
（唯一例外：轉正時把對方 pending 規則改為 deprecated＋superseded_by）。
結束碼：0 通過；1 有錯誤；2 無法執行檢查。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))

import yaml  # noqa: E402

from ykkb import rules as rl  # noqa: E402

ZERO_SHA = re.compile(r"^0+$")


@dataclass
class Issue:
    file: str
    item: str
    message: str
    fix: str

    def render(self) -> str:
        return f"錯誤 [{self.item}] {self.file}\n    {self.message}\n    修法：{self.fix}"


# ---------------------------------------------------------------- 共用

def load_office_codes(repo_root: Path) -> set[str]:
    path = repo_root / "offices.yaml"
    try:
        from ykkb import config
        return set(config.load_office_codes(path))
    except ImportError:
        pass
    data = yaml.safe_load(rl.read_text(path)) or {}
    body = data.get("offices", data)
    if isinstance(body, list):
        return {str(i.get("code")) for i in body if isinstance(i, dict) and i.get("code")}
    return {str(k) for k in body}


def _is_date(value) -> bool:
    if isinstance(value, dt.date):
        return True
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            dt.date.fromisoformat(value)
            return True
        except ValueError:
            return False
    return False


def _empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------- 靜態檢查

def static_checks(repo_root: Path, fields: dict, office_codes: set[str], check_exports: bool = True):
    """回傳 (issues, rule_files)。"""
    issues: list[Issue] = []
    columns = fields["columns"]
    ext = fields["extension_fields"]
    allowed_keys = set(columns) | set(ext)
    id_re = re.compile(fields["id"]["pattern"])
    pending_re = re.compile(fields["id"]["pending_pattern"])
    counties = fields["county_codes"]
    enums = fields.get("enums", {})
    patterns = {k: re.compile(v) for k, v in (fields.get("patterns") or {}).items()}
    legacy = rl.load_legacy(repo_root)
    legacy_digest = {r["rule_id"]: r["content_sha256"] for r in legacy}
    rule_files = rl.load_all_rules(repo_root)

    def add(rf_rel, item, msg, fix):
        issues.append(Issue(rf_rel, item, msg, fix))

    # 放錯層的檔（rules/ 底下但不在三個分類內的 yaml 不會被讀到；這裡補抓 rules/ 第一層以外的雜檔）
    rules_dir = repo_root / rl.RULES_DIR
    if rules_dir.is_dir():
        for p in sorted(rules_dir.iterdir()):
            if p.is_dir() and not p.name.startswith("_") and p.name not in rl.CATEGORIES:
                add(f"rules/{p.name}/", "放置位置", "rules/ 底下只能有 national、local、pending 與 _ 開頭的規格資料夾",
                    "把規則檔搬到 rules/national/、rules/local/<縣市代碼>/ 或 rules/pending/<辦公室代碼>/")

    ids: dict[str, list[str]] = {}
    for rf in rule_files:
        rel = rf.rel
        if rf.category == "unknown":
            add(rel, "放置位置", "規則檔放錯層：national 直接放檔；local、pending 要再多一層縣市或辦公室資料夾",
                "搬到 rules/national/<ID>.yaml、rules/local/<縣市代碼>/<ID>.yaml 或 rules/pending/<辦公室代碼>/<ID>.yaml")
            continue
        if rf.path.suffix != ".yaml":
            add(rel, "檔名", "副檔名必須是 .yaml", f"改名為 {rf.path.stem}.yaml")
        if rf.error:
            add(rel, "格式錯", rf.error, "用文字編輯器修正 YAML 語法（冒號後要空一格；多行文字用 | 開頭並縮排）")
            continue
        d = rf.data
        rid = d.get("rule_id")
        if not rl.is_standard_format(rf):
            add(rel, "格式不標準", "檔案不是標準輸出格式（引號、換行 CRLF、縮排或 BOM 與 rulebook_export 整理後不同；CI 的測試會因此失敗）",
                "先跑 python -X utf8 core/tools/rulebook_export.py（自動整理格式、值不變），再 git add rules exports")
        # 欄位
        missing = [c for c in columns if c not in d]
        missing += [k for k, spec in ext.items() if spec.get("required") and k not in d]
        if missing:
            add(rel, "欄位缺", f"缺少欄位：{', '.join(missing)}", "照 rules/_template.yaml 補上（沒有值就寫 null）")
        unknown = [str(k) for k in d if k not in allowed_keys]
        if unknown:
            add(rel, "欄位多餘", f"無法辨識的欄位：{', '.join(unknown)}",
                "欄名須與 rules/_fields.yaml 的 columns／extension_fields 完全一致（含全形符號），多的刪掉")
        order = [k for k in d if k in columns]
        if not missing and order != columns:
            add(rel, "欄位順序", "21 個原欄位的順序與 rules/_fields.yaml 的 columns 不同",
                "依 _fields.yaml 的 columns 順序排列（可直接照 rules/_template.yaml 的順序）")
        for c in columns:
            v = d.get(c)
            if v is not None and not isinstance(v, str):
                add(rel, "格式錯", f"欄位「{c}」的值不是文字（讀到 {type(v).__name__}：{v!r}）",
                    f"加引號寫成字串，例：{c}: '{v}'")
        for c in fields.get("required_nonempty", []):
            if c in d and _empty(d.get(c)):
                add(rel, "欄位缺", f"欄位「{c}」不可空白", "填入內容；確實無內容的欄位請寫「—」")
        for c, allowed in enums.items():
            v = d.get(c)
            if isinstance(v, str) and v not in allowed:
                add(rel, "enum 非法", f"欄位「{c}」的值「{v}」不在允許清單",
                    f"改成以下之一：{'、'.join(allowed)}（真的需要新選項，請總部先改 rules/_fields.yaml）")
        for c, pat in patterns.items():
            v = d.get(c)
            if isinstance(v, str) and not pat.match(v):
                add(rel, "格式錯", f"欄位「{c}」的值「{v}」不符格式 {pat.pattern}", "照 rules/_fields.yaml 的 patterns 改寫")
        # ID
        if not isinstance(rid, str) or not rid:
            add(rel, "ID 格式", "rule_id 空白或不是文字", "填入規則 ID（與檔名相同）")
            continue
        ids.setdefault(rid, []).append(rel)
        digit_ok = "-" in rid and any(ch.isdigit() for ch in rid.split("-", 1)[1])
        if not id_re.match(rid) or (fields["id"].get("digit_after_first_hyphen") and not digit_ok):
            add(rel, "ID 格式", f"rule_id「{rid}」格式不合：須為大寫英數以連字號分段，且第一個連字號後含數字（例 GEN-064、XHC-1）",
                "改成合格 ID，並同步改檔名")
        if rf.path.stem != rid:
            add(rel, "檔名≠ID", f"檔名「{rf.path.stem}」與 rule_id「{rid}」不同", f"把檔名改為 {rid}.yaml（或改 rule_id）")
        m = pending_re.match(rid)
        if rf.category == "pending":
            if rf.group not in office_codes:
                add(rel, "pending 位置", f"pending 底下的「{rf.group}」不是辦公室代碼（offices.yaml：{', '.join(sorted(office_codes))}）",
                    "放到 rules/pending/<自己的辦公室代碼>/")
            if not m or m.group("office") != rf.group:
                add(rel, "pending 前綴", f"rules/pending/{rf.group}/ 的規則 ID 必須是 X{rf.group}-<流水號>（讀到「{rid}」）",
                    f"改成 X{rf.group}-<下一個流水號>，或把檔搬到正確辦公室的 pending 資料夾")
            if d.get("added_by") != rf.group:
                add(rel, "pending 位置", f"pending/{rf.group} 的規則 added_by 應為 {rf.group}（讀到 {d.get('added_by')!r}）",
                    f"added_by 改為 {rf.group}")
            if not _empty(d.get("reviewed_by")) or not _empty(d.get("reviewed_at")):
                add(rel, "轉正", "pending 規則不應填 reviewed_by／reviewed_at（轉正是另建正式 ID 規則檔）",
                    "清空這兩欄；轉正步驟見 README 9.3")
        else:
            if m:
                add(rel, "ID 格式", f"已轉正規則不可使用 pending 形式 ID「{rid}」",
                    "轉正時改配正式 ID（中央法規用法規縮寫前綴、地方規定用縣市代碼前綴），原 pending 檔保留並標 deprecated")
            if rf.category == "local":
                if rf.group not in counties:
                    add(rel, "放置位置", f"rules/local/ 底下的「{rf.group}」不是縣市代碼",
                        f"改用 rules/_fields.yaml 的 county_codes（{', '.join(counties)}）；新縣市代碼請總部新增")
                else:
                    ok = rid.startswith("LOCAL-") if rf.group == "ANY" else (
                        rid.startswith(f"{rf.group}-") or rid.startswith(f"LOCAL-{rf.group}-"))
                    if not ok:
                        want = "LOCAL-" if rf.group == "ANY" else f"{rf.group}- 或 LOCAL-{rf.group}-"
                        add(rel, "ID 格式", f"local/{rf.group}/ 的規則 ID 應以 {want} 開頭（讀到「{rid}」）",
                            "改 ID，或把檔搬到正確的縣市資料夾")
        # 擴充欄
        status = d.get("status")
        if status is not None and status not in ext["status"]["enum"]:
            add(rel, "enum 非法", f"status「{status}」不合法", "改為 active 或 deprecated")
        sup = d.get("superseded_by")
        if status == "deprecated" and _empty(sup):
            add(rel, "廢止", "status 為 deprecated 但沒填 superseded_by", "superseded_by 填取代它的 rule_id，或寫明廢止原因")
        if sup is not None and not isinstance(sup, str):
            add(rel, "格式錯", "superseded_by 必須是文字", "寫成 rule_id 或文字原因")
        for key in ("added_by", "reviewed_by"):
            v = d.get(key)
            if v is not None and v not in office_codes:
                add(rel, "enum 非法", f"{key}「{v}」不是辦公室代碼", f"改為 {', '.join(sorted(office_codes))} 之一")
        reviewed_by = d.get("reviewed_by")
        if not _empty(reviewed_by) and reviewed_by == d.get("added_by"):
            add(rel, "轉正", f"reviewed_by 與 added_by 相同（{reviewed_by}）：自己新增的規則不能自己轉正",
                "請另一個辦公室覆核，reviewed_by 填覆核辦公室代碼")
        if not _empty(reviewed_by) and not _is_date(d.get("reviewed_at")):
            add(rel, "轉正", "有 reviewed_by 但 reviewed_at 空白或不是 YYYY-MM-DD", "reviewed_at 填覆核日期，例 '2026-11-20'")
        lf = d.get("legacy_import", False)
        if lf not in (True, False, None):
            add(rel, "格式錯", "legacy_import 只能是 true／false", "新規則刪掉這行或寫 false")
        is_legacy = lf is True
        if is_legacy and rid not in legacy_digest:
            add(rel, "匯入標記", f"legacy_import: true 只限原匯入規則，「{rid}」不在 rules/_meta/legacy_import.yaml",
                "新規則刪掉 legacy_import 這行或寫 false（複製舊規則當範本時常見）")
            is_legacy = False
        if rf.category in ("national", "local") and not is_legacy and _empty(reviewed_by):
            add(rel, "轉正", "已轉正（national／local）的新規則必須有 reviewed_by 與 reviewed_at",
                "新規則先放 rules/pending/<自己辦公室>/，由另一辦公室覆核轉正")
        # source_url
        url = d.get("source_url")
        changed_legacy = is_legacy and rl.content_digest(d, columns) != legacy_digest.get(rid)
        if _empty(url):
            if not is_legacy:
                add(rel, "source_url", "新增規則缺 source_url", "填官方法規資料庫網址（白名單見 rules/_fields.yaml 的 source_url）")
            elif changed_legacy:
                add(rel, "source_url", "匯入規則的 21 欄內容已修改，修改後必須補 source_url",
                    "填這次核對所依據的官方法規資料庫網址")
        elif not isinstance(url, str):
            add(rel, "source_url", "source_url 必須是文字網址", "寫成 https://... 的完整網址")
        else:
            ok, why = rl.url_host_allowed(url, fields)
            if not ok:
                add(rel, "source_url", f"source_url 不合格：{why}",
                    "填完整的官方法規資料庫網址（law.moj.gov.tw、glrs.moi.gov.tw 等，或縣市法規系統，含 pcode／id 參數值）；第三方彙編站不接受")
        # 中央法規新規則的 ID 前綴須在對照表內
        prefixes = fields.get("national_prefixes") or {}
        if rf.category == "national" and not is_legacy and prefixes and not m:
            prefix = rid.split("-", 1)[0]
            if prefix not in prefixes:
                add(rel, "ID 前綴", f"中央法規規則前綴「{prefix}」不在 rules/_fields.yaml 的 national_prefixes 對照表",
                    "改用對照表內對應該法規的前綴；確實是新法規時請總部（TN）配新前綴並加進對照表")

    # 全域
    for rid, rels in sorted(ids.items()):
        if len(rels) > 1:
            add(", ".join(rels), "ID 重複", f"rule_id「{rid}」出現 {len(rels)} 次（全 repo 須唯一，含已 deprecated 的 pending 規則）",
                "其中一條改用新的 ID（pending 用下一個流水號）")
    all_ids = set(ids)
    for rf in rule_files:
        sup = (rf.data or {}).get("superseded_by")
        if isinstance(sup, str) and re.fullmatch(fields["id"]["pattern"], sup.strip()):
            if sup.strip() not in all_ids:
                add(rf.rel, "廢止", f"superseded_by 指向的「{sup}」不存在", "改成存在的 rule_id，或寫明廢止原因")
            elif sup.strip() == rf.rule_id:
                add(rf.rel, "廢止", "superseded_by 不可指向自己", "改成取代它的 rule_id")
    for rid in legacy_digest:
        if rid not in all_ids:
            add(f"rules/**/{rid}.yaml", "刪除轉正規則", f"匯入規則「{rid}」的檔案不見了（已轉正規則不可刪除）",
                f"用 git restore 還原；要廢止請保留檔案，改 status: deprecated 並填 superseded_by")
    if check_exports:
        import rulebook_export
        try:
            problems = rulebook_export.check(repo_root, include_format=False)
        except rl.RuleFileError as exc:
            problems = [f"無法產生匯出（{exc}）"]
        for p in problems:
            add("exports/", "exports 未同步", p, "先跑 python -X utf8 core/tools/rulebook_export.py，再 git add rules exports")
    return issues, rule_files


# ---------------------------------------------------------------- git

def git(repo_root: Path, *args, binary=False):
    """執行 git；失敗回 None。"""
    try:
        res = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, check=False)
    except OSError:
        return None
    if res.returncode != 0:
        return None
    return res.stdout if binary else res.stdout.decode("utf-8", "replace")


def rev_ok(repo_root: Path, rev: str | None) -> str | None:
    if not rev or ZERO_SHA.match(rev):
        return None
    out = git(repo_root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return out.strip() if out else None


def changed_rule_paths(repo_root: Path, base: str, head: str) -> list[tuple[str, str]]:
    out = git(repo_root, "-c", "core.quotepath=off", "diff", "--name-status", "--no-renames", base, head, "--", "rules/")
    result = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            result.append((parts[0][:1], parts[-1]))
    return result


def show_rule(repo_root: Path, rev: str, rel: str):
    raw = git(repo_root, "show", f"{rev}:{rel}", binary=True)
    if raw is None:
        return None
    try:
        return rl.load_rule_text(raw.decode("utf-8-sig"), rel)
    except (rl.RuleFileError, UnicodeDecodeError):
        return None


def export_tree(repo_root: Path, rev: str, dest: Path) -> bool:
    """把要 push 的 commit 內容（rules、exports、offices.yaml）解到 dest，供靜態檢查。"""
    # 直接取 blob 原始位元組（git archive 會依 autocrlf 轉換換行，CSV 比對會失準）
    listing = git(repo_root, "-c", "core.quotepath=off", "ls-tree", "-r", "-z", rev, "--",
                  "rules", "exports", "offices.yaml", binary=True)
    if listing is None:
        return False
    entries = []
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, _, name = item.partition(b"\t")
        mode, kind, sha = meta.split()
        if kind == b"blob":
            entries.append((sha.decode(), name.decode("utf-8")))
    if not entries:
        return True
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=repo_root, capture_output=True, check=False,
                          input=b"".join(sha.encode() + b"\n" for sha, _ in entries))
    if proc.returncode != 0:
        return False
    buf = io.BytesIO(proc.stdout)
    root = dest.resolve()
    for sha, name in entries:
        header = buf.readline().split()
        size = int(header[2])
        data = buf.read(size)
        buf.read(1)  # 結尾換行
        target = (dest / name).resolve()
        if root not in target.parents:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return True


def diff_checks(repo_root: Path, base: str, head: str, head_rules: list, local_office: str | None) -> list[Issue]:
    issues = []
    by_id = {rf.rule_id: rf for rf in head_rules if rf.data}
    for status, rel in changed_rule_paths(repo_root, base, head):
        cat, group = rl.classify_rel(rel)
        stem = PurePosixPath(rel).stem
        if status == "D" and cat in ("national", "local") and stem not in by_id:
            issues.append(Issue(rel, "刪除轉正規則", f"已轉正規則「{stem}」在這次 push 範圍內被刪除",
                                "用 git restore／git revert 還原；要廢止請改 status: deprecated 並填 superseded_by"))
        if local_office and cat == "pending" and group != local_office:
            if status == "M" and _same_values(repo_root, base, head, rel):
                continue  # 純格式差異（例如被 rulebook_export 自動整理），值完全相同就放行
            if status == "M" and _is_promotion_mark(repo_root, base, head, rel, group, local_office, by_id):
                continue
            verb = {"D": "刪除", "A": "新增", "M": "修改"}.get(status, "變動")
            issues.append(Issue(rel, "他辦公室 pending",
                                f"{verb}了 {group} 辦公室的 pending 規則（本機辦公室為 {local_office}）。"
                                "唯一例外是轉正：只把 status 改為 deprecated 並新增 superseded_by，且指向的正式規則"
                                f" reviewed_by＝{local_office}、added_by＝{group}",
                                f"還原這個檔（git restore --source={base[:12]} -- \"{rel}\" 後重新 commit），或請 {group} 辦公室自己改"))
    return issues


def _same_values(repo_root, base, head, rel) -> bool:
    old = show_rule(repo_root, base, rel)
    new = show_rule(repo_root, head, rel)
    return old is not None and new is not None and old == new


def branch_warnings(repo_root: Path) -> list[str]:
    """差異檢查以 origin/main 為基準；分支不是 main 或沒有 origin/main 時明確警告（不再靜默退回靜態檢查）。"""
    out = []
    branch = (git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if branch and branch not in ("main", "HEAD"):
        out.append(f"目前分支是「{branch}」不是 main；差異檢查仍以 origin/main 為基準，本 repo 的規則只應在 main 上改動")
    if not rev_ok(repo_root, "origin/main"):
        out.append("找不到 origin/main（尚未設定遠端 origin、遠端主分支不叫 main，或還沒 git fetch）："
                   "「刪除轉正規則」「修改他辦公室 pending」等差異檢查可能只能做靜態部分；請先 git fetch origin")
    return out


def _is_promotion_mark(repo_root, base, head, rel, group, local_office, by_id) -> bool:
    old = show_rule(repo_root, base, rel)
    new = show_rule(repo_root, head, rel)
    if old is None or new is None:
        return False
    if old.get("status", "active") != "active" or new.get("status") != "deprecated":
        return False
    if not _empty(old.get("superseded_by")):
        return False
    target_id = new.get("superseded_by")
    if _empty(target_id):
        return False
    rest_old = {k: v for k, v in old.items() if k not in ("status", "superseded_by")}
    rest_new = {k: v for k, v in new.items() if k not in ("status", "superseded_by")}
    if rest_old != rest_new:
        return False
    target = by_id.get(str(target_id).strip())
    if target is None or target.category not in ("national", "local"):
        return False
    return target.data.get("reviewed_by") == local_office and target.data.get("added_by") == group


def ci_base(repo_root: Path, explicit: str | None) -> tuple[str | None, str]:
    b = rev_ok(repo_root, explicit)
    if b:
        return b, f"--base {explicit[:12]}"
    head = rev_ok(repo_root, "HEAD")
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        mb = git(repo_root, "merge-base", "HEAD", f"origin/{base_ref}")
        if mb:
            return mb.strip(), f"origin/{base_ref} 的分岔點"
    if rev_ok(repo_root, "origin/main"):
        mb = (git(repo_root, "merge-base", "HEAD", "origin/main") or "").strip()
        if mb and mb != head:
            return mb, "origin/main 的分岔點"
    prev = rev_ok(repo_root, "HEAD~1")
    if prev:
        return prev, "前一個 commit（HEAD~1）"
    return None, ""


def local_office_code(config_path, office_codes: set[str]) -> tuple[str | None, str | None]:
    """回 (辦公室代碼, 問題說明)。先用 ykkb.config.load_office_config；vault 連不上等與規則無關的問題不擋 push。"""
    from ykkb import config
    try:
        cfg = config.load_office_config(config_path, require_vault_exists=False)
        return cfg["office_code"], None
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)
    try:
        path = config.resolve_config_path(config_path)
        data = yaml.safe_load(rl.read_text(path)) or {}
        code = data.get("office_code")
        if code in office_codes:
            return code, f"office.yaml 其他設定有問題（不影響規則檢查）：{reason}"
    except Exception:  # noqa: BLE001
        pass
    return None, reason


# ---------------------------------------------------------------- 主程式

def run(repo_root: Path, mode: str, base_arg: str | None, config_path, stdin_text: str | None) -> int:
    notes: list[str] = []
    issues: list[Issue] = []
    office_codes = load_office_codes(repo_root)
    fields = rl.load_fields(repo_root)
    in_git = git(repo_root, "rev-parse", "--is-inside-work-tree") is not None

    local_office = None
    if mode != "ci":
        local_office, problem = local_office_code(config_path, office_codes)
        if problem:
            if local_office is None and mode == "pre-push":
                issues.append(Issue("office.yaml", "本機設定", f"無法判斷本機辦公室代碼：{problem}",
                                    "複製 office.example.yaml 為 office.yaml 並填 office_code"))
            else:
                notes.append(problem if local_office else f"未讀到 office.yaml（{problem}），略過「修改他辦公室 pending」檢查")
    else:
        notes.append("CI 模式：略過「修改他辦公室 pending」檢查")

    targets: list[tuple[str | None, str]] = []   # (base, head)
    if mode == "pre-push":
        for line in (stdin_text or "").splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            _lref, lsha, _rref, rsha = parts
            if ZERO_SHA.match(lsha):
                continue  # 刪除遠端分支，不檢查
            base = rev_ok(repo_root, rsha)
            if base is None:
                for cand in ("origin/main", "origin/HEAD"):
                    if rev_ok(repo_root, cand):
                        base = (git(repo_root, "merge-base", lsha, cand) or "").strip() or None
                        if base:
                            break
            if base is None:
                notes.append(f"{lsha[:12]}：找不到遠端比對基準（第一次 push？），只做靜態檢查")
            targets.append((base, lsha))
        if not targets:
            notes.append("stdin 沒有要 push 的 commit，改檢查工作區")
    elif in_git and mode == "ci":
        base, why = ci_base(repo_root, base_arg)
        head = rev_ok(repo_root, "HEAD")
        if base and head:
            notes.append(f"差異比對基準：{why}")
            targets.append((base, head))
        else:
            notes.append("沒有可比對的 commit，只做靜態檢查")
    elif in_git:
        # 本機手動執行：只看「尚未 push 的 commit」（HEAD 與 origin/main 的分岔點之後），
        # 不拿 HEAD~1 比，以免把剛 pull 下來的他辦公室 commit 誤判成自己改的。
        head = rev_ok(repo_root, "HEAD")
        base = None
        if head and rev_ok(repo_root, "origin/main"):
            base = (git(repo_root, "merge-base", "HEAD", "origin/main") or "").strip() or None
        if base and base != head:
            notes.append("差異比對基準：origin/main 的分岔點（尚未 push 的 commit）")
            targets.append((base, head))
        else:
            notes.append("沒有尚未 push 的 commit（或沒有 origin/main），差異檢查留給 push 時的 hook")
    else:
        notes.append("不在 git repo 內，只做靜態檢查（無法檢查刪除與他辦公室 pending）")

    if mode == "pre-push" and targets:
        for base, head in targets:
            with tempfile.TemporaryDirectory() as tmp:
                tree = Path(tmp)
                if not export_tree(repo_root, head, tree):
                    issues.append(Issue(head[:12], "git", "無法取出要 push 的 commit 內容", "確認 git 可正常執行後重試"))
                    continue
                st, head_rules = static_checks(tree, rl.load_fields(tree), load_office_codes(tree))
                issues += st
                if base:
                    issues += diff_checks(repo_root, base, head, head_rules, local_office)
        if git(repo_root, "status", "--porcelain", "--", "rules", "exports"):
            notes.append("工作區 rules／exports 有未提交的變更；本次只檢查已 commit、要 push 的內容")
    else:
        st, head_rules = static_checks(repo_root, fields, office_codes)
        issues += st
        for base, head in targets:
            issues += diff_checks(repo_root, base, head, head_rules, local_office)
            if git(repo_root, "status", "--porcelain", "--", "rules"):
                notes.append("工作區 rules 有未提交的變更：靜態檢查看工作區，差異檢查只看已 commit 的內容")

    warnings: list[str] = []
    if in_git and mode != "ci":
        warnings += branch_warnings(repo_root)
    if mode == "pre-push":
        for line in (stdin_text or "").splitlines():
            parts = line.split()
            if len(parts) == 4 and not ZERO_SHA.match(parts[1]) and parts[2] != "refs/heads/main":
                warnings.append(f"這次推到遠端「{parts[2]}」不是 refs/heads/main；GitHub Actions 的更新通知只在 main 觸發")
    for w in warnings:
        print(f"警告：{w}")
    for n in notes:
        print(f"說明：{n}")
    if issues:
        for i in issues:
            print(i.render())
        print(f"\n規則檢查未通過：{len(issues)} 項錯誤。修好後重新 commit 再 push（不要用 --no-verify 跳過）。")
        return 1
    n_rules = sum(1 for _ in rl.rule_paths(repo_root))
    print(f"規則檢查通過（{n_rules} 個規則檔）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pre-push", action="store_true", help="由 git pre-push hook 呼叫（讀 stdin）")
    g.add_argument("--ci", action="store_true", help="CI 模式")
    ap.add_argument("--base", help="CI 模式的比對基準 commit（例：push 前的 SHA）")
    ap.add_argument("--repo-root", type=Path, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--office-config", type=Path, default=None, help="office.yaml 路徑（預設 repo 根）")
    ap.add_argument("hook_args", nargs="*", help=argparse.SUPPRESS)  # pre-push 的 remote 名稱與網址
    a = ap.parse_args(argv)
    root = (a.repo_root or rl.REPO_ROOT).resolve()
    mode = "pre-push" if a.pre_push else ("ci" if a.ci else "local")
    stdin_text = sys.stdin.read() if a.pre_push else None
    try:
        return run(root, mode, a.base, a.office_config, stdin_text)
    except (rl.RuleFileError, OSError, KeyError) as exc:
        print(f"無法執行規則檢查：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
