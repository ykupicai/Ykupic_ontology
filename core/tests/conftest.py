"""測試共用設定：把 core/ 與 core/tools/ 加進匯入路徑，並提供暫存辦公室設定。

所有測試只用暫存目錄，不依賴 NAS、不讀 repo 根的 office.yaml。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
for _path in (CORE, CORE / "tools"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

OFFICES_YAML = """\
offices:
  TN: {name: 臺南辦公室}
  HC: {name: 新竹辦公室}
  TP: {name: 台北辦公室}
"""


@pytest.fixture(autouse=True)
def _isolate_office_env(monkeypatch):
    """避免開發者本機設定的 YKKB_OFFICE_CONFIG 影響測試。"""
    monkeypatch.delenv("YKKB_OFFICE_CONFIG", raising=False)


@pytest.fixture
def make_office(tmp_path):
    """建暫存 offices.yaml＋office.yaml，回傳 (load_office_config 結果, office.yaml 路徑, vault 路徑)。"""
    from ykkb import config

    def _make(body: str | None = None, *, vault_name: str = "vault", create_vault: bool = True,
              require_vault_exists: bool = True):
        vault = tmp_path / vault_name
        if create_vault:
            vault.mkdir(exist_ok=True)
        offices = tmp_path / "offices.yaml"
        offices.write_text(OFFICES_YAML, encoding="utf-8")
        office = tmp_path / "office.yaml"
        if body is None:
            body = (f"office_code: HC\noffice_name: 新竹辦公室\nvault_root: {vault.as_posix()}\n"
                    f"sync_backup_dir: {(tmp_path / 'sync_backups').as_posix()}\n")
        office.write_text(body, encoding="utf-8")
        cfg = config.load_office_config(office, offices_path=offices,
                                        require_vault_exists=require_vault_exists)
        return cfg, office, vault

    return _make
