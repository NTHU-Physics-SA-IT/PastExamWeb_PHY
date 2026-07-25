# Umami 截圖自動化

本專案透過 GitHub Actions 每日擷取 Umami 公開分享頁面的 Overview 統計卡片與主要圖表，分別產生明亮及深色模式圖片。自動化只支援匿名可讀的公開 Share URL，不會保存管理員帳號、密碼、Cookie、storage state 或 API token。

## 啟用方式

1. 在 Umami 後台為清大物理考古系統建立只讀的公開分享連結。
2. 以未登入或無痕瀏覽器開啟該連結，確認不會導向登入頁。
3. 確認公開頁面不顯示管理員帳號、Email、訪客 IP、敏感 query string、內部 hostname 或不適合公開的頁面路徑。
4. 到 GitHub repository：

   ```text
   Settings
   → Secrets and variables
   → Actions
   → New repository secret
   ```

5. 建立 repository secret：

   ```text
   UMAMI_SHARE_URL
   ```

6. 從 Actions 頁面手動執行 `Update Umami dashboard screenshots`。沒有設定 secret 時，workflow 會安全跳過，不會產生假圖片。

請勿將 Share URL、管理員帳密、Website ID、API token 或其他敏感資料寫入 workflow、README、issue、commit 或 Action logs。

GitHub 的 `schedule` 與 `workflow_dispatch` 事件只會在 workflow 檔案存在於 default branch 時生效。因此，本功能分支只負責準備與審查自動化；未來經正常 Pull Request 合併後，才能從 Actions 頁面首次手動執行及啟用每日排程。

## 排程與輸出

- 排程：每日 `23:30 UTC`，即台灣時間隔日 `07:30`。
- 手動執行：支援 `workflow_dispatch`。
- 不會因一般 push 自動執行。
- 擷取區間：最近 90 天。
- 固定 viewport：`1600 × 1400`，device scale factor 為 2。
- 截圖只保留 Overview 統計卡片與主要圖表，並隱藏導覽列及帳號相關控制項；不會把完整頁面或診斷 HTML 上傳為 artifact。
- 圖片採用無損 PNG 壓縮，不降低文字解析度。
- 輸出 branch：`analytics-assets`。
- Branch 根目錄檔案：

  ```text
  umami-overview-light.png
  umami-overview-dark.png
  ```

第一次成功執行時，workflow 會建立 orphan `analytics-assets` branch；後續只在圖片內容改變時建立正常 commit，不會 force push。

## README 圖片啟用

第一組真實圖片成功產生並確認可公開後，再用下列區塊取代 README 目前的 placeholder。網址依 canonical repository `NTHU-Physics-SA-IT/PastExamWeb_PHY` 組成：

```html
<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="
        https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-dark.png
      "
    />
    <source
      media="(prefers-color-scheme: light)"
      srcset="
        https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-light.png
      "
    />
    <img
      src="https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-light.png"
      alt="清大物理考古系統的 Umami 網站使用統計"
      width="820"
    />
  </picture>
</p>
```

在圖片 branch 尚未建立或首次截圖尚未成功前，不要啟用這段引用，以免 README 顯示破圖。
