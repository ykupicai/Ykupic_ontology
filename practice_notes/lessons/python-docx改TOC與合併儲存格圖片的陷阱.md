---
type: lesson
source: claude-code-projects
updated: 2026-09-21
source_office: TN
deidentified: true
---

# python-docx 改 TOC 條目、合併儲存格圖片、圖內標題佔位字元的三個陷阱

## 情境
臺南市農再案期中報告書，要用 python-docx 批次改表4-17~20數字、移除「圖4-15…（需更換）」標記、換上新繪製的國土利用調查地圖。

## 踩坑一：TOC 條目用 `paragraph.runs` 抓不到文字
Word 目錄（TOC）條目的標題文字＋Tab＋頁碼，常被包在 `w:hyperlink` 底下，且頁碼是 `PAGEREF` 欄位（`fldChar`/`instrText` 結構）。`paragraph.runs`（python-docx 公開屬性）**只抓 `w:p` 的直接子層 `w:r`**，不會遞迴進 `w:hyperlink`，所以對 TOC 段落呼叫 `paragraph.runs` 會回傳**空列表**，即使 `paragraph.text`（走 XPath `.//w:t`）能正常讀到完整文字。用「先讀 runs 再覆寫」的改法會誤判成「沒有 run」而新增一個 run，造成內容重複、且沒動到真正該改的文字。

**正確做法**：改標題文字時直接對 `paragraph._element.findall('.//' + qn('w:t'))` 逐一檢查、命中就地 `.text` 取代，不經過 `.runs`。這樣不會動到 `PAGEREF` 欄位結構，頁碼與跳轉功能都保留。
```python
def patch_wt_substr(paragraph, old, new):
    for node in paragraph._element.findall('.//' + qn('w:t')):
        if node.text and old in node.text:
            node.text = node.text.replace(old, new)
```
此案改完直接用 LibreOffice 轉 PDF 檢查，TOC 頁**第一次就顯示正確**，沒有遇到專案筆記提過的「TOC 欄位快取要改兩次才生效」問題——因為那個問題通常發生在「改了標題本體、指望 TOC 自動重算」的情境，這裡是直接改 TOC 條目自己的快取文字，屬不同失敗模式。

## 踩坑二：水平合併儲存格（gridSpan）在 python-docx 裡是同一顆 tc
一張圖＋圖說被放進一個 `2 欄合併成 1 欄`（`gridSpan=2`）的儲存格。用 `row.cells[0]` 和 `row.cells[1]` 分別讀取，兩者**回傳相同文字**，一開始以為是資料重複，其實是 python-docx 對 gridSpan 儲存格會讓兩個邏輯欄位都指到同一個底層 `<w:tc>`。**只需要編輯 `cells[0]`（或任一欄），不要兩欄都改，否則等於改兩次或誤判成兩個獨立值要分別替換。**

## 踩坑三：置換內嵌圖片，直接換 blob 比 add_picture 更穩
要把儲存格裡既有的圖換成新圖，且**版面／裁切／尺寸完全不變**時，不要用 `run.add_picture()` 重新插入（要重新算 extent、可能連動段落結構），而是：
1. 找到該 `w:drawing` 底下的 `a:blip` 的 `r:embed` 取得 relationship id
2. `image_part = doc.part.related_parts[rid]`
3. 換位元組即可：`image_part._blob = new_image_bytes`（`Part.blob` 這個公開屬性本身就是回傳 `self._blob`，存檔時直接序列化這個值）
4. 換之前**務必先比對新舊圖片的長寬比**（`PIL.Image.open(...).size`），只有比例相近才能安全沿用舊的 `wp:extent`／`a:ext`，否則要連動改尺寸避免變形。

## 踩坑四：matplotlib 產的地圖標題留了佔位字元「圖4-XX」，插入文件後才發現編號沒填
繪圖腳本裡 `ax.set_title("圖4-XX、……")` 的 `XX` 是先寫的佔位字元，等最終確認文件裡這張圖該編第幾號再回填——但因為是另一支獨立腳本、插入文件是另一個步驟，中間忘了回填，直到把圖插進文件、轉 PDF 檢查時才看到圖內標題與圖說編號兜不起來（圖說寫「圖4-15」，圖內卻印著「圖4-XX」）。

**判斷準則**：任何會把「圖號」畫進點陣圖本體（而非只寫在 docx 圖說段落）的繪圖腳本，**在確認該圖於文件中的正式編號之前，一律先用佔位字元且不要急著插入定稿文件**；插入前的最後一步一定要重新檢視一次圖片本身渲染出的文字，不能只信任程式碼裡寫的字串（佔位字元本身也可能忘記替換）。

## 相關
案件成果沉澱機制、`master_edit.py`（本案批次改表格數字＋圖片置換的腳本，存於該次 session scratchpad，未沉澱為 skill）
