"""rules/ → exports/法令檢核規則庫.csv 與 exports/法令檢核規則庫.xlsx。

用法：
  python -X utf8 core/tools/rulebook_export.py           先把 rules/ 規則檔整理成標準格式（值不變），再重產匯出（內容沒變的檔不重寫）
  python -X utf8 core/tools/rulebook_export.py --check   只比對、不寫檔；規則檔格式不標準或匯出過期回 1

CSV 與臺南原匯出格式相同（UTF-8 with BOM、LF、每條規則一行、儲存格內換行寫成字面 \\n），逐位元組比對。
xlsx 的位元組會隨 openpyxl 版本變動，--check 改為逐格比對儲存格內容（工作表名、順序、每格值）。
本機產出時固定 zip 內時間戳與文件屬性時間，同一環境重跑位元組相同。
規格（欄位、排序鍵、哪些規則進匯出）見 rules/_fields.yaml。
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ykkb import rules as rl  # noqa: E402

FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
FIXED_DOC_TIME = "2026-01-01T00:00:00Z"


def render_all(repo_root: Path):
    """回傳 (csv 文字, 工作表格子清單)。"""
    fields = rl.load_fields(repo_root)
    rules = rl.exported_rules(repo_root, fields)
    text = rl.render_csv(rules, fields["columns"])
    grids = rl.workbook_grids(repo_root, fields)
    return text, grids, len(rules)


def xlsx_bytes(grids) -> bytes:
    """產生 xlsx 並把 zip 時間戳、core.xml 建立／修改時間固定，讓輸出可重現。"""
    wb = rl.build_workbook(grids)
    wb.properties.creator = "rulebook_export"
    wb.properties.lastModifiedBy = "rulebook_export"
    raw = io.BytesIO()
    wb.save(raw)
    src = zipfile.ZipFile(io.BytesIO(raw.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                              rb"\g<1>" + FIXED_DOC_TIME.encode() + rb"\g<2>", data)
            zi = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            dst.writestr(zi, data)
    return out.getvalue()


def xlsx_diff(path: Path, grids) -> list[str]:
    """逐格比對既有 xlsx 與應有內容，回傳差異說明（最多列 20 筆）。"""
    if not path.is_file():
        return [f"{path.name} 不存在"]
    try:
        actual = rl.read_workbook_grids(path)
    except Exception as exc:  # noqa: BLE001 - 壞檔一律視為過期
        return [f"{path.name} 無法讀取（{type(exc).__name__}）"]
    diffs = []
    expected_names = [name for name, _, _ in grids]
    if list(actual) != expected_names:
        diffs.append(f"工作表不同：應為 {expected_names}，實際 {list(actual)}")
    for name, grid, _ in grids:
        if name not in actual:
            continue
        exp = rl.normalize_grid(grid)
        got = rl.normalize_grid(actual[name])
        if len(exp) != len(got):
            diffs.append(f"{name}：列數應為 {len(exp)}，實際 {len(got)}")
        for r, (er, gr) in enumerate(zip(exp, got), 1):
            if er != gr:
                for c in range(max(len(er), len(gr))):
                    ev = er[c] if c < len(er) else None
                    gv = gr[c] if c < len(gr) else None
                    if ev != gv:
                        diffs.append(f"{name}!{_col(c)}{r} 不同")
                        break
            if len(diffs) >= 20:
                return diffs
    return diffs


def _col(index: int) -> str:
    letters, index = "", index + 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def check(repo_root: Path, include_format: bool = True) -> list[str]:
    """回傳過期說明清單；空清單＝規則檔皆為標準格式、匯出與 rules/ 一致。
    rule_check 以 include_format=False 呼叫（格式另由它逐檔報錯）。"""
    problems = []
    if include_format:
        for rel in rl.normalize_rule_files(repo_root, write=False):
            problems.append(f"{rel} 不是標準格式")
    text, grids, _ = render_all(repo_root)
    csv_path = repo_root / rl.EXPORT_DIR / rl.CSV_NAME
    expected = text.encode("utf-8-sig")
    if not csv_path.is_file():
        problems.append(f"{rl.EXPORT_DIR}/{rl.CSV_NAME} 不存在")
    elif csv_path.read_bytes() != expected:
        problems.append(f"{rl.EXPORT_DIR}/{rl.CSV_NAME} 與 rules/ 不一致")
    for d in xlsx_diff(repo_root / rl.EXPORT_DIR / rl.XLSX_NAME, grids):
        problems.append(f"{rl.EXPORT_DIR}/{rl.XLSX_NAME}：{d}")
    return problems


def _write_if_changed(path: Path, data: bytes) -> bool:
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return True


def export(repo_root: Path) -> tuple[int, list[str]]:
    """先把規則檔正規化成標準格式（值不變），再產生匯出。回傳 (規則數, 改寫或更新的檔名)。"""
    written = list(rl.normalize_rule_files(repo_root, write=True))
    text, grids, n = render_all(repo_root)
    csv_path = repo_root / rl.EXPORT_DIR / rl.CSV_NAME
    if _write_if_changed(csv_path, text.encode("utf-8-sig")):
        written.append(csv_path.name)
    xlsx_path = repo_root / rl.EXPORT_DIR / rl.XLSX_NAME
    # 內容相同就不重寫，避免不同 openpyxl 版本只因位元組差異產生無意義的 git 變動
    if xlsx_diff(xlsx_path, grids):
        _write_if_changed(xlsx_path, xlsx_bytes(grids))
        written.append(xlsx_path.name)
    return n, written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只比對，不寫檔；過期回 1")
    ap.add_argument("--repo-root", type=Path, default=rl.REPO_ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.repo_root.resolve()
    try:
        if a.check:
            problems = check(root)
            for p in problems:
                print(f"過期：{p}")
            if problems:
                print("規則檔格式或匯出未同步。修法：先跑 python -X utf8 core/tools/rulebook_export.py（會自動整理格式並重產匯出），再 git add rules exports")
                return 1
            print("匯出與 rules/ 一致")
            return 0
        n, written = export(root)
    except rl.RuleFileError as exc:
        print(f"無法匯出：{exc}\n先跑 python -X utf8 core/tools/rule_check.py 看完整錯誤清單。")
        return 2
    print(f"規則 {n} 條；" + (f"已改寫／更新：{', '.join(written)}" if written else "規則檔格式與匯出皆已是最新，未改檔"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
