# Ykupic_ontology 建置手冊

給新竹（HC）、台北（TP）維護者照做。Windows／PowerShell 為主，每個步驟的指令都可直接複製。

## 1. 這是什麼

- 臺南、新竹、台北三個辦公室共用的**私有** repo：法令檢核規則庫（文字正本）、核心法規重點筆記、核心腳本、vault 骨架範本。
- 做完這份手冊，你會有：自己辦公室的本地知識庫（vault，健檢 0 錯誤）、能新增規則並在 push 前自動檢查、能同步別人的更新。
- 另有 `practice_notes/`：三辦公室共用、**已去識別化**的實務經驗（工程教訓、辦案通用實務、審議判斷依循）。
- **案件資料不進這個 repo**，只留在各辦公室自己的 vault；案件經驗要分享，去識別化後寫進 `practice_notes/`（見 9.5）。治理規則、誰可以改什麼，先讀 [CLAUDE.md](CLAUDE.md)。

所有指令都在 repo 根資料夾執行。

## 2. 事前準備

1. **GitHub 帳號**：沒有就註冊一個，把帳號名稱給總部（TN）維護者，由對方加你為協作者。
2. **接受協作邀請**：到信箱找 GitHub 的邀請信，按 Accept。
3. **設定通知**：開啟 repo 頁面 → 右上角 **Watch** → 選 **All activity**；再到 **Issues** 打開「規則庫更新通知」這個 issue，右側按 **Subscribe**。
   GitHub 本身不會為 push 寄信，所以 repo 設了自動機制：任何一邊 push 到 main 後，系統會在這個 issue 留言（誰推的、改了哪些規則），你就會收到 email。這是你知道「別人更新了」的主要管道；檢查沒過的 push 也會在這裡留言示警。
   另外確認 GitHub 的 **Settings → Notifications** 有勾選 Email。
4. **安裝 Git 與 Python 3.12 以上**（PowerShell）：

   ```powershell
   winget install Git.Git
   winget install Python.Python.3.12
   ```

   裝完**關掉 PowerShell 重開**，確認版本：

   ```powershell
   git --version
   python --version
   ```

5. **設定 git 使用者**（commit 會記這個名字，建議用「辦公室代碼＋姓名」方便辨識，例如 `HC <你的姓名>`）：

   ```powershell
   git config --global user.name "HC <你的姓名>"
   git config --global user.email "你的信箱"
   ```

6. **中文檔名與長路徑**（規則檔、法規筆記有中文檔名）：

   ```powershell
   git config --global core.quotepath false
   git config --global core.longpaths true
   git config --global core.editor notepad
   git config --global pull.rebase false
   ```

   後兩行的用意：git 需要你輸入合併說明時改開記事本（預設的 Vim 新手出不來）；`git pull` 一律用合併方式。

   若系統要求，另以**系統管理員**身分開 PowerShell 執行一次（啟用 Windows 長路徑）：

   ```powershell
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
   ```

## 3. clone 到本機

**clone 到你電腦的本機磁碟（例如 `D:\`），不要 clone 到 NAS。** 原因：

- NAS（SMB）的檔案鎖與 git 的暫存檔機制處理不一致，容易出現 `.git` 鎖定錯誤、索引損毀。
- NAS 檔案擁有者與你的本機帳號不同，git 會以 dubious ownership 擋下。
- vault 在 NAS 沒關係，腳本會用 `office.yaml` 的路徑去讀寫它；repo 本身放本機即可。

```powershell
cd D:\
git clone https://github.com/ykupicai/Ykupic_ontology.git Ykupic_ontology
cd D:\Ykupic_ontology
```

第一次 clone 會要求登入 GitHub（跳出瀏覽器授權）。要先接受總部寄出的協作邀請才能 clone。

## 4. 安裝套件

```powershell
python -m pip install -r requirements.txt
```

套件只有 `pyyaml`、`openpyxl`、`pytest`。**不要**在其他軟體內建的 Python（例如 QGIS 附的 Python）上執行 pip，會污染那套軟體的環境。

跑一次測試確認環境正常：

```powershell
python -B -X utf8 -m pytest core/tests -q -p no:cacheprovider
```

## 5. 填 office.yaml

```powershell
Copy-Item office.example.yaml office.yaml
notepad office.yaml
```

要填的：

| 欄位 | 填什麼 |
|---|---|
| `office_code` | 你的辦公室代碼：新竹填 `HC`、台北填 `TP`（須存在於 `offices.yaml`） |
| `office_name` | 例如 `新竹辦公室` |
| `vault_root` | 你要放 vault 的資料夾，NAS 用正斜線，例如 `//<NAS>/<共享名>/知識庫/<vault 資料夾>` |
| `restricted_dir_names` | 保持預設 `[30_committees]` |
| `shared_dirs`、`extra_export_targets` | 沒特殊需求就不用動 |

注意：

- 路徑一律用**正斜線**（`//<NAS>/...`），Python 吃不了反斜線 UNC。
- `office.yaml` 含本地路徑，已列入 `.gitignore`，**不要 commit**。
- 資料夾不存在沒關係，下一步建 vault 時會建立；但上層資料夾要先存在、你要有寫入權。

## 6. 建 vault（先 dry-run）

先看會建什麼，不實際寫入：

```powershell
python -X utf8 core/tools/init_vault.py --dry-run
```

確認清單合理後正式建立：

```powershell
python -X utf8 core/tools/init_vault.py
```

- 依 `templates/vault/` 建出各層資料夾與各層 `CLAUDE.md`、`00_Index/知識庫總入口.md`；`{{OFFICE_CODE}}`、`{{OFFICE_NAME}}` 會替換成你的設定。
- **已存在的檔不會被覆蓋**，重跑是安全的。
- 建完用 Obsidian 開啟 vault 資料夾，先把 vault 根的 `CLAUDE.md` 與 `00_Index/知識庫總入口.md` 讀一遍。

## 7. 第一次同步與健檢

把規則匯出與法規筆記同步進你的 vault 唯讀區：

```powershell
python -X utf8 core/tools/sync_to_vault.py
python -X utf8 core/tools/vault_audit.py
```

- 同步後 vault 內會出現 `03_案件經驗知識層/70_法規索引/_shared/`、`71_核心法規全文/_shared/` 與 `01_AI協作共用知識/55_共用實務筆記/_shared/`。這三個資料夾**每次整個覆蓋**。
- 健檢要看到 **格式錯誤 0** 才算建置完成。有錯誤先看訊息指出的檔案，常見是 frontmatter 欄位缺漏或格式不對。

## 8. 裝 push 前檢查

```powershell
python -X utf8 core/tools/install_hooks.py
```

之後每次 `git push` 前會自動跑規則檢查，沒過就擋下、不能 push。每台電腦都要各裝一次（hook 不隨 repo 同步）。
repo 另有 GitHub Actions，在每次 push 後重跑同一組檢查；跳過本機檢查的 push 也會被發現。

## 9. 日常操作

### 9.1 收到更新通知後

```powershell
cd D:\Ykupic_ontology
git pull
python -X utf8 core/tools/sync_to_vault.py
python -X utf8 core/tools/vault_audit.py
```

先看 `CHANGELOG.md` 最上面一筆，確認你的辦公室要不要另外做事。

- 同步若**中止**並列出檔案，代表有人在 vault 的共用區裡新增或改了東西（那些改動不在 repo 裡，同步會蓋掉）。照訊息把內容移到 `_local/` 或改進 repo 後再同步；確定不要的才加 `--force`（舊內容會先備份）。
- 健檢若示警「vault 落後於 repo」，表示 pull 了但還沒同步，跑一次 `sync_to_vault.py` 即可。

### 9.2 新增一條規則（範例：新竹新增 `XHC-1`）

原則：**官方原文 → 法規重點筆記 → 規則檔**。

1. **讀官方原文**：到官方法規資料庫（全國法規資料庫等，清單見 [CLAUDE.md](CLAUDE.md)）找到條文，整份下載到本機逐點讀。第三方彙編網站不能當來源。
2. **補法規重點筆記**：到 `law_notes/` 找該法的筆記，沒有就新增一個，更新對應條文重點與官方網址。
3. **新增規則檔**：從範本複製到自己辦公室的 pending 資料夾，檔名等於規則 ID：

   ```powershell
   Copy-Item rules/_template.yaml rules/pending/HC/XHC-1.yaml
   notepad rules/pending/HC/XHC-1.yaml
   ```

   - 逐欄填寫（檔頭的 `#` 註解不必刪，跑匯出時會自動整理）；21 個欄位的順序不可改，沒有內容寫「—」。欄位定義與 enum 見 `rules/_fields.yaml`。
   - `source_url` 要填到完整網址（範本裡的 `pcode=` 後面是空的，不補會被檢查擋下）。
   - 可以打開同類的既有規則（`rules/national/`、`rules/local/<縣市代碼>/`）參考寫法，但**不要直接複製既有規則檔**：既有規則帶著 `legacy_import: true` 與 `added_by: TN`，會被檢查擋下。
   - 擴充欄位：`status: active`、`added_by: HC`（自己的辦公室代碼）、`source_url`（官方網址，必填，網域須在白名單內）、`legacy_import: false`；`reviewed_by`、`reviewed_at` 留 `null`（轉正時才由覆核辦公室填）。
   - 規則 ID 為 `XHC-1`，下一條用 `XHC-2`，依序流水編號。

4. **在 `CHANGELOG.md` 追加一筆**（格式見該檔），規則 ID 欄寫「新增：`XHC-1`」。
5. **匯出、檢查、提交、推送**：

   ```powershell
   git pull
   python -X utf8 core/tools/rulebook_export.py
   python -X utf8 core/tools/rule_check.py
   git status
   git add rules exports law_notes CHANGELOG.md
   git commit -m "新增規則 XHC-1（來源：<法規名稱與條號>）"
   git push
   ```

   先 `git pull` 是為了拿到別人剛推的內容，減少推送被拒。
6. push 成功後，另外兩個辦公室會收到通知（見第 2 節第 3 步），其中一邊會覆核。

### 9.3 覆核並轉正另一辦公室的規則

例如台北覆核新竹的 `XHC-1`（**自己加的規則不能自己轉正**）：

1. `git pull` 取得最新內容。
2. **對過官方原文**：打開規則檔的 `source_url`，逐項核對條文、條號、門檻，確認一致。
3. **複製**（不是搬移）到 `rules/national/`（中央法規）或 `rules/local/<縣市代碼>/`（地方規定），並**改配正式 ID**：中央法規用 `rules/_fields.yaml` 的 `national_prefixes` 對照表裡該法規的前綴（例如管制規則用 `LUR-`），地方規定用同檔的縣市代碼前綴。表裡沒有的新法規或縣市，請總部配號，不要自創（自創的前綴會被檢查擋下）。檔名等於新 ID：

   ```powershell
   Copy-Item rules/pending/HC/XHC-1.yaml rules/national/<新ID>.yaml
   ```

4. 編輯**新檔**：
   - `rule_id` 改為新 ID；
   - `added_by` 保留原辦公室（`HC`），不要改成自己；
   - 填 `reviewed_by: TP`、`reviewed_at: "YYYY-MM-DD"`（覆核日期）；
   - `source_url` 必須有值；`legacy_import: false`。
5. 編輯**原檔** `rules/pending/HC/XHC-1.yaml`：**只改兩處**——`status: active` 改成 `status: deprecated`、`superseded_by` 填新 ID。其他欄位一字不動，檔案也不刪，讓引用過 `XHC-1` 的清單查得到。
   （本機檢查會擋下對其他辦公室 pending 檔的修改；只有「只改這兩欄、而且新規則的 `reviewed_by` 是你、`added_by` 是原辦公室」才放行。多改任何一欄都會被擋。）
6. 在 `CHANGELOG.md` 寫「轉正：`XHC-1` → `<新ID>`」，再照 9.2 第 5 步匯出、檢查、提交（`git add rules exports CHANGELOG.md`）、推送。

### 9.4 檢查沒過怎麼辦

`rule_check.py` 會逐項列出哪個檔、哪一項沒過。常見原因與處理：

| 訊息類型 | 處理 |
|---|---|
| 格式錯、欄位缺、enum 非法 | 對照 `rules/_fields.yaml` 補齊或改正 |
| ID 不合格式、重複、檔名不等於 ID | 改 ID 或檔名；ID 全 repo 唯一 |
| pending 資料夾與 ID 前綴不符 | HC 的規則必須在 `rules/pending/HC/` 且 ID 是 `XHC-` 開頭 |
| 缺 `source_url` 或網域不在白名單 | 改填官方資料庫網址；不接受第三方彙編站 |
| 已轉正規則被刪除 | 不能刪；要廢止改 `status: deprecated` 並填 `superseded_by` |
| 轉正時覆核者等於新增者 | 換另一個辦公室覆核 |
| exports 未同步 | 重跑 `rulebook_export.py` 再 `git add exports` |
| 修改了其他辦公室的 pending | 還原那些檔：`git restore <檔案>` |
| `禁字：…`、`repo 外連結`、`frontmatter`（practice_notes） | 照訊息的「修法」改寫；標準見 [CLAUDE.md](CLAUDE.md)「共用實務筆記」一節 |

**不要用 `git push --no-verify` 跳過檢查**，也**不要在 GitHub 網頁上直接改檔**（網頁編輯不會跑本機檢查）。GitHub Actions 會在 push 後再跑一次，失敗會在「規則庫更新通知」issue 留言示警，三邊都看得到。

### 9.5 新增或修改共用實務筆記（`practice_notes/`）

適合放：跨案歸納出來、別的辦公室也用得上的做法與教訓。不適合放：單一案件的紀錄、委員資料、報價合約。

1. 依內容放子資料夾：`lessons/`（工程、查證教訓）、`practice/`（辦案通用實務）、`review/`（審議判斷依循）。
2. 檔頭至少要有：

   ```yaml
   ---
   type: lesson
   source_office: HC
   deidentified: true
   updated: 2026-11-20
   ---
   ```

3. **去識別化**：案名、業主、地段地號、案件代碼、收發文號、委員姓名、金額、內網路徑都不能出現，改寫成「新竹某廠房增建案」「某段某地號」。
   要引用已公告的解釋函，把文號原樣列進檔頭 `allow_terms:` 清單。`[[連結]]` 只能連 `practice_notes/`、`law_notes/` 內的筆記。完整標準見 [CLAUDE.md](CLAUDE.md)。
4. 先自己檢查，再提交：

   ```powershell
   python -X utf8 core/tools/notes_check.py
   git add practice_notes CHANGELOG.md
   git commit -m "新增實務筆記：<標題>"
   git push
   ```

   不需要另一辦公室覆核；push 前 hook 與 GitHub Actions 會再檢查一次。檢查只擋得住明顯的格式，**描述性的可辨識資訊（例如「某縣唯一的太空中心案」）要自己把關**——push 後要從 git 歷史清掉很難。
5. 想修改別的辦公室寫的實務筆記可以直接改，CHANGELOG 寫清楚改了什麼。

## 10. 常見問題

**`git push` 被拒（rejected / fetch first）**
代表別人剛推了新內容。先拉下來再推：

```powershell
git pull
python -X utf8 core/tools/rulebook_export.py
python -X utf8 core/tools/rule_check.py
git add rules exports
git commit -m "合併後重產匯出"
git push
```

`git pull` 若跳出記事本要你寫合併說明，直接存檔關閉即可。重跑匯出那兩行是為了確保合併後的匯出檔與規則一致；若 `git status` 顯示沒有變動，就略過 `git add`／`git commit`，直接 `git push`。

**`git pull` 出現衝突（conflict）**
多半是兩邊改了同一個檔。不要慌也不要硬覆蓋：

```powershell
git status
```

打開標示衝突的檔，找 `<<<<<<<`、`=======`、`>>>>>>>` 三種標記，和對方確認要留哪一邊後手動整理、刪掉標記，再：

```powershell
git add <檔案>
git commit
```

`exports/` 衝突時（兩邊同時轉正或修改規則時常見，xlsx 一定無法自動合併），不要手動合併：先解決 `rules/` 的衝突，再重跑 `rulebook_export.py` 重新產生，然後 `git add rules exports`、`git commit`。不確定就先找總部，不要 `git reset --hard`。

**檢查擋下，錯誤看不懂**
把 `rule_check.py` 的完整輸出貼給總部維護者，或在 repo 資料夾啟動 Claude Code 請它協助判讀（它會讀 `CLAUDE.md` 的規則）。

**同步後 Obsidian 沒更新**
Obsidian 有時沒偵測到外部檔案異動。先確認 `sync_to_vault.py` 有顯示複製了檔案；再關掉 vault 重新開啟，或執行命令面板的「重新載入應用程式而不儲存」。仍沒出現時檢查 `office.yaml` 的 `vault_root` 是否指到你開著的那個 vault。

**可以直接在 vault 的 `_shared/` 裡改東西嗎？**
**不行。** `_shared/` 每次同步整個覆蓋，改了就消失，也不會傳給別人。要改規則、共用法規筆記或實務筆記，改本 repo 的 `rules/`、`law_notes/`、`practice_notes/` 再 push；本辦公室自己的補充放 `_local/`。

**`office.yaml` 不小心 commit 了**
先停下來，不要 push；已 push 就立刻通知總部（內含本地路徑）。

**要改核心腳本或欄位規格**
約定只由總部改。請開 issue 或另開分支給總部看過再併入。

**更多環境問題**（中文路徑亂碼、NAS 路徑寫法、PowerShell 與 CMD 的差異）
- 一律用 PowerShell，不要用 CMD；NAS 路徑在 Python 與 git 裡用正斜線 UNC（`//<NAS>/<共享名>/...`）。
- 中文檔名在 Bash 顯示亂碼時改用 PowerShell。
