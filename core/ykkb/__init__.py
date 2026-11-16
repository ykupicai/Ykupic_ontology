"""ykkb：多辦公室共用知識庫的核心模組（設定、metadata 解析、schema 驗證、規則檔）。

各工具（core/tools/*.py）以 `core/` 為匯入根目錄：`from ykkb import config`。
本套件不寫死任何路徑；vault 位置一律由 repo 根的 office.yaml 提供。
"""
