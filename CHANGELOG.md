# 更新紀錄（CHANGELOG）

每次對其他辦公室有影響的更新（規則、法規筆記、腳本、欄位規格、骨架範本），在最上方追加一筆。
各辦公室收到通知、`git pull` 後，先看這裡再決定要不要做事。

## 追加格式

```markdown
## YYYY-MM-DD 一句話標題（維護者辦公室代碼）

- **改了什麼**：（規則、法規筆記、腳本、範本、文件；一兩行即可）
- **各辦公室要做事嗎**：
  - TN：無／要（做什麼）
  - HC：無／要（做什麼）
  - TP：無／要（做什麼）
- **規則 ID**：
  - 新增：`XHC-3`、…
  - 修改：`NAT-5`（改了哪個欄位）
  - 廢止：`TNN-2`（由 `TNN-9` 取代）
  - 轉正：`XTP-1` → `LOCAL-TPE-4`
```

要點：

- 「各辦公室要做事嗎」一定要寫。需要重跑 `sync_to_vault.py` 才算要做事（規則或法規筆記有變動時幾乎都要）。
- 規則 ID 沒有變動就寫「無」，不要省略這一項。
- 修改既有已轉正規則時，註明對照的官方來源。
- 核心腳本或欄位規格有改，註明是否需要重裝 hook（`install_hooks.py`）或重跑 `pip install`。

---

## 2026-11-25 新增環評主管機關管轄分工規則與法規筆記（TN）

- **改了什麼**：新增法規筆記「環境影響評估法施行細則-第12條主管機關管轄分工-重點」（附附表一官方 PDF），新增 pending 規則兩條，判定環評由環境部或地方環保局審查。
- **各辦公室要做事嗎**：
  - TN：無
  - HC：無（可覆核）
  - TP：無（可覆核）
- **規則 ID**：
  - 新增：`XTN-41`、`XTN-42`

## 2026-11-24 防冒名轉正檢查＋正式 ID 編法寫進手冊（TN）

- **改了什麼**：`rule_check.py` 的 push 前檢查新增「冒名轉正」：新增正式規則，或改動既有正式規則的 `added_by`／`reviewed_by`／`reviewed_at`／`review_mode` 時，`reviewed_by` 必須等於本機 `office.yaml` 的辦公室代碼（只改內容不受限；CI 不做這項）。README 9.3 第 3 步、CLAUDE.md 補上正式 ID 編法（三位數條號、之 n 用 `-<n>`、項用 `-P<n>`、附表用 `-A<n>`）。
- **各辦公室要做事嗎**：`git pull` 即可。往後轉正請在自己的電腦 push，`reviewed_by` 填自己的代碼；配正式 ID 照 README 9.3 的表。

## 2026-11-23 TN 待覆核規則 40 條自行轉正（TN）

- **改了什麼**：
  - 規則：`rules/pending/TN/` 的 `XTN-1`～`XTN-40` 全部以自行轉正方式（`review_mode: self`、`reviewed_by: TN`、`reviewed_at: 2026-11-23`）複製到 `rules/national/` 並改配正式 ID；21 欄內容照原 pending 檔，只把「核對狀態」的「未覆核」改為「2026-11-23 TN 自行轉正（review_mode: self），每月抽查」，並把內文引用的 `XTN-` 編號換成新 ID。原 pending 檔保留，改 `status: deprecated`、`superseded_by` 填新 ID。
  - 欄位規格（`rules/_fields.yaml`）：`national_prefixes` 由總部新配 9 個前綴——`RRA`（農村再生條例 M0110017）、`RRD`（農村再生發展區計畫審核及管理監督辦法 M0110023）、`RCR`（農村社區土地重劃條例 D0060007）、`NSP`（國土計畫法 D0070230）、`NSPS`（一定規模以上或性質特殊土地申請使用許可認定標準 D0070312）、`NSPA`（國土計畫使用許可申請辦法 GL001691）、`NSPR`（國土計畫使用許可審議規則 D0070310）、`NSPO`（國土計畫使用許可核發後應循事項辦法 GL001690）、`NSPF`（國土保育費及影響費收取辦法 D0070311）。
  - 匯出：規則由 346 條增為 386 條（CSV、xlsx 的 `20_規則庫`、`90_規則狀態` 各多 40 列）。
  - 配號慣例：條號三位數補零；多條合併取第一條；`-A<n>`＝附表 n；`-P<n>`＝第 n 項（同條有兩條以上規則時才加）；`-<n>`＝之 n。
  - ⚠ `NSPS-`、`NSPA-`、`NSPR-`、`NSPO-`、`NSPF-` 共 20 條所依據的國土計畫法子法尚未施行，觸發條件與核對狀態原有的警示照舊保留。
- **各辦公室要做事嗎**：
  - TN：要。`git pull` → `sync_to_vault.py`。
  - HC：要。`git pull` → `sync_to_vault.py`。原本請 HC／TP 覆核 `XTN-1`～`XTN-40` 的事項取消（已自行轉正）；下游清單引用 `XTN-` 編號者，請改填新 ID。
  - TP：同 HC。
  - TN2：同 HC。
- **規則 ID**：
  - 新增：`LUR-A1-RR`、`RRA-017`、`RRD-004`～`RRD-A2-6`（8 條）、`RCR-006`～`RCR-018`（4 條）、`NSP-023`～`NSP-045`（6 條）、`NSPS-003`～`NSPS-008`（5 條）、`NSPA-003`～`NSPA-012`（4 條）、`NSPR-010`～`NSPR-044`（9 條）、`NSPO-002`、`NSPF-009`（共 40 條，全部見下表）
  - 轉正：

    | 原 ID | 新 ID | 原 ID | 新 ID | 原 ID | 新 ID | 原 ID | 新 ID |
    |---|---|---|---|---|---|---|---|
    | `XTN-1` | `LUR-A1-RR` | `XTN-11` | `RCR-006` | `XTN-21` | `NSPS-003` | `XTN-31` | `NSPR-014` |
    | `XTN-2` | `RRA-017` | `XTN-12` | `RCR-008` | `XTN-22` | `NSPS-003-A1` | `XTN-32` | `NSPR-015` |
    | `XTN-3` | `RRD-020` | `XTN-13` | `RCR-011` | `XTN-23` | `NSPS-003-A2` | `XTN-33` | `NSPR-018` |
    | `XTN-4` | `RRD-026` | `XTN-14` | `RCR-018` | `XTN-24` | `NSPS-003-A3` | `XTN-34` | `NSPR-021` |
    | `XTN-5` | `RRD-027` | `XTN-15` | `NSP-023` | `XTN-25` | `NSPS-008` | `XTN-35` | `NSPR-022` |
    | `XTN-6` | `RRD-030` | `XTN-16` | `NSP-045` | `XTN-26` | `NSPA-003` | `XTN-36` | `NSPR-030` |
    | `XTN-7` | `RRD-031` | `XTN-17` | `NSP-024` | `XTN-27` | `NSPA-006` | `XTN-37` | `NSPR-041` |
    | `XTN-8` | `RRD-031-1` | `XTN-18` | `NSP-024-P3` | `XTN-28` | `NSPA-009` | `XTN-38` | `NSPR-044` |
    | `XTN-9` | `RRD-A2-6` | `XTN-19` | `NSP-028` | `XTN-29` | `NSPA-012` | `XTN-39` | `NSPO-002` |
    | `XTN-10` | `RRD-004` | `XTN-20` | `NSP-032` | `XTN-30` | `NSPR-010` | `XTN-40` | `NSPF-009` |

## 2026-11-23 開放各辦公室自行轉正自己的規則（TN）

- **改了什麼**：
  - 規則欄位（`rules/_fields.yaml`）：新增 `review_mode`（`peer`＝他辦覆核、`self`＝自行轉正），有 `reviewed_by` 時必填；新增選填 `spot_checked_at`（抽查日期）、`spot_check_note`（抽查結果一句話），只限 `self` 規則。
  - `rule_check.py`：拿掉「`reviewed_by` 與 `added_by` 相同即擋」，改檢查 `review_mode` 一致性（同辦公室須 `self`、不同須 `peer`、`reviewed_by` 空白時 `review_mode` 也須空白；legacy 匯入規則免填）。本機 push、`--ci` 都適用。他辦公室 pending 資料夾仍不能新增、修改或刪除，只放行他辦覆核（`peer`）轉正的兩欄變動。
  - 匯出：xlsx 的 `90_規則狀態` 在 `reviewed_at` 後加 `review_mode`、`spot_checked_at` 兩欄。**CSV 與 `20_規則庫` 的 21 欄不變。**
  - CLAUDE.md、README 9.2～9.4 改寫轉正說明（含自行轉正 yaml 範例）。自行轉正每月抽查一部分回官方原文核對。
- **各辦公室要做事嗎**：
  - TN：要。push 後跑 `sync_to_vault.py`（匯出 xlsx 的 90 表多兩欄）。
  - HC：要。`git pull` → `sync_to_vault.py`（匯出 xlsx 的 90 表多兩欄）。hook 不必重裝（hook 只呼叫 `rule_check.py`，本次未改 `install_hooks.py`）。之後自行轉正須填 `reviewed_by`＝自己代碼、`review_mode: self`。
  - TP：同 HC。
  - TN2：同 HC。
- **規則 ID**：無（既有已轉正、非匯入規則中沒有填 `reviewed_by` 的，故無須補 `review_mode`）

## 2026-11-23 新增辦公室代碼 TN2（臺南第二辦公室）（TN）

- **改了什麼**：`offices.yaml` 新增 `TN2`（臺南第二辦公室）；CLAUDE.md、README 的辦公室列表補上 TN2。`rules/pending/TN2/` 由 TN2 第一次新增規則時自行建立（其他辦公室不能在別人的 pending 資料夾放檔，`rule_check` 會擋）。新規則暫用 ID 為 `XTN2-<流水號>`。TN2 與 TN 是不同辦公室，可以互相覆核轉正。
- **各辦公室要做事嗎**：
  - TN：無（`git pull` 即可）
  - HC：無（`git pull` 即可）
  - TP：無（`git pull` 即可）
  - TN2：要。照 README 第 2 節起建置，`office.yaml` 的 `office_code` 填 `TN2`。
- **規則 ID**：無

## 2026-11-22 國土計畫法筆記改標「施行中」（TN）

- **改了什麼**：法規筆記 `law_notes/國土計畫法-重點.md` 的 `legal_status` 由 `future_system` 改為 `effective`（全國法規資料庫無「尚未施行」標示，2026-11-20 查證）；`official_url` 改指全國法規資料庫；`applicability_condition` 改寫為依§45Ⅲ，功能分區圖公告後區域計畫法才停止適用。警示框文字同步修正。子法筆記維持「尚未施行」。
- **各辦公室要做事嗎**：
  - TN：無（維護者已同步）。
  - HC：要。`git pull` → `sync_to_vault.py`。
  - TP：同 HC。
- **規則 ID**：無

## 2026-11-20 國土子法 8 篇改標「尚未施行」；新增農村與國土相關規則 40 條待覆核（TN）

- **改了什麼**：
  - 法規筆記：國土計畫法 8 部子法改標 `future_system`，並加上「尚未施行」警示框。這 8 部是使用許可的審議規則、申請辦法、認定標準、核發後應循事項辦法、國土保育費及影響費收取辦法、適時檢討變更簡化辦法、重大公設認定標準、功能分區圖繪製作業辦法，2026-11-13 誤標為施行中。審議規則筆記另補 §18、§25 原文。判斷是否施行以全國法規資料庫的「生效狀態」為準；glrs 頁面可能沒有「尚未施行」的標示。
  - 規則：在 `rules/pending/TN/` 新增 40 條，逐條回官方原文撰寫。
    - 農村 14 條：非都市土地使用管制規則附表一的農村再生設施列、農村再生條例§17、農村再生發展區計畫審核及管理監督辦法、農村社區土地重劃條例。
    - 國土 26 條：國土計畫法、使用許可的認定標準、申請辦法、審議規則、核發後應循事項辦法、國土保育費及影響費收取辦法。
    - ⚠ XTN-21～XTN-40 所依據的子法尚未施行。這 20 條的觸發條件都寫明「本法規施行，且國土功能分區圖公告實施後」，核對狀態欄也加註警示。
- **各辦公室要做事嗎**：
  - TN：無。
  - HC：要。`git pull` → `sync_to_vault.py`；並對照官方原文覆核 `XTN-1`～`XTN-40`，通過的轉正。
  - TP：要。`git pull` → `sync_to_vault.py`；覆核與 HC 擇一即可。
- **規則 ID**：
  - 新增：`XTN-1`～`XTN-40`（pending，不進 exports）

## 2026-11-17 實務筆記：萃取深度訪談案件經驗＋鄉鎮案名去識別（TN）

- **改了什麼**：
  - 從臺南 9 件深度訪談案件萃取，新增 5 篇 `practice/`：接案先查土地歷次核准再決定程序、變更開發計畫實務-對照表或重辦的分流與節奏、太陽光電開發許可實務、臨海低窪光電審議重點、交通用地（停車場）變更編定實務。
  - 補進既有 3 篇：非都市土地變更編定通用實務（光電農變論述、多候選基地、非技術卡關）、山坡地變更編定通用實務（長照需求計算）、案件類型審查重點-變更編定與開發許可（地籍預割、延伸實務連結）。
  - 既有筆記中以鄉鎮稱呼的案件（例如「某鄉鎮案」）改為縣市層級或「某評估案」；公開地理資料與統計例子保留。
- **各辦公室要做事嗎**：
  - TN：要。`git pull` → `sync_to_vault.py`。
  - HC：要。`git pull` → `sync_to_vault.py` → `vault_audit.py`。
  - TP：同 HC。
- **規則 ID**：無

## 2026-11-17 新增共用實務筆記 practice_notes（TN）

- **改了什麼**：
  - 新增 `practice_notes/`：臺南既有經驗去識別化後共 66 篇＋索引——`lessons/` 工程與查證教訓 43 篇、`practice/` 辦案通用實務 9 篇、`review/` 審議判斷依循 14 篇。案名、業主、地段地號、案件代碼、收發文號都已改寫成匿名描述。
  - `sync_to_vault.py` 多同步一區：`practice_notes/` → vault `01_AI協作共用知識/55_共用實務筆記/_shared/`（`office.yaml` 的 `shared_dirs.practice_notes`，不填用此預設）。
  - 新增 `core/tools/notes_check.py`（去識別化禁字＋檔頭檢查），由 `rule_check.py` 呼叫，push 前 hook 與 GitHub Actions 都會跑。
  - 通知留言多一段「共用實務筆記有無變動」。
  - CLAUDE.md 新增「共用實務筆記」一節（去識別化標準）；README 新增 9.5；vault 範本加 `55_共用實務筆記/`。
- **各辦公室要做事嗎**：
  - TN：要。`git pull` → `sync_to_vault.py`；臺南原本的 66 篇原檔改由同步副本取代（另依切換步驟處理，見總部說明）。
  - HC：要。`git pull` → `sync_to_vault.py`（會新建 `55_共用實務筆記/_shared/`）→ `vault_audit.py`。hook 不用重裝。
  - TP：同 HC。
- **規則 ID**：無

## 2026-11-17 法規筆記索引加上「同步副本」公告（TN）

- **改了什麼**：`law_notes/_核心法規全文-索引.md` 頂端加一段公告，說明法規重點筆記自 2026-11-17 起只在本 repo 維護、vault 內為同步副本；`updated` 改為 2026-11-17。筆記內容沒有變動。
- **各辦公室要做事嗎**：
  - TN：無（切換時的首次同步會一併帶入）
  - HC：無（首次建置時會一併帶入；已建置者下次同步即可）
  - TP：同 HC
- **規則 ID**：無

## 2026-11-17 首次發布（TN）

- **改了什麼**：
  - 法令檢核規則庫改為文字正本：現有 346 條規則由 xlsx 轉為 `rules/` 內一條一檔的 yaml（全部視為已轉正，`legacy_import: true`）；`exports/` 由腳本匯出，與原 CSV 逐格相同。
  - 核心法規重點筆記 87 個檔（`law_notes/`，含附表原檔）。
  - 核心腳本：`rulebook_export.py`（匯出）、`rule_check.py`（push 前與 CI 檢查）、`install_hooks.py`（裝 pre-push hook）、`init_vault.py`（建 vault 骨架）、`sync_to_vault.py`（同步規則與法規筆記進 vault 唯讀區）、`vault_audit.py`（vault 健檢）。
  - 欄位規格 `core/knowledge_schema.yaml`、vault 骨架範本 `templates/vault/`、建置手冊 README、治理說明 CLAUDE.md。
  - GitHub Actions：push／PR 自動跑 `rule_check --ci`、`rulebook_export --check`、pytest。
- **各辦公室要做事嗎**：
  - TN：改用本 repo 為規則正本；原 xlsx 改為匯出的唯讀檔，之後不再手改。
  - HC：照 README 建置（clone、填 `office.yaml`、建 vault、首次同步、裝 hook）。
  - TP：同 HC。
- **規則 ID**：
  - 新增：無（346 條皆為既有規則轉入）
  - 修改：無
  - 廢止：無
