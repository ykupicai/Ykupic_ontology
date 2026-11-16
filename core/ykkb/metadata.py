"""共用、唯讀的 YAML 解析與舊版 metadata 相容讀取。

相容讀取不查證法規、不推進日期、不改變案件判斷。
必須安裝 PyYAML；壞掉或重複鍵的 YAML 一律明確失敗，不可看起來像空資料。
（移植自臺南維護者 repo 的 _knowledge_metadata.py，行為不變；
限制級目錄名改由 office.yaml 的 restricted_dir_names 提供，預設值見 ykkb.config。）
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

from ykkb import config as _config

# --- 限制級資料目錄 --------------------------------------------------------------
# 目錄名的唯一來源是 office.yaml 的 restricted_dir_names（未設定時用
# ykkb.config.DEFAULT_RESTRICTED_DIR_NAMES）。其他模組不得再寫死目錄名，
# core/tests/test_restricted_dir_single_source.py 會擋下回流。
# 判定採「路徑任一層目錄名整段命中、不分大小寫」而非完整路徑：同名目錄放錯層也照樣排除，寧可多擋。
COMMITTEE_LAYER = "02_審議資料庫知識層"


def _folded(names: Iterable[str] | None) -> frozenset[str]:
    source = _config.restricted_dir_names() if names is None else names
    return frozenset(name.casefold() for name in source)


def is_restricted_dir_name(name: str, names: Iterable[str] | None = None) -> bool:
    """單一目錄名是否為限制級資料目錄（不分大小寫、整段比對）。"""
    return name.casefold() in _folded(names)


def in_restricted_dir(parts, names: Iterable[str] | None = None) -> bool:
    """路徑分段中是否有任一層是限制級資料目錄。最後一段若是檔名也一併比對，無害。"""
    folded = _folded(names)
    return any(part.casefold() in folded for part in parts)


# --- 限制級標記（sensitivity 欄位）：唯一判定處 -----------------------------------
# 散在一般目錄的限制級筆記不受目錄名排除保護，sensitivity 欄位是它們唯一的防線，
# 因此判定採「寧可多擋」：
# - 沒有 sensitivity 欄位 → 非限制。
# - 字串值去前後空白、不分大小寫後，屬 SENSITIVITY_NON_RESTRICTED → 非限制。
# - 其餘一律視為限制級：restricted 的各種寫法、未知字串、空字串、null、清單／數字等非字串型別。
SENSITIVITY_RESTRICTED = "restricted"
SENSITIVITY_NON_RESTRICTED = frozenset({"public", "internal"})


# frontmatter 位置不標準（開頭多了空行或空白）時，Obsidian 與本模組都不會把它當
# frontmatter，sensitivity 欄位因此讀不到、筆記會被當成非限制。
# 補一道 fail-closed：沒解析出 sensitivity 欄位，但筆記開頭幾行出現 `sensitivity:`，
# 就視為「標記寫壞了」。呼叫端把回傳的佔位值放進 metadata，仍由 is_restricted 判定。
SENSITIVITY_UNPARSED = "unparsed_marker"
_SENSITIVITY_HEAD_LINES = 20
_SENSITIVITY_LINE = re.compile(r"^[ \t]*sensitivity[ \t]*:", re.M | re.I)


def has_unparsed_sensitivity_marker(text: str, metadata) -> bool:
    """metadata 沒有 sensitivity 欄位，但原文前 20 行有 `sensitivity:` 開頭的行。"""
    if isinstance(metadata, dict) and "sensitivity" in metadata:
        return False
    head = text.lstrip("﻿").replace("\r\n", "\n").split("\n")[:_SENSITIVITY_HEAD_LINES]
    return bool(_SENSITIVITY_LINE.search("\n".join(head)))


def sensitivity_state(metadata) -> str:
    """回傳 sensitivity 判定：'absent'（無欄位）、'non_restricted'、'restricted'
    （可辨識的限制級寫法）、'unrecognized'（欄位存在但值無法辨識，比照限制級）。"""
    if not isinstance(metadata, dict) or "sensitivity" not in metadata:
        return "absent"
    value = metadata["sensitivity"]
    if not isinstance(value, str):
        return "unrecognized"
    folded = value.strip().casefold()
    if folded == SENSITIVITY_RESTRICTED:
        return "restricted"
    if folded in SENSITIVITY_NON_RESTRICTED:
        return "non_restricted"
    return "unrecognized"


def is_restricted(metadata) -> bool:
    """是否應視為限制級（fail-closed：無法辨識的值一律當限制級）。"""
    return sensitivity_state(metadata) in ("restricted", "unrecognized")


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ValueError("YAML mapping keys must be hashable scalars") from exc
        if duplicate:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", re.S)
DEPTHS = {"骨架": "folder_only", "骨架（待補卷）": "folder_only",
          "文件萃取": "document_extracted", "深度訪談": "interview_validated"}


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_plain(val) for val in value]
    return value


def load_yaml(text: str) -> dict:
    try:
        data = yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    return _plain(data)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    match = FRONTMATTER.match(text)
    if not match:
        if text.startswith("---\n"):
            raise ValueError("Unclosed YAML frontmatter")
        return {}, text
    return load_yaml(match[1]), text[match.end():]


def iso_date(value):
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|[^\d])", str(value or ""))
    if match:
        try:
            return date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    return None


def valid_official_url(value):
    """只驗網址語法與主機名稱；不代表可連線、內容真實或法律效力。"""
    if not isinstance(value, str) or any(ch.isspace() for ch in value):
        return False
    if any(ch in value for ch in '<>（），；。'):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme in ('http', 'https') and bool(url.hostname)
                and url.hostname.lower().endswith('.gov.tw')
                and url.username is None and url.password is None)
    except ValueError:
        return False


def legacy_official_url(value):
    """只取開頭的官方網址，來源註記原樣保留。"""
    if not isinstance(value, str):
        return None
    match = re.match(r'https?://[^\s<>()（），；。]+', value)
    candidate = match[0] if match else None
    return candidate if valid_official_url(candidate) else None


def normalize_metadata(metadata: dict, path: str = "") -> dict:
    """相容讀取檢視；明確填寫的欄位一律優先於舊欄位映射。"""
    data = dict(metadata)
    if "source_depth" not in data and isinstance(data.get("depth"), str) and data["depth"] in DEPTHS:
        data["source_depth"] = DEPTHS[data["depth"]]
    if "verified_at" not in data and data.get("verified"):
        stamp = iso_date(data["verified"])
        if stamp:
            data["verified_at"] = stamp
            data.setdefault("verification_scope", str(data["verified"]))
    is_law = data.get("type") in ("law-digest", "核心法規重點") or "71_核心法規全文" in path
    if is_law:
        if "official_url" not in data:
            source = data.get("官方網址") or data.get("source")
            url = legacy_official_url(source)
            if url:
                data["official_url"] = url
        # 缺 legal_status 視為 unknown，不視為有效；不構成新的法規查證。
        data.setdefault("legal_status", "unknown")
    return data


def load_eval_progress(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records = load_yaml(path.read_text(encoding="utf-8-sig")).get("done", {})
    if not isinstance(records, dict):
        raise ValueError("evaluation progress.done must be a mapping")
    result = {}
    for cid, value in records.items():
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError(f"Invalid evaluation case ID: {cid!r}")
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"Invalid evaluation record: {cid}")
        result[cid] = dict(value or {})
        if not cid.startswith("EV-"):
            result[cid]["identity_status"] = "needs_case_id"
    return result


def eval_progress_status(record: dict) -> str:
    explicit = record.get("review_state")
    if explicit:
        return explicit
    if record.get("method") == "none":
        return "needs_source"
    if record.get("confidence") in {"低", "low", "無"}:
        return "needs_review"
    return "read_recorded"
