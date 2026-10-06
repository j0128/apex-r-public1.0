# Apex-R

> ⚠️ **免責聲明**：本專案為個人研究與程式學習用途，**不構成任何投資建議**。回測結果不代表未來績效，
> 且含存活者偏差等限制；實際投資風險自負。


動能輪動策略（預設 Apex-R 4.0 RDyn-W）：ROC_120 / vol_20 風險調整動能、價 ≥ 200MA、Top10、月頻決策＋月內續抱，並依大盤 regime 混合 R0／R3 權重。

## 目錄

| 路徑 | 說明 |
|------|------|
| `shared/` | **唯一真實來源**：核心引擎、策略預設、委員會報告、宇宙建構 |
| `desktop/` | 本機每日報告、GUI、排程腳本、設定 (`config*.yaml`) |
| `mobile/` | Flet APK（`mobile/lib/` 是 `shared/` 的副本） |
| `colab/` | Colab 筆記本（`colab/modules/` 是 `shared/` 的副本） |
| `tests/` | pytest 單元測試 |

## 月度鎖定（重要規則）

每月月初換股日決定的**標的與權重會寫入檔案（`desktop/locked_books/`），該月任何日期查詢都不會變動**，包含價格更新、資料修正、改參數、更新宇宙都不影響；次月換股日才重新計算。
桌面版介面會顯示「🔒 本月持倉已鎖定」。僅在首次鎖定資料有誤等例外時，才用「🔒 重新鎖定本月」按鈕覆寫。

## Windows 啟動

雙擊 `啟動 Apex-R.bat`（或 `啟動 Apex-M.bat`）。腳本會自動找 Python、缺套件時自動 `pip install`，出錯時視窗會停住並顯示訊息。
需要 Python 3.10 以上（安裝時勾選 Add python.exe to PATH 與 tcl/tk）。若有打包好的 `Apex-R-4.0.exe` 放在 `desktop/`，則優先執行 exe。

## 開發

```bash
pip install -r desktop/requirements.txt pytest
python -m pytest tests          # 核心邏輯 + 副本同步檢查
```

### 修改 shared/ 後同步副本

```bash
python check_shared_sync.py --fix   # 或 Windows: .\sync_shared.ps1
python check_shared_sync.py         # 檢查（有漂移時 exit 1；測試也會檢查）
```

### 本機設定

複製 `desktop/.env.example` 為 `desktop/.env`，填入你自己的 `GMAIL_ADDRESS`（及需要時的應用程式密碼）；`.env` 已被 gitignore。
設定檔 `desktop/config*.yaml` 內的資金數字是**範例值**，請改成你自己的。
每日報告 (`desktop/report_*.txt`)、月度鎖定檔 (`desktop/locked_books/`) 含持倉資訊，已被 gitignore，請勿 commit。

## 取得 exe（不需安裝 Python）

GitHub → Actions → **Build Windows exe** → 最新一次執行 → 下載 artifact `Apex-R-4.0-windows`，解壓後雙擊 `Apex-R-4.0.exe`。
推送到 main 或 `desktop/`、`shared/` 有變動時會自動重新打包；也可在 Actions 頁面按 *Run workflow* 手動觸發。

## 授權

本專案以 [PolyForm Noncommercial License 1.0.0](LICENSE) 授權：**個人學習、研究、非商業用途可自由使用與修改；不得用於商業用途**（例如販售、納入付費產品或服務）。
商業使用請在本儲存庫開一個 Issue 聯絡作者洽談授權。

Required Notice: Copyright (c) 2026 j0128 (https://github.com/j0128)

## 手機版

`mobile/` 尚未跟上最新的桌面版功能（月度鎖定、新介面、績效曲線）；`mobile/lib/` 為較舊的核心副本。

## 資料來源與致謝

- 行情來自 Yahoo Finance（透過 `yfinance`），請遵守其使用條款。
