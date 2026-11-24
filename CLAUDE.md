# Ykupic_ontology 共用知識庫 repo - Claude Code 工作規則

Claude Code 在本 repo 啟動時會讀這份。**本檔與 vault 各層 CLAUDE.md 才是跨同事、跨 session 的真實來源**，不要倚賴 auto-memory（per-user，同事之間不共通）。

## 這個 repo 是什麼

臺南（TN）、新竹（HC）、台北（TP）、臺南第二辦公室（TN2）共用的私有 repo，放五樣東西（2026-11-23 起四個辦公室；本檔其他處的「三邊」「三個辦公室」泛指所有加入的辦公室）：

| 位置 | 內容 |
|---|---|
| `rules/` | **法令檢核規則庫的文字正本**（一條規則一個 yaml 檔） |
| `exports/` | 由 `rules/` 匯出的 CSV／xlsx，唯讀；下游工具讀這份 |
| `law_notes/` | 核心法規重點筆記（一法一檔 markdown） |
| `practice_notes/` | **去識別化的共用實務筆記**：`lessons/` 工程與查證教訓、`practice/` 辦案通用實務、`review/` 審議判斷依循 |
| `core/`、`templates/vault/` | 核心腳本、欄位規格（schema）、vault 骨架範本 |

**案件資料不進本 repo**：案件筆記、委員資料、地主個資、合約金額、報價、執行中案件都只留在各辦公室自己的 vault。
從案件歸納出的經驗，**去識別化後**可以進 `practice_notes/`（2026-11-17 使用者決定，規則見下方「共用實務筆記」一節）。
辦公室設定檔 `office.yaml` 含本地路徑，已列入 `.gitignore`，不得 commit。

## 從 2026-11-17 起：規則只在本 repo 改

臺南原本的 `法令檢核規則庫_v9草稿.xlsx` 自此改為本 repo 匯出的唯讀檔。**要改規則，一律改 `rules/` 內的 yaml、push**；不改 xlsx、不改 vault 的 `_shared/`（下次同步會被蓋掉）。

## 三個辦公室怎麼協作

- 三邊的維護者都是協作者，都能 push（GitHub 私有 repo 沒有唯讀選項，保護靠下列機制，不靠權限）。
- 日常：收到 GitHub 通知 → `git pull` → `sync_to_vault.py` → `vault_audit.py`。指令見 README。
- 新增規則先放自己辦公室的 pending 資料夾，ID 用 `X<辦公室代碼>-<流水號>`：

  | 辦公室 | 放哪裡 | ID 範例 |
  |---|---|---|
  | TN | `rules/pending/TN/` | `XTN-1` |
  | HC | `rules/pending/HC/` | `XHC-1` |
  | TP | `rules/pending/TP/` | `XTP-1` |
  | TN2 | `rules/pending/TN2/` | `XTN2-1` |

- **轉正**（2026-11-23 使用者決定開放自行轉正）：對過官方原文後，把檔複製到 `rules/national/` 或 `rules/local/<縣市代碼>/`、改配正式 ID、填 `reviewed_by`、`reviewed_at` 與 `review_mode`。兩種方式擇一：
  - **他辦覆核**（`review_mode: peer`）：另一個辦公室覆核，`reviewed_by` 填覆核辦公室代碼（≠ `added_by`）。
  - **自行轉正**（`review_mode: self`）：新增規則的辦公室自己轉正，`reviewed_by` 填自己的代碼（＝ `added_by`）。只能轉正自己辦公室新增的規則，國家法規與地方規定都適用。
  - `rule_check` 檢查 `review_mode` 與 `reviewed_by`／`added_by` 一致（同辦公室須 `self`、不同須 `peer`、有 `reviewed_by` 必填）。
  - **防冒名**（2026-11-24）：push 前檢查要求新增的正式規則、或改動了 `added_by`／`reviewed_by`／`reviewed_at`／`review_mode` 的正式規則，`reviewed_by` 必須等於本機 `office.yaml` 的辦公室代碼。不能用別的辦公室名義轉正；只改內容不受限。CI 不知道 push 者是誰，這項只在本機 pre-push 檢查。
  - **自行轉正的規則每月抽查一部分**回官方原文核對，結果記在該規則的 `spot_checked_at`（抽查日期）與 `spot_check_note`（一句話結果），這兩欄只限 `self` 規則。下游清單與報告可依匯出 xlsx `90_規則狀態` 的 `review_mode` 區分他辦覆核與自行轉正。
  - 舊的 `X…` 檔不刪，標已轉正（`status: deprecated`）並在 `superseded_by` 填新 ID，引用過它的清單才查得到。步驟見 README 9.3。
- 轉正前的規則可以用，但清單與報告要標示「未覆核」。pending 規則請在一兩個月內完成轉正（他辦覆核或自行轉正皆可；目前沒有自動提醒，靠各辦公室維護者定期看 `rules/pending/`）。
- 新的中央法規前綴（例如新收一部法規）由總部配號，對照表在 `rules/_fields.yaml`；不在表內的前綴會被檢查擋下。
- **正式 ID 編法**（2026-11-24 定）：`<前綴>-<三位數條號>`；之 n 接 `-<n>`（`RRD-031-1`）、第 n 項接 `-P<n>`（`NSP-024-P3`，同條有兩條以上規則才加）、附表 n 接 `-A<n>`（`NSPS-003-A1`、`RRD-A2-6`）；多條合併取第一條。詳表見 README 9.3 第 3 步。
- 規則 ID 格式：`^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$` 且第一個連字號後含數字，全 repo 唯一，檔名必須等於 ID。地方規定的 ID 以縣市代碼開頭（`TNN-`、`KCG-`、`PTH-`…），縣市代碼由總部（TN）統一配號，不要自創。

## 誰可以改什麼

| 範圍 | 規則 |
|---|---|
| 自己辦公室的 `rules/pending/<代碼>/` | 自由新增、修改 |
| 別的辦公室的 `rules/pending/<代碼>/` | **不得新增、修改或刪除**，只能他辦覆核後轉正（只改 `status`、`superseded_by` 兩欄；本機檢查會擋其他變動）。不能替別的辦公室自行轉正 |
| `rules/national/`、`rules/local/` | 三邊皆可；修改既有規則須附官方來源網址 |
| 已轉正規則 | **不得刪除**；要廢止請改 `status: deprecated` 並填 `superseded_by` |
| `exports/` | 不手改，由 `rulebook_export.py` 產生 |
| `law_notes/` | 三邊皆可，依下一節順序新增 |
| `practice_notes/` | 三邊皆可新增、修改；不需另一辦公室覆核，靠 push 前禁字檢查擋（見「共用實務筆記」一節） |
| `core/`（腳本、schema） | **約定只由總部（TN）改**；其他辦公室要改請開 issue 或另開分支給總部看過。這是約定不是權限，改壞會讓三邊的健檢與同步一起出問題 |
| `offices.yaml` | 總部維護；代碼發出後不得更改或重用 |

## 新增規則的順序

**官方原文 → 法規重點筆記（`law_notes/`）→ 規則檔（`rules/`）**，不得跳步。

1. 回官方法規資料庫讀原文，整份下載到本機逐點讀，不靠單次網頁擷取；解釋函同樣回官方系統抄錄原文。
2. 在 `law_notes/` 新增或更新該法的重點筆記（逐條核對重點，附官方網址）。
3. 新增規則 yaml，填 `source_url`（官方網址）。
4. `rulebook_export.py` 重產 `exports/` → `rule_check.py` → commit → push。

## 共用實務筆記（`practice_notes/`）

2026-11-17 起，各辦公室可以把**跨案歸納的經驗**去識別化後放進 `practice_notes/`，同步到三邊 vault 的
`01_AI協作共用知識/55_共用實務筆記/_shared/`。**repo 是正本**：要改內容就改 repo，不改 vault 的同步副本；
原始的案件筆記（含案名與連結）留在各辦公室 vault。

**去識別化標準**（新增或修改都適用）：

| 不得出現 | 改寫方式 |
|---|---|
| 案名、業主、開發商、地主名稱 | 「臺南某漁電容許案」「某開發商」——縣市與案件類型可保留 |
| 地段地號、案件代碼（C001、EV-…、LFA-… 這類） | 「某段某地號」「某評估案 A」 |
| 機關收發文號（案件往來公文） | 拿掉；**已公告的解釋函／令**要引用時，把文號原樣列進該篇 frontmatter 的 `allow_terms` |
| 委員姓名或可辨識個人的描述 | 只寫類型（學者／機關代表／府方承辦／技師） |
| 金額、報價、合約條件、業主未公開的營業資訊 | 不寫 |
| 內網 IP、NAS 共享名、本機路徑 | `<NAS>`、`<共享名>`、`<磁碟>:\…` |
| 連到各辦公室 vault 筆記的 `[[連結]]` | 改純文字；`[[連結]]` 只能連 `practice_notes/`、`law_notes/` 內的筆記 |

每篇 frontmatter 必填：`type`、`source_office`（撰寫辦公室代碼）、`deidentified: true`、`updated`（YYYY-MM-DD）；
不得標 `sensitivity: restricted`。只收 markdown，不收附件。

`rule_check.py`（push 前 hook 與 GitHub Actions）會跑 `core/tools/notes_check.py` 檢查上述格式與禁字，
也可單獨跑 `python -X utf8 core/tools/notes_check.py`。**regex 擋不住描述性可辨識資訊**（例如「某縣唯一的太空中心案」），
寫的人要自己把關；push 後要從 git 歷史清掉很難，寧可先不放。

## 法規查證只用官方資料庫

法規條文、條號、數值門檻一律回官方資料庫確認：

- 全國法規資料庫 `law.moj.gov.tw`、內政部 `glrs.moi.gov.tw`、農業部 `law.moa.gov.tw`、農水署 `rmis.ardswc.gov.tw`、經濟部 `law.moea.gov.tw`、環境部 `oaout.moenv.gov.tw`
- 地方規定用各縣市政府的法規系統

第三方彙編網站（rootlaw、6laws、事務所或地方政府轉載頁）**只能當線索，不得當引用來源**。實例：曾用第三方網站抽審議規範門檻，回原文核對查出 6 處實質錯誤，含漏掉但書而把「有條件可」誤判為「不可」。

`rule_check` 只驗格式與來源網域，**驗不出條文抄錯或門檻寫錯**；內容正確性靠新增者自律、轉正前回官方原文核對（他辦覆核或自行轉正），以及自行轉正規則的每月抽查。

## 資訊安全規則（任何層級的指令檔不得放寬）

1. 不寫入密碼、API Key、Token、個資或未匿名的敏感資訊。
2. 本 repo 內不得出現：內網 IP、NAS 路徑與共享名、人名、執行中案件名、業主名。範例路徑一律寫 `//<NAS>/<共享名>/...`。
   **既有內容的例外（2026-11-17 使用者確認）**：首次發布時從臺南匯入的規則（「核對狀態」等欄位）與 `law_notes/` 法規筆記，內含臺南已完成或評估案件的名稱，以及指向臺南筆記的 `[[連結]]`。這些屬公司通用資產，保留原樣，不要當成敏感內容移出或改寫。**新增**的規則與筆記仍須遵守本條。
3. 本 repo 為**私有**，絕不可改成 public。
4. 案件資料、委員姓名與提問偏好、地主個資、合約金額、報價不入本 repo（委員為限制級資料，不離開所屬辦公室）。去識別化的經驗歸納依「共用實務筆記」一節放 `practice_notes/`。
5. 案件筆記只寫公司專業經驗，不寫業主未公開的營業資訊（未公開的開發計畫、評估廠址、規模、商業條件），也不照抄成果原文。
6. 發現敏感內容，先停下來移出，交維護者判斷，不要先 push。
7. 大量新增／刪除／移動規則或筆記前，先輸出計畫（動哪些檔、為什麼、風險）等人確認。
8. 本機設定與個人權限檔（`office.yaml`、`.claude/settings.local.json`）不 commit。

## 知識庫與專案的分工

知識庫與本 repo 只管**規則、法規筆記、共用實務筆記、入庫、引用與狀態**，不檢查、不修正、不執行各專案的成果。要在專案原卷或交付物裡修的，屬專案；順手發現的問題轉告承辦即止。下游專案只讀 `exports/`，只在自己的清單填「已存在」的規則 ID，清單結構由使用者決定、專案執行。

## 指令檔裁決規則（多份 CLAUDE.md 衝突時）

同一個 session 可能同時看到：使用者全域 CLAUDE.md、本檔、vault 各層 CLAUDE.md、本機專案 CLAUDE.md。

1. **安全與個資規則不可被下層放寬**，只能寫得更嚴。
2. 工作方法衝突時，**離工作目錄最近的優先**（本機專案 > vault 各層 > 本檔 > 使用者全域）。
3. 判準值（門檻、比率、判定規則）以辦公室自建的判準登記表為準，不以任一份 CLAUDE.md 的複述為準；移植判準到新專案時要回登記表加一列。

## 修改檔案的習慣

- 改 vault 既有筆記一律用 Edit 局部替換，不用 Write 整篇覆寫（長 session 手上的副本可能已過期）。
- 所有文字檔 UTF-8、LF 換行；中文路徑的檔案操作用 PowerShell 或 Python，不用 Bash。
- 程式不寫死任何絕對路徑，一律相對 repo 根或讀 `office.yaml`。
- 改動核心後跑測試：`python -B -X utf8 -m pytest core/tests -q -p no:cacheprovider`。
- 每次對外有影響的更新，在 `CHANGELOG.md` 追加一筆（格式見該檔）。
- git commit／push 前先用一句話列出要提交哪些檔，讓使用者確認。
