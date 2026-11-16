"""法令檢核規則檔（rules/）的讀寫共用函式。

規則檔格式、分類、排序鍵、enum 與官方網域白名單的唯一定義在 rules/_fields.yaml；
本模組只負責讀取與套用，不另寫一份規格。

主要入口：
  load_fields(repo_root)            讀 rules/_fields.yaml
  load_all_rules(repo_root)         讀 national／local／pending 全部規則檔（不驗證，驗證在 rule_check）
  exported_rules(repo_root)         依排序鍵排好、要進匯出的規則（national＋local；pending 不進）
  dump_rule(data) / load_rule_text  規則檔 YAML 的穩定寫出與讀入
  render_csv / build_workbook       產生匯出內容（rulebook_export 與 rule_check 共用）
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = "rules"
FIELDS_FILE = "rules/_fields.yaml"
META_DIR = "rules/_meta"
WORKBOOK_META = "rules/_meta/workbook.yaml"
LEGACY_FILE = "rules/_meta/legacy_import.yaml"
EXPORT_DIR = "exports"
CSV_NAME = "法令檢核規則庫.csv"
XLSX_NAME = "法令檢核規則庫.xlsx"
RULE_SHEET = "20_規則庫"
CATEGORIES = ("national", "local", "pending")


class RuleFileError(ValueError):
    """規則檔或規格檔無法讀取（YAML 語法錯、不是對照表等）。"""


# ---------------------------------------------------------------- YAML 讀寫

class _RuleDumper(yaml.SafeDumper):
    """多行字串用 block scalar（|），其餘交給 PyYAML 決定是否加引號。"""


def _str_representer(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_RuleDumper.add_representer(str, _str_representer)


def dump_yaml(data) -> str:
    """穩定輸出：保留鍵順序、不折行、UTF-8 原字、LF。"""
    return yaml.dump(data, Dumper=_RuleDumper, allow_unicode=True, sort_keys=False,
                     width=1_000_000, default_flow_style=False, indent=2)


def load_yaml_text(text: str, label: str = ""):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleFileError(f"{label} YAML 語法錯誤：{exc}") from exc


def read_text(path: Path) -> str:
    # utf-8-sig：容忍使用者用記事本存出 BOM；換行統一成 LF
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def dump_rule(data: dict) -> str:
    return dump_yaml(data)


def load_rule_text(text: str, label: str = "") -> dict:
    data = load_yaml_text(text, label)
    if not isinstance(data, dict):
        raise RuleFileError(f"{label} 內容不是「欄名: 值」的對照表")
    return data


# ---------------------------------------------------------------- 規格

def load_fields(repo_root=REPO_ROOT) -> dict:
    path = Path(repo_root) / FIELDS_FILE
    data = load_yaml_text(read_text(path), str(path))
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
        raise RuleFileError(f"{path} 缺 columns 清單")
    return data


def load_legacy(repo_root=REPO_ROOT) -> list[dict]:
    """原 xlsx 匯入的規則清單（原列順序＋匯入當時 21 欄內容指紋）。"""
    path = Path(repo_root) / LEGACY_FILE
    if not path.is_file():
        return []
    data = load_yaml_text(read_text(path), str(path)) or {}
    return list(data.get("rules") or [])


def content_digest(data: dict, columns: list[str]) -> str:
    """21 欄內容指紋（只看原欄，不含擴充欄）；用來判斷 legacy 規則有沒有被改過內容。"""
    import hashlib
    import json
    payload = json.dumps([data.get(c) for c in columns], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 規則檔

@dataclass
class RuleFile:
    path: Path                 # 實際路徑
    rel: str                   # 相對 repo 根的 posix 路徑
    category: str              # national／local／pending／unknown
    group: str | None          # local 的縣市代碼、pending 的辦公室代碼
    data: dict | None = None   # 解析成功的內容
    error: str | None = None   # 解析失敗原因
    extra: dict = field(default_factory=dict)

    @property
    def rule_id(self):
        return (self.data or {}).get("rule_id")


def classify_rel(rel: str) -> tuple[str, str | None]:
    """rules/ 底下相對路徑 → (分類, 縣市或辦公室代碼)。不合規定位置回 ('unknown', None)。"""
    parts = PurePosixPath(rel).parts
    if len(parts) < 3 or parts[0] != RULES_DIR:
        return "unknown", None
    cat = parts[1]
    if cat == "national" and len(parts) == 3:
        return "national", None
    if cat in ("local", "pending") and len(parts) == 4:
        return cat, parts[2]
    return "unknown", None


def rule_paths(repo_root=REPO_ROOT) -> list[Path]:
    """rules/national、local、pending 底下所有 .yaml／.yml（含放錯層的，交給 rule_check 報錯）。"""
    root = Path(repo_root)
    out = []
    for cat in CATEGORIES:
        base = root / RULES_DIR / cat
        if base.is_dir():
            out += [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in (".yaml", ".yml")]
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def load_rule_file(path: Path, repo_root=REPO_ROOT) -> RuleFile:
    rel = path.relative_to(Path(repo_root)).as_posix()
    cat, group = classify_rel(rel)
    rf = RuleFile(path=path, rel=rel, category=cat, group=group)
    try:
        rf.data = load_rule_text(read_text(path), rel)
    except (RuleFileError, UnicodeDecodeError) as exc:
        rf.error = str(exc)
    return rf


def load_all_rules(repo_root=REPO_ROOT) -> list[RuleFile]:
    return [load_rule_file(p, repo_root) for p in rule_paths(repo_root)]


def is_standard_format(rf: RuleFile) -> bool:
    """檔案位元組是否等於 dump_rule 的標準輸出（UTF-8 無 BOM、LF、固定引號與縮排規則）。解析失敗的檔回 True（交給格式錯檢查）。"""
    if rf.data is None:
        return True
    return rf.path.read_bytes() == dump_rule(rf.data).encode("utf-8")


def normalize_rule_files(repo_root=REPO_ROOT, write: bool = True) -> list[str]:
    """把可解析的規則檔改寫成標準格式（值不變，只改引號、換行、縮排、BOM）。回傳不標準（或已改寫）的相對路徑。
    解析失敗的檔不碰，留給 rule_check 報格式錯。"""
    changed = []
    for rf in load_all_rules(repo_root):
        if rf.data is None or is_standard_format(rf):
            continue
        changed.append(rf.rel)
        if write:
            data = dump_rule(rf.data).encode("utf-8")
            if load_rule_text(data.decode("utf-8"), rf.rel) != rf.data:  # 防呆：改寫不得改變值
                raise RuleFileError(f"{rf.rel}：正規化後內容不一致，未改寫")
            tmp = rf.path.with_name(rf.path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(rf.path)
    return changed


# ---------------------------------------------------------------- 排序與匯出

_CHUNK = re.compile(r"(\d+)")


def natural_key(text: str):
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in _CHUNK.split(text) if t)


def sort_key(rule_id: str, legacy_index: dict[str, int]):
    """排序鍵（規格見 _fields.yaml 的 sort_key）：原匯入規則依原 xlsx 列順序在前；
    其餘接在後面，依 rule_id 自然排序（GEN-2 在 GEN-10 前）。"""
    if rule_id in legacy_index:
        return (0, legacy_index[rule_id], ())
    return (1, 0, natural_key(rule_id))


def exported_rules(repo_root=REPO_ROOT, fields: dict | None = None) -> list[dict]:
    """要進匯出的規則內容（依排序鍵）。解析失敗或缺 rule_id 的檔直接丟例外，避免匯出缺漏。"""
    fields = fields or load_fields(repo_root)
    include = set(fields.get("export", {}).get("include_categories", ["national", "local"]))
    legacy_index = {r["rule_id"]: i for i, r in enumerate(load_legacy(repo_root))}
    rules = []
    for rf in load_all_rules(repo_root):
        if rf.category not in include:
            continue
        if rf.error:
            raise RuleFileError(f"{rf.rel}：{rf.error}")
        if not isinstance(rf.rule_id, str) or not rf.rule_id:
            raise RuleFileError(f"{rf.rel}：缺 rule_id")
        rules.append(rf.data)
    ids = [r["rule_id"] for r in rules]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise RuleFileError(f"rule_id 重複，無法匯出：{', '.join(dup)}")
    return sorted(rules, key=lambda r: sort_key(r["rule_id"], legacy_index))


def csv_cell(value) -> str:
    """與臺南原匯出相同：None → 空字串；反斜線加倍；儲存格內換行寫成字面 \\n。"""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def render_csv(rules: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([csv_cell(c) for c in columns])
    for r in rules:
        w.writerow([csv_cell(r.get(c)) for c in columns])
    return buf.getvalue()


def load_workbook_meta(repo_root=REPO_ROOT) -> dict:
    path = Path(repo_root) / WORKBOOK_META
    return load_yaml_text(read_text(path), str(path))


def meta_sheet_rows(repo_root, sheet: dict) -> list[list]:
    """_meta 內一個工作表 → 含表頭的二維格子（還原成原本的列與欄，空格為 None）。"""
    path = Path(repo_root) / META_DIR / sheet["file"]
    data = load_yaml_text(read_text(path), str(path))
    columns = data["columns"]
    if data.get("format") == "records":
        rows = [list(columns)] + [[rec.get(c) for c in columns] for rec in data["rows"]]
    else:
        rows = [list(columns)] + [list(r) for r in data["rows"]]
    width = data.get("width", len(columns))
    return [r + [None] * (width - len(r)) for r in rows]


STATUS_SHEET = "90_規則狀態"


def workbook_grids(repo_root=REPO_ROOT, fields: dict | None = None) -> list[tuple[str, list[list], dict]]:
    """匯出 xlsx 的全部工作表：[(名稱, 二維格子, 版面設定)]，依 workbook.yaml 順序。"""
    fields = fields or load_fields(repo_root)
    columns = fields["columns"]
    meta = load_workbook_meta(repo_root)
    rules = exported_rules(repo_root, fields)
    out = []
    for sheet in meta["sheets"]:
        layout = sheet.get("layout") or {}
        if sheet.get("source") == "rules":
            grid = [list(columns)] + [[r.get(c) for c in columns] for r in rules]
        else:
            grid = meta_sheet_rows(repo_root, sheet)
        out.append((sheet["name"], grid, layout))
    status_cols = fields.get("export", {}).get("status_sheet_columns")
    if status_cols:
        grid = [list(status_cols)] + [[_status_cell(r.get(c)) for c in status_cols] for r in rules]
        out.append((STATUS_SHEET, grid, {"freeze_panes": "A2"}))
    return out


def _status_cell(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_workbook(grids):
    """二維格子 → openpyxl Workbook（表頭粗體灰底、內文自動換行靠上、欄寬與凍結窗格照 _meta）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="E7E7E7")
    wrap = Alignment(wrap_text=True, vertical="top")
    for name, grid, layout in grids:
        ws = wb.create_sheet(name)
        for r_idx, row in enumerate(grid, 1):
            for c_idx, value in enumerate(row, 1):
                if value is None:
                    continue
                cell = ws.cell(row=r_idx, column=c_idx, value=value)
                cell.alignment = wrap
                if r_idx == 1:
                    cell.font = head_font
                    cell.fill = head_fill
        for letter, width in (layout.get("column_widths") or {}).items():
            ws.column_dimensions[letter].width = width
        if layout.get("freeze_panes"):
            ws.freeze_panes = layout["freeze_panes"]
    return wb


def read_workbook_grids(path: Path) -> dict[str, list[list]]:
    """讀 xlsx 每個工作表的儲存格值（去掉尾端全空列），供 --check 與往返驗證逐格比對。"""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        out = {}
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            while rows and all(v is None for v in rows[-1]):
                rows.pop()
            out[ws.title] = rows
        return out
    finally:
        wb.close()


def normalize_grid(grid: list[list]) -> list[list]:
    """比對用：補齊成同寬、去尾端全空列（xlsx 不保存空儲存格）。"""
    rows = [list(r) for r in grid]
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    width = max((len(r) for r in rows), default=0)
    rows = [r + [None] * (width - len(r)) for r in rows]
    while width and all(r[width - 1] is None for r in rows):
        width -= 1
        rows = [r[:width] for r in rows]
    return rows


# ---------------------------------------------------------------- 網址白名單

def url_host_allowed(url: str, fields: dict) -> tuple[bool, str]:
    """回 (是否合格, 說明)。規則見 _fields.yaml 的 source_url。"""
    spec = fields.get("source_url", {})
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False, "不是合法網址"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False, "須為 http(s):// 開頭的完整網址"
    host = parts.hostname.lower()
    from urllib.parse import parse_qsl
    blank = [k for k, v in parse_qsl(parts.query, keep_blank_values=True) if not v.strip()]
    if blank or parts.query.rstrip().endswith("="):
        return False, f"查詢參數 {', '.join(blank) or parts.query} 沒有值（範本網址沒填完？）"
    if host in {h.lower() for h in spec.get("allowed_hosts", [])}:
        return True, ""
    suffix = spec.get("local_host_suffix", ".gov.tw")
    tokens = [t.lower() for t in spec.get("local_host_tokens", [])]
    if host.endswith(suffix):
        labels = host[: -len(suffix)].split(".")
        if any(tok in label for label in labels for tok in tokens):
            return True, ""
    return False, f"網域 {host} 不在官方白名單"
