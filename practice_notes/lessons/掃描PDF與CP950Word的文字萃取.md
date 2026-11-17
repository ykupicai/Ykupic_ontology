---
type: lesson
source: claude-code-projects
updated: 2026-06-25
source_office: TN
deidentified: true
---

# 掃描 PDF 與 CP950 Word 的文字萃取

## 問題
NAS 上大量計畫書／公文是 **掃描影像 PDF（無文字層）** 或 **CP950 舊編碼 Word**，直接 `pdftotext` 得到空白、`python-docx` 讀出滿是亂碼，看似「讀不到內容」。

## 原因
- 掃描 PDF 只有影像、沒有文字層。
- 早期 Word 內文以 Big5/CP950 儲存，目錄／圖表清單列尤其容易亂碼。

## 解法
- **CP950 Word**：用 `python-docx` 逐段讀，**本文其實可讀**；用正則 `[一-鿿]` + 關鍵詞過濾掉亂碼的目錄列即可萃取出申請人、地號、面積、文號等。輸出前設 `PYTHONIOENCODING=utf-8` 避免 console cp950 報錯。
- **掃描 PDF（OCR）**：本機 **Tesseract 已裝**（`C:\Program Files\Tesseract-OCR\tesseract.exe`，含繁中 `chi_tra`）。流程：`pip install pymupdf` → `fitz` 開檔逐頁 `page.get_pixmap(dpi=250)` 存 PNG → `subprocess` 呼叫 `tesseract img out -l chi_tra+eng --psm 3` → 收 `.txt`。長文件取前 15–20 頁即涵蓋摘要／基本資料／變更／環境章。
- 本機**無** poppler/pdftoppm、pytesseract、easyocr；用上述 PyMuPDF + Tesseract 組合最省事。

## 下次注意
- 萃取案件資料時**避開 `報價/契約` docx**（含金額），依知識庫規則不得入庫。
- OCR 全文可暫存本機 `_ocr_*.txt` 供細讀，但勿把整份原文倒進正式筆記——只萃取重點。
- 詳細指令見記憶 `nas-pdf-ocr-method`。

## 相關
- NAS路徑各工具斜線與存取差異
- [[Windows 中文路徑與編碼注意事項]]
