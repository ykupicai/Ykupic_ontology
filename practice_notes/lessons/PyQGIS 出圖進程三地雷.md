---
type: lesson
source: claude-code-projects
專案: 大量圖資轉換工具
嚴重度: 高（兩個地雷會「回報成功但成果是壞的」）
updated: 2026-07-29
source_office: TN
deidentified: true
---

# PyQGIS 出圖進程三地雷（兩個會回報「成功」）

> PyQGIS 批次出圖最危險的不是崩潰——崩潰你會發現。
> **危險的是「圖出來了、程式說成功了、但內容是壞的」。** 以下三個地雷都實際踩過。

## 地雷 1：openpyxl 不可在 PyQGIS 出圖進程內使用（硬崩潰）

### 症狀
大量圖磚（GDAL）處理後，`openpyxl` 建立 Workbook 時**存取違例硬崩潰**
（用 `faulthandler` 才看得到真正位置）。

### 原因
`openpyxl` 依賴 lxml，**lxml 與 GDAL 共用 libxml2**。
大量 GDAL 操作後 libxml2 的全域狀態損毀，此時任何 lxml 呼叫都可能炸。

### 解法
**把 xlsx 產製移出出圖進程**：
- 出圖迴圈中只寫 **CSV**
- xlsx 交由**獨立乾淨子進程**（`csv_to_xlsx.py`）產生

`.qgz` 不受影響（`project.write` 走 Qt XML，非 libxml2）。

### 通則
> **同一進程內混用 GDAL 與 lxml 系套件（openpyxl／python-docx／python-pptx 等）是地雷。**
> 需要兩者時，用子進程隔離。

---

## 地雷 2：桌面 QGIS 開著同一案子 → 鎖 gpkg／.qgz（★會回報成功）

### 症狀
- 主題色**整片空白**，但紅框／灰線可能正常
- **4 張圖都回報「成功」**
- log 裡只有一行不起眼的 `unable to open database file`

### 原因
桌面版 QGIS 開著同一案的 `gpkg`／`.qgz` 時，**SQLite 鎖衝突**讓算圖讀不到要素。
讀不到要素 ≠ 出圖失敗，所以引擎照樣回報成功。

### 解法
- **關掉桌面 QGIS 再跑**（最簡單）
- 或用 `--mem`：向量層 materialize 成記憶體層算圖，**免疫鎖**
  （記憶體層不入 `.qgz`，需搭配 `--no-qgz`）

---

## 地雷 3：桌面 QGIS 鎖住底圖 tif（★比地雷 2 更陰，會弄壞既有檔）

2026-07-29 實踩。

### 症狀
- 警告只有一行：「底圖下載失敗：Deleting … Permission denied」
- **圖照出、但底圖整片空白**
- **而且既有 tif 會被弄壞成無 geotransform**
  （`gdalinfo` 看 Corner Coordinates 變成 `0,0 / 1280,1024` 就是壞了）

### 原因
使用者開著同案 `.qgz` 時 `底圖\*.tif` 被鎖 → `build_basemap` 刪不掉舊檔 →
半途寫入把原檔弄壞。

### 解法（不必打斷使用者的 QGIS）
| 旗標 | 行為 |
|---|---|
| `--basemap-dir=<新資料夾>` | tif 改寫他處（圖磚快取仍共用原處） |
| `--reuse-basemap` | 沿用既有 tif，**會驗涵蓋範圍**；不足或壞掉照常重建（不拿錯範圍充數） |

---

## 三個地雷的共同教訓

1. **「回報成功」不等於成果正確。** 出圖類工作必須有**成果驗證**（開圖看、或程式檢查
   要素數／涵蓋範圍／geotransform），不能只看 exit code。
   → 呼應 案件建入知識庫-AI標準作業與判斷準則「驗證勝於信任」。
2. **檔案鎖是 Windows 桌面工具＋批次腳本並存時的頭號隱形殺手**，
   而且它的錯誤訊息通常只有一行、不顯眼。**跑批次前先確認沒人開著同一份檔。**
3. **QGIS returncode 豁免要收斂範圍**：引擎對 QGIS 的 `5`／`0xC0000005` returncode 有豁免
   （QGIS 正常結束也會回這些），但豁免**只給出圖步驟**；抽取／總覽步驟崩潰時
   **必須驗產物剛寫出才放行**，否則會把崩潰當成功。

---
相關：大量圖資轉換工具、地籍出圖產線引擎側操作與閘門、PyQGIS 批次出圖而非 QGIS MCP 逐張、使用 QGIS 內建 Python 避免 GDAL 環境衝突、_工程教訓總表
