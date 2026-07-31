# TOST CLI

![License](https://img.shields.io/github/license/howar31/tost?style=flat-square)
![Made with Python](https://img.shields.io/badge/made%20with-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS-000000?style=flat-square&logo=apple)
![Conventional Commits](https://img.shields.io/badge/conventional%20commits-1.0.0-FE5196?style=flat-square&logo=conventionalcommits&logoColor=white)
![Last commit](https://img.shields.io/github/last-commit/howar31/tost?style=flat-square)
![Stars](https://img.shields.io/github/stars/howar31/tost?style=flat-square)

[English](README.md)

本機版 Tesla 訂單追蹤器。純 Python stdlib、零第三方依賴、無遙測。
只連 Tesla 官方 API（`auth.tesla.com`、`owner-api.teslamotors.com`、
`akamai-apigateway-vfx.tesla.com`），token 存 macOS Keychain，不落地明文。

需求：macOS（Keychain、launchd、osascript）、Python 3.9+。swift token
transport 需 Xcode Command Line Tools，未安裝時自動改用系統 curl。

## 使用

```sh
python3 tost.py auth              # 首次：瀏覽器登入 Tesla（見下方認證步驟）
python3 tost.py status            # 目前訂單摘要（現抓）
python3 tost.py status --cached   # 離線看快取
python3 tost.py timeline          # 歷次變化時間軸
python3 tost.py fetch             # 抓快照並顯示變化
python3 tost.py raw               # 完整原始 JSON
python3 tost.py export            # 摘要＋事件＋輪詢日誌（dashboard 資料來源）
python3 tost.py agent install     # 安裝 launchd 定時自動抓＋變化通知
                                  #（--interval 30 改為每 30 分鐘，預設 60）
python3 tost.py agent status      # 查看背景代理狀態
```

## 認證步驟

Tesla 自 2026-07 起只接受 `tesla://auth/callback` 作為跳轉位址，瀏覽器無法
跟隨此跳轉，需從 DevTools 取得授權碼：

1. 執行 `python3 tost.py auth`，程式會印出授權網址（不自動開瀏覽器）。
2. 開新分頁 → 先開 DevTools（Cmd+Option+I）→ Network → 勾 Preserve log
   → filter 輸入 `callback`。
3. 把授權網址貼進該分頁的網址列。已有 Tesla session 會立即跳轉（免登入）；
   否則完成登入（密碼 + MFA）。
4. 在 Network 清單找到 `tesla://auth/callback?code=...`（紅色/cancelled 的
   請求，或最後一個 `/authorize` 回應的 Location header），複製完整網址
   貼回終端機。

Token 交換經由 Apple TLS stack（`swift` 執行 `app/token_post.swift` 原始碼）
以通過 Tesla 的 TLS 指紋檢查；未安裝 Xcode CLT 時自動跳過 swift，備援依序
為系統 curl、Python urllib。

## 通知管道

變化通知發送到 `data/notify.json` 設定的管道（範本見 `notify.json.example`）。
各管道獨立、盡力而為，單一管道故障不影響其他管道與抓取本身。

支援：macOS 通知中心、iMessage、Discord DM、Slack、Email。Discord 與 Slack
經 [dscrd](https://github.com/howar31/dscrd) 與
[slk](https://github.com/howar31/slk) 發送——為 AI agent 設計、輸出精簡的
Discord / Slack CLI，需自行安裝與認證；兩者皆支援 `profile` 欄位固定發送
帳號，避免全域帳號切換影響發送身分。Email 經 `gws` CLI 發送。

### 選擇管道時的兩個限制

**自己傳給自己不會產生通知。** iMessage 與 Slack 自我 DM 都是如此：訊息從
你的帳號發給同一個帳號時，平台視為「已送出訊息在裝置間同步」而非「收到新
訊息」，不會跳橫幅通知，必須主動開啟 app 才看得到。這是平台機制，換成手機
號碼或其他自有位址也一樣。這類管道只適合當留底；要有實際推播，需選擇你是
真正收件方的管道（例如 bot 發給你的 DM，或 bot 發到頻道）。

**企業帳號有可見性風險。** 若 Email 或 Slack 管道使用的是所屬組織的帳號，
管理員通常可查看相關紀錄（如 Google Workspace 的 Email Log Search 中繼資料、
啟用 Vault 時的完整內容、已連結應用程式清單）。個人用途建議避開組織帳號。

### macOS 自動化權限

iMessage 管道需要自動化權限（首次發送會跳對話框）。背景排程與手動執行若使用
同一個 Python 直譯器路徑，屬同一個 TCC 主體，授權一次即涵蓋兩者。

## AI agent

repo 內附 agent skill（`skills/tost/`），教會 agent 查詢介面——JSON 契約、
exit code、解讀規則：

```sh
npx skills add https://github.com/howar31/tost
```

Claude Code 在本 repo 目錄內工作時會自動載入；其他 agent 可從
[AGENTS.md](AGENTS.md) 開始。

## 測試

```sh
python3 -m unittest discover tests
```

## 資料

全部在 `data/`（chmod 700、git 排除）：`latest.json` 最新快照、
`history.jsonl` 變化事件流、`archive/*.json.gz` 原始快照封存（內容有任何
差異時寫入，含被雜訊過濾的欄位——完整 audit trail）、`observations.jsonl`
每次抓取的輪詢日誌（時間＋內容雜湊＋對應封存檔，可區分「沒變化」與
「沒抓取」）、`logs/agent.log` 背景代理輸出。

## 授權

[MIT](LICENSE)
