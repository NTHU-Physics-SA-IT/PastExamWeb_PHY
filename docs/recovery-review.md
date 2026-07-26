# Recovery Review 本機舊資料檢視環境

Recovery Review 是與 clean-dev 完全隔離的本機只讀環境，用於檢視 2026-07-12 的資料庫備份與可配對的 MinIO 舊檔案。它不會把舊資料匯入 clean-dev，也不能用來新增、編輯、審核、下架或刪除內容。

## 使用方式

先由範例檔建立 Git ignored 的 `docker/recovery-review.env`，再依序執行：

```bash
scripts/recovery-review.sh preflight
scripts/recovery-review.sh prepare
scripts/recovery-review.sh start
scripts/recovery-review.sh status
```

網站入口為 `http://localhost:18082`，也可使用 `http://127.0.0.1:18082`。停止應用服務時執行：

```bash
scripts/recovery-review.sh stop
```

腳本刻意不提供無保護的資料銷毀命令。實際密碼只存在 mode 600 的本機環境檔，不得提交至 Git。

## 隔離與只讀保護

- Compose project、PostgreSQL database、MinIO bucket、Redis、volumes、network 與 host port 均為 Recovery Review 專用。
- 還原來源 dump 與原始 MinIO bucket 只作為來源，不由網站直接掛載。
- 後端在 `RECOVERY_REVIEW_MODE=true` 時，除登入、登出、heartbeat 與讀取請求外，所有內容變更請求都回傳 HTTP 403 與 `recovery_review_read_only`。
- 前端會顯示常駐的「Recovery Review｜2026-07-12 舊資料檢視｜只讀」橫幅，並隱藏內容變更操作。
- 缺少對應 MinIO object 的資料仍會保留，預覽時顯示明確的「檔案缺失」訊息。
