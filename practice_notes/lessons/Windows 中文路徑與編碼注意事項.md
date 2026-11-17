---
type: lesson
source: claude-code-projects
source_office: TN
deidentified: true
updated: 2026-11-17
---

# Windows 中文路徑與編碼注意事項

## 問題
PowerShell、VBS、Python、批次檔與 Windows 預設 Big5/CP950 在中文路徑下容易發生亂碼或啟動失敗。

## 原因
不同工具的預設編碼不同，PowerShell 5.1 與 wscript 對檔案編碼尤其敏感。

## 解法
- Python 執行資料處理時優先使用 `python -X utf8`。
- PowerShell 腳本若需在 PS 5.1 執行，必要時使用 UTF-8 with BOM。
- VBS 使用 UTF-16。
- 路徑使用 `-LiteralPath` 或完整引號。
- 啟動腳本需實測重開機與登入初期狀態。

## ★ 三條追加鐵則（2026-07 多專案實踩）

1. **中文絕不經 PowerShell stdin**（minitaiwan R7）：透過 stdin 餵中文給 PowerShell，
   cp950 會把內容毀掉。**改為先寫 UTF-8 檔案再執行**，Python 一律加 `-X utf8`。
   同理，heredoc 內別嵌反斜線路徑（`\1`、`\P` 會被當跳脫字元），改寫成 `.py` 檔用 argv 傳正斜線路徑。
2. **Bash 的 `cp`／`mv` 會弄壞中文路徑**（願景圖繪製專案雷區 13）：
   Windows 上凡涉及中文檔名／路徑的複製搬移，**一律用 PowerShell 或 Python `shutil`**，不要用 Bash。
3. **Python 讀含中文的 NAS 路徑時 cp950 會爛掉**（NAS 整理專案）：
   若無法用 `-X utf8` 解決，退回**三段式**——
   PowerShell 複製到 ASCII 暫存路徑 → Python 處理 → PowerShell 複製回 NAS。

## ★ 別被主控台亂碼騙

**PowerShell 顯示中文亂碼 ≠ 檔案內容壞了。** 那是主控台輸出編碼問題，內檔往往仍是正確 UTF-8。
驗證方式：另開一個 `python -X utf8` 讀該檔印出來確認。
（NAS 整理專案曾因此白花時間「修」根本沒壞的檔。）

## 下次注意
只在已登入 session 手動測試，不代表真實重開機後一定成功。

## 相關專案
- 報帳工具
- 備標團隊組成
- 審議資料庫
- NAS評估案件整理、minitaiwan、願景圖繪製

