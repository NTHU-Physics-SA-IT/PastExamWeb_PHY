<div align="center">
  <img
    src="./frontend/public/physics-symbol.png"
    alt="清大物理考古系統標誌"
    width="180"
  />
  <h1>清大物理考古系統</h1>
  <p>整理與查詢物理系課程的歷屆考題、解答與參考資料，並支援投稿、審核與管理流程。</p>
  <a href="https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/actions/workflows/main.yml"><img alt="CI/CD Pipeline" src="https://img.shields.io/github/actions/workflow/status/NTHU-Physics-SA-IT/PastExamWeb_PHY/main.yml?label=CI%2FCD%20Pipeline"></a>
</div>

## 功能

- 依課程分類與課程瀏覽資料，並依學期、授課教師、考試類型及是否附解答篩選考古題。
- 線上預覽及下載考古題 PDF，支援考古題留言、按讚、置頂與留言回報。
- 登入使用者可投稿考古題、申請新增課程，並追蹤個人投稿與審核狀態。
- 管理員可處理投稿與課程申請，並管理課程分類、課程、公告、使用者、各類回報及垃圾桶。
- 提供站內公告、個人通知、系統問題回報，以及考古題與使用狀況統計。
- 響應式操作介面，支援明暗主題、字體大小與個人資料設定。

## 登入方式

目前試作版使用一般帳號密碼登入。清大校務身分驗證 OAuth 已提出申請，但尚未正式啟用；待申請與整合完成後，預計加入校務身分驗證登入方式。

專案仍保留後端 OAuth 設定及使用者相容欄位，供未來整合使用。現階段請勿將 OAuth 設定視為可用的登入入口。

## 使用狀況

下列統計圖片由 GitHub Actions 每日自動更新，資料來自 Umami，請參考 [Umami 截圖自動化](docs/umami-screenshot-automation.md)。

<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-dark.png"
    />
    <source
      media="(prefers-color-scheme: light)"
      srcset="https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-light.png"
    />
    <img
      src="https://raw.githubusercontent.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/analytics-assets/umami-overview-light.png"
      alt="清大物理考古系統的 Umami 網站使用統計"
      width="820"
    />
  </picture>
</p>

## 介面預覽

### 考古題搜尋與篩選

<p align="center">
  <img src="docs/screenshots/search.webp" alt="清大物理考古系統的課程與考古題搜尋介面" width="100%" />
</p>

### 文件預覽與討論

<p align="center">
  <img src="docs/screenshots/preview-forum.webp" alt="考古題文件預覽與討論介面" width="100%" />
</p>

## 技術架構

| 分類         | 技術                                |
| ------------ | ----------------------------------- |
| 前端         | Vue 3、Vite、PrimeVue、Tailwind CSS |
| 後端         | Python、FastAPI、SQLModel、Alembic  |
| 資料庫與快取 | PostgreSQL、Redis                   |
| 物件儲存     | MinIO（S3 相容）                    |
| 反向代理     | Nginx                               |
| 開發與 CI    | Docker Compose、GitHub Actions      |

## 本地開發

### 1. 取得專案

```bash
git clone https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY.git
cd PastExamWeb_PHY
```

### 2. 建立本地環境變數

範例值僅供本地開發；部署時請改用安全且獨立的密碼與金鑰。

```bash
cp docker/.env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

### 3. 建置並啟動開發環境

```bash
docker compose -f docker/docker-compose.dev.yml build
docker compose -f docker/docker-compose.dev.yml up -d
```

啟動後可使用：

- 網站與 API 反向代理：<http://localhost:8080>（API 位於 `/api/`）
- pgAdmin：<http://localhost:8081>
- MinIO S3 API：<http://localhost:9000>
- MinIO Console：<http://localhost:9001>

PostgreSQL、Redis、後端及前端開發伺服器預設在 Docker Compose 網路內互通，不另外暴露主機連接埠。可用下列指令查看狀態與停止服務：

```bash
docker compose -f docker/docker-compose.dev.yml ps
docker compose -f docker/docker-compose.dev.yml down
```

## 參與貢獻

1. 先查看目前 repository 的 [Issues](https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues)，確認是否已有相關討論。
2. Fork repository，並從最新的 `main` 建立內容明確的功能或修正 branch。
3. 完成修改與必要驗證後提交 commit。
4. 對本 repository 的 `main` 建立 Pull Request，說明修改內容與驗證結果。

## 專案沿革與致謝

本專案基於 [`NCTUCSUnion/pastexam`](https://github.com/NCTUCSUnion/pastexam) 修改與延伸，原專案依 MIT License 授權。現由清大物理系系學會資訊組依物理系需求持續開發與維護。

特別感謝 `gainsborouo（周廷威）`，相關實際貢獻仍完整保留於 Git commit 歷史中。

## 授權

本專案依 [MIT License](LICENSE) 授權，並保留上游專案的著作權聲明。

目前的更新與維護由清大物理系系學會資訊組持續進行。
