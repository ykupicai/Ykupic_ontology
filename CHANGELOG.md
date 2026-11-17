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
