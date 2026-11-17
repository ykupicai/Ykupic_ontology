---
type: lesson
source: claude-code-projects
updated: 2026-09-20
source_office: TN
deidentified: true
---

# sieve+polygonize產生的破碎多邊形，疊圖前別對它做 union_all()

## 情境
臺南市農再案表4-20（閒置公有土地），要把「公有土地」（23.5萬筆宗地）與「國土利用調查090501未使用地」（62,273個小多邊形，來自WMTS柵格sieve+polygonize後向量化）做疊圖分析。

## 踩坑
先用 `weili_c.geometry.union_all()` 把62,273個未使用地小多邊形合併成一個，再與公有土地做 `gpd.overlay(...)`。這行程序跑了超過4小時還沒完成——process本身**沒有當機**（CPU持續在增長，`Get-Process` 看得到），但已經遠超合理時間（同規模的表4-15疊圖，130萬筆宗地 vs 1個社區聯集多邊形，只花40分鐘）。

診斷後確認瓶頸是 `union_all()` 本身：對大量破碎、來自柵格向量化（邊界鋸齒、形狀複雜）的小多邊形做全域幾何合併，是已知的效能地雷，複雜度遠差於一般的疊圖運算。

## 正確做法
**破碎多邊形要疊圖時，不要對它做 union_all() 或 dissolve()，直接用空間索引做候選預篩選再 overlay：**
```python
hits = set()
for geom in fragmented_layer.geometry:
    hits.update(other_layer.sindex.query(geom, predicate="intersects"))
candidates = other_layer.iloc[sorted(hits)]
inter = gpd.overlay(candidates, fragmented_layer, how="intersection")
```
改用這個寫法後，同一份資料 7 分鐘完成（原本 4 小時以上）。

## 判斷準則
看到「疊圖前先 dissolve/union_all 縮小要素數量」這個常見效能優化手法時，先確認來源圖層是否為**柵格向量化產物**（sieve+polygonize、WMTS分類等）——這類圖層形狀複雜、數量龐大但個別面積小，union 反而是效能反指標；來源是行政區界、社區邊界這種**少量、形狀相對單純**的多邊形時，union_all 才是合理的優化。

## 相關
[[點位清單圖資範圍需空間驗證不能依路徑判斷]]（同案例踩過的另一個坑）
