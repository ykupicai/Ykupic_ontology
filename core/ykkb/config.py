"""辦公室設定（office.yaml）讀取與驗證。

找設定檔的順序（不靠目前工作目錄）：
  1. 呼叫端傳入的 path
  2. 環境變數 YKKB_OFFICE_CONFIG
  3. repo 根目錄的 office.yaml（repo 根由本檔位置推得：core/ykkb/config.py 往上兩層）

找不到或內容不合法時一律丟出 OfficeConfigError，訊息說明怎麼修；不猜路徑、不自動補 vault 位置。

限制級目錄名（restricted_dir_names）的預設值只定義在本檔 DEFAULT_RESTRICTED_DIR_NAMES，
其他模組一律經由設定取得（core/tests/test_restricted_dir_single_source.py 會擋回流）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "YKKB_OFFICE_CONFIG"
CONFIG_NAME = "office.yaml"
EXAMPLE_NAME = "office.example.yaml"
OFFICES_NAME = "offices.yaml"

# 限制級資料目錄名（委員資料等）：唯一預設定義處。比對時不分大小寫、路徑任一層整段比對。
DEFAULT_RESTRICTED_DIR_NAMES = ("30_committees",)
DEFAULT_SHARED_DIRS = {
    "rules": "03_案件經驗知識層/70_法規索引/_shared",
    "law_notes": "03_案件經驗知識層/71_核心法規全文/_shared",
}
ALLOWED_KEYS = {
    "office_code", "office_name", "vault_root", "restricted_dir_names",
    "shared_dirs", "extra_export_targets", "sync_backup_dir", "require_office_field",
}
DEFAULT_SYNC_BACKUP_DIRNAME = "_sync_backups"   # 未設定 sync_backup_dir 時：repo 根底下（已列 .gitignore）
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class OfficeConfigError(ValueError):
    """office.yaml／offices.yaml 缺漏或不合法。"""


def _hint() -> str:
    return (f"請把 repo 根目錄的 {EXAMPLE_NAME} 複製為 {CONFIG_NAME} 並填寫"
            f"（或以環境變數 {ENV_VAR} 指定設定檔路徑）。")


def _load_yaml_file(path: Path, label: str) -> dict:
    from ykkb.metadata import load_yaml  # 延遲匯入，避免與 metadata 互相匯入

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise OfficeConfigError(f"讀不到{label}：{path}（{exc}）") from exc
    try:
        return load_yaml(text)
    except ValueError as exc:
        raise OfficeConfigError(f"{label}格式錯誤：{path}（{exc}）") from exc


def resolve_config_path(path=None) -> Path:
    """回傳要讀的 office.yaml 路徑（不檢查存在與否）。"""
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return Path(env)
    return REPO_ROOT / CONFIG_NAME


def load_office_codes(offices_path=None) -> dict[str, dict]:
    """讀 offices.yaml，回傳 {辦公室代碼: 該列資料}。

    接受三種寫法：
      offices: {TN: {...}, HC: {...}}
      offices: [{code: TN, ...}, ...]   （code 或 office_code）
      TN: {...}                          （頂層直接以代碼為鍵）
    """
    path = Path(offices_path) if offices_path is not None else REPO_ROOT / OFFICES_NAME
    if not path.is_file():
        raise OfficeConfigError(f"找不到辦公室代碼表 {path}；這個檔應隨 repo 一起 clone 下來。")
    data = _load_yaml_file(path, "辦公室代碼表")
    body = data.get("offices", data)
    codes: dict[str, dict] = {}
    if isinstance(body, dict):
        for code, value in body.items():
            if isinstance(code, str) and _CODE_PATTERN.match(code):
                codes[code] = dict(value) if isinstance(value, dict) else {"name": value}
    elif isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                code = item.get("code", item.get("office_code"))
                if isinstance(code, str) and _CODE_PATTERN.match(code):
                    codes[code] = dict(item)
    if not codes:
        raise OfficeConfigError(f"辦公室代碼表 {path} 沒有任何有效代碼（大寫英數，例：TN、HC、TP）。")
    return codes


def _relative_dir(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfficeConfigError(f"shared_dirs.{label} 必須是非空字串（相對 vault_root 的路徑）。")
    text = value.strip().replace("\\", "/").strip("/")
    pure = PurePosixPath(text)
    if (value.strip().startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value.strip())
            or any(part in ("..", ".") for part in pure.parts) or not pure.parts):
        raise OfficeConfigError(f"shared_dirs.{label} 必須是 vault_root 底下的相對路徑，不可為絕對路徑或含 ..：{value!r}")
    return pure.as_posix()


def _is_within(path: str, root: str) -> bool:
    """path 是否等於 root 或位於其下（不分大小寫、斜線方向一致化）。"""
    norm = lambda value: os.path.normcase(os.path.abspath(value.replace("\\", "/"))).rstrip("\\/")  # noqa: E731
    child, parent = norm(path), norm(root)
    return child == parent or child.startswith(parent + os.sep)


def load_office_config(path=None, *, offices_path=None, require_vault_exists: bool = True) -> dict:
    """讀取並驗證 office.yaml，回傳正規化後的 dict。

    回傳鍵：office_code、office_name、vault_root（str）、restricted_dir_names（list[str]）、
    shared_dirs（{"rules", "law_notes"}，相對 vault_root 的 posix 路徑）、
    extra_export_targets（list[str]）、sync_backup_dir（絕對路徑，vault 外；預設 repo 根 _sync_backups）、
    require_office_field（bool，預設 False）、office_codes（代碼表全部代碼）、config_path、repo_root。
    require_vault_exists=False 只給 init_vault 用（vault 可能尚未建立，但上層資料夾須存在）。
    """
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise OfficeConfigError(f"找不到辦公室設定檔 {config_path}。" + _hint())
    data = _load_yaml_file(config_path, "辦公室設定檔")
    unknown = sorted(str(key) for key in data if key not in ALLOWED_KEYS)
    if unknown:
        raise OfficeConfigError(f"{config_path} 有無法辨識的欄位：{', '.join(unknown)}（可用欄位見 {EXAMPLE_NAME}）。")

    code = data.get("office_code")
    if not isinstance(code, str) or not code.strip():
        raise OfficeConfigError(f"{config_path} 缺 office_code（必填）。" + _hint())
    code = code.strip()
    codes = load_office_codes(offices_path)
    if code not in codes:
        raise OfficeConfigError(f"office_code {code!r} 不在辦公室代碼表內（可用：{', '.join(sorted(codes))}）。")

    name = data.get("office_name")
    if name is not None and not isinstance(name, str):
        raise OfficeConfigError("office_name 必須是字串。")
    if not name:
        name = str(codes[code].get("name") or code)

    vault_root = data.get("vault_root")
    if not isinstance(vault_root, str) or not vault_root.strip() or "<" in vault_root:
        raise OfficeConfigError(f"{config_path} 的 vault_root 未填或仍是範本佔位字串（必填，填自己辦公室 vault 的完整路徑）。")
    vault_root = vault_root.strip()
    vault_path = Path(vault_root)
    if require_vault_exists and not vault_path.is_dir():
        raise OfficeConfigError(f"vault_root 不存在或不是資料夾：{vault_root}（新辦公室請先跑 init_vault.py；NAS 路徑請確認可連線）。")
    if not require_vault_exists and not vault_path.is_dir() and not vault_path.parent.is_dir():
        raise OfficeConfigError(f"vault_root 的上層資料夾不存在：{vault_path.parent}（不自動建立多層路徑，請確認路徑沒打錯）。")

    restricted = data.get("restricted_dir_names", list(DEFAULT_RESTRICTED_DIR_NAMES))
    if (not isinstance(restricted, list) or not restricted
            or not all(isinstance(item, str) and item.strip() for item in restricted)):
        raise OfficeConfigError("restricted_dir_names 必須是非空的字串清單（例：[30_committees]）。")
    restricted = [item.strip() for item in restricted]
    if any(re.search(r"[\\/]", item) for item in restricted):
        raise OfficeConfigError("restricted_dir_names 每項是單一目錄名，不可含路徑分隔符號。")

    shared_raw = data.get("shared_dirs") or {}
    if not isinstance(shared_raw, dict):
        raise OfficeConfigError("shared_dirs 必須是對照表（rules、law_notes）。")
    extra_keys = sorted(str(key) for key in shared_raw if key not in DEFAULT_SHARED_DIRS)
    if extra_keys:
        raise OfficeConfigError(f"shared_dirs 只接受 rules、law_notes，無法辨識：{', '.join(extra_keys)}")
    shared = {key: _relative_dir(shared_raw.get(key, default), key) for key, default in DEFAULT_SHARED_DIRS.items()}
    rules_parts = PurePosixPath(shared["rules"].casefold()).parts
    notes_parts = PurePosixPath(shared["law_notes"].casefold()).parts
    shorter = min(len(rules_parts), len(notes_parts))
    if rules_parts[:shorter] == notes_parts[:shorter]:
        raise OfficeConfigError("shared_dirs.rules 與 shared_dirs.law_notes 不可相同或互相包含（同步時會整個替換資料夾）。")
    folded = {item.casefold() for item in restricted}
    for key, rel in shared.items():
        if any(part.casefold() in folded for part in PurePosixPath(rel).parts):
            raise OfficeConfigError(f"shared_dirs.{key} 不可位於限制級目錄內：{rel}")

    extra = data.get("extra_export_targets") or []
    if not isinstance(extra, list) or not all(isinstance(item, str) and item.strip() for item in extra):
        raise OfficeConfigError("extra_export_targets 必須是字串清單（絕對路徑），不用時留 []。")
    extra = [item.strip() for item in extra]
    for item in extra:
        if not (Path(item).is_absolute() or item.startswith(("//", "\\\\"))):
            raise OfficeConfigError(f"extra_export_targets 必須是絕對路徑：{item!r}")

    backup = data.get("sync_backup_dir")
    if backup is None or (isinstance(backup, str) and not backup.strip()):
        backup = str(REPO_ROOT / DEFAULT_SYNC_BACKUP_DIRNAME)
    elif not isinstance(backup, str) or not (Path(backup.strip()).is_absolute() or backup.strip().startswith(("//", "\\\\"))):
        raise OfficeConfigError(f"sync_backup_dir 必須是絕對路徑：{backup!r}")
    backup = backup.strip()
    if _is_within(backup, vault_root):
        raise OfficeConfigError(f"sync_backup_dir 不可位於 vault_root 內（備份要放 vault 外）：{backup}")

    require_office = data.get("require_office_field", False)
    if not isinstance(require_office, bool):
        raise OfficeConfigError("require_office_field 必須是 true 或 false。")

    return {
        "office_code": code,
        "office_name": name,
        "vault_root": vault_root,
        "restricted_dir_names": restricted,
        "shared_dirs": shared,
        "extra_export_targets": extra,
        "sync_backup_dir": backup,
        "require_office_field": require_office,
        "office_codes": sorted(codes),
        "config_path": str(config_path),
        "repo_root": str(REPO_ROOT),
    }


def restricted_dir_names(config: dict | None = None) -> tuple[str, ...]:
    """限制級目錄名清單：有設定用設定，否則用本檔預設值。"""
    if config and config.get("restricted_dir_names"):
        return tuple(config["restricted_dir_names"])
    return DEFAULT_RESTRICTED_DIR_NAMES
