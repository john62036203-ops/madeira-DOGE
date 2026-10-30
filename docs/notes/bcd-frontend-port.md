# BCD 新介面移植筆記（前端）

寫於 2026-10-30（台北時間 17:25）。這份是交接用的調查筆記，**還沒有任何程式碼被改**。

## 目標（使用者決定）

- 把 BCD 的新介面（Home / Library / Downloads 分頁、紫色主題、海報卡片、上方狀態列）移植到 fork。
- 方式：**做成可切換的介面**。原本的遊戲庫（Library）保留為預設，BCD 介面是一個選項，出問題可以隨時切回來。
- 這部分交給另一個 session 做；FF15 效能的 session 會繼續在 `exvs2` 上改 ntdll / x64-fast。
  **建議前端開新分支**（例如 `bcd-ui`），不要直接改 `exvs2`：兩邊同時推 `exvs2` 容易互相蓋掉，
  同一個 runner 的編譯也會互相取消（workflow 的 concurrency 是 ref + runner）。

## 來源

- BCD repo：https://github.com/thebcd69/bcd-games
- 調查時的 commit：`05e9f6f`（2026-10-29），BCD 版本 0.1.623 之後
- 介面檔案：`app/Madeira/BCD*`（194 個檔案，約 55,000 行；含子資料夾 `BCDContent/`、`BCDEpic/`、
  `BCDGOG/`、`BCDGameSetup/`、`BCDMidi/`、`BCDSaveBackups/`、`BCDSteamDLC/`）
- 入口：
  - `BCDFrontEnd.swift`：外殼（分頁、狀態、手把提示；直向 iPhone 時分頁移到底部）
  - `BCDLiveFrontEnd.swift`：接到真正資料的版本
  - BCD 在 `ContentView.swift` 約 1033 行直接用
    `BCDLiveFrontEnd(play: launchLibraryEntry, enableJIT: enableJIT, startDock: { startDock($0, compactPool: $1) })`
    取代遊戲庫（BCD 自 2026-10-19 起只剩這個介面）
- 樣式：`BCDStyle.swift`（顏色 #0B0816 底、#7C3AED 紫 → #D946EF 粉紅漸層、圓體字、圓角卡片）
- 主要畫面：`BCDHomeView.swift`、`BCDLibraryView.swift`、`BCDDownloadsView.swift`、`BCDComponents.swift`、
  `BCDArt.swift`（封面）、`BCDStore.swift` / `BCDLiveStore.swift`（資料）、`BCDFocus.swift`（手把焦點）、
  `BCDMenu*.swift`、`BCDSettings*.swift`、`BCDGamePage*.swift`（遊戲頁，最大，約 4,500 行）

## fork 這邊的接點

- `app/Madeira/Library.swift` 的 `enum FrontendChoice`（約 118 行）：
  UserDefaults key `madeiraFrontend`，目前值有 `"new"`（遊戲庫，預設）、`"old"`（開發者介面）、
  `"bcd"`（舊的 madeira-bcd HomeView）。新介面可以加一個新值（例如 `"bcd2"`），
  再在 `ContentView` 選介面的地方多一個分支，就能做成可切換。

## 授權（LICENSE-BCD.md，GPL-3.0 section 7 附加條款）

- 檔頭有 `BCD Material: additional terms ...` 的檔案，要**保留版權行和那一行**。
- App 的「關於 / 授權」畫面要加一行：
  `Includes work from BCD by thebcd69 (https://github.com/thebcd69/bcd-games)`
- 修改過的檔案要標示修改（檔頭註記日期，或 git 歷史即可）。
- **不能**說成是官方 BCD；**不能**用「BCD」「thebcd69」的名字做宣傳；**不能**用 BCD 的圖示 / logo
  （`tools/brand/` 和 app icon）。`BCDLogoMark` 用到 `Image("BCDLogo")`，要換成 fork 自己的。
- 說「based on BCD / a fork of BCD」是允許的。

## 相依性（BCD 介面用到、fork 沒有的型別）

用型別名稱粗掃的結果（只比對 struct/class/enum 名稱，**函式和屬性層級的差異沒掃到，實際缺的會更多**，
例如 BCD 在 `LibraryModel` 等共用型別上加的成員）：

- `app/Madeira/AutoTune.swift` : AutoTune, AutoTuneOffer
- `app/Madeira/AutoTuneCore.swift` : AutoTuneEngine, AutoTuneState
- `app/Madeira/AutoTuneViews.swift` : AutoTuneAlertGate
- `app/Madeira/DeviceCapability.swift` : Launch
- `app/Madeira/DockInstallers.swift` : DockInstallRequest
- `app/Madeira/DockReset.swift` : DockReset, Found, RegText
- `app/Madeira/ExternalGamesPicker.swift` : BCDExternalPickerFix
- `app/Madeira/FeedbackUpload.swift` : FeedbackUpload
- `app/Madeira/FeedbackUploadCore.swift` : FeedbackCore
- `app/Madeira/GameRecommendations.swift` : GameRecommendations
- `app/Madeira/GameRecommendationsApply.swift` : BCDGraphicsTip, Write
- `app/Madeira/GameRecommendationsList.swift` : Program
- `app/Madeira/GameRecommendationsSource.swift` : RecommendationsSource
- `app/Madeira/HardwareInput.swift` : Reading
- `app/Madeira/Library.swift` : BCDCredit
- `app/Madeira/LogUpload.swift` : LogUpload, Sent, UploadError
- `app/Madeira/LogUploadCore.swift` : LogUploadCore
- `app/Madeira/MemoryRights.swift` : MemoryRights, MemoryRightsNotice
- `app/Madeira/ProMotionIntent.swift` : ThermalPacing
- `app/Madeira/SteamCloud.swift` : List
- `app/Madeira/SteamGames.swift` : DockOption, SteamPlayCheck
- `app/Madeira/StorageModel.swift` : ExternalGameStorage, Reconnect
- `app/Madeira/SystemGestures.swift` : SystemGestures
- `app/Madeira/UpdateNotice.swift` : BCDUpdateNotice
- `app/Madeira/VCRuntimeDownload.swift` : VCRuntime

另外有幾個 C 檔跟介面一起：`BCDCab.c`、`BCDFrameRing.c`、`BCDHostStatus.c`、`BCDPauseGate.c`、
`BCDStartMenu.c`、`BCDGraphicsRoutes.c`、`BCDPhoneRumble.m`（HUD、暫停、開始選單、震動等），
它們可能還要 ntdll / win32u 那邊的配合，移植 HUD / 遊戲中選單時要一起看。

## 建議的分批

1. **外殼 + 樣式 + 遊戲庫頁**：`BCDStyle`、`BCDComponents`、`BCDArt`、`BCDFrontEnd`、`BCDHomeView`、
   `BCDLibraryView`、`BCDDownloadsView`、`BCDStore` / `BCDLiveStore`、`BCDFocus`、`BCDMenu`，
   缺的相依先用 stub 或接到 fork 現有功能。加 `FrontendChoice` 新選項，預設不變。
2. 遊戲頁（`BCDGamePage*`）與設定頁（`BCDSettings*`），要對接 fork 自己的遊戲詳細資料開關
   （fork 有很多自己加的 per-game toggle，例如 Show friends on Steam、portrait touch layout）。
3. 遊戲中的 HUD、觸控、手把、暫停（牽涉 C 檔和 ntdll），最後做，風險最大。

## 注意事項

- 這個環境沒有 Swift 編譯器，Swift 的錯誤只會在 GitHub Actions 的 Archive 步驟出現
  （錯誤會貼成 commit comment，用 `gh api repos/john62036203-ops/madeira-DOGE/commits/<sha>/comments` 讀）。
  每次編譯約 40 分鐘（ARM runner）到 2 小時（Intel），所以每批盡量一次改對。
- 新增的 Swift 檔要加進 `app/Madeira.xcodeproj/project.pbxproj`（PBXFileReference + PBXBuildFile + group + Sources），
  否則不會被編進去。
- workflow 有 settings catalog 檢查（`tests/host/check-config-catalog.py`），新增的設定鍵要讓 catalog 重新產生。
- 使用者的固定規則：每次編譯完給 IPA 連結（Actions artifact + release），一律 `publish-release=true`；
  只有 `exvs2` 的編譯會變成 release（分支編譯的發布方式要先跟使用者確認）；回覆用繁體中文；
  不要保證下一版一定能用。
