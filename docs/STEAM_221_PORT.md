# Steam on the build-221 base

This branch (`from-221`) carries the upstream project's Steam features on top of
the build-221 tree, which has no Steam code of its own.

## What came over unchanged

- `app/Madeira/SwiftSteam/**`: Steam sign-in (password, QR), the Steam connection,
  library fetch, depot downloader and the C decoders (liblzma shim, zstd, zip chunks).
- `SteamOwnedLibrary`, `SteamDownloadBackground`, `SteamInstall`, `SteamKeyValues`,
  `SteamRuntime`, `MadeiraDock`, `MadeiraDockView`, `DockInstallers`.
- `build/madeira-dock/build.sh` and the `research/madeira-dock` submodule
  (builds `dockhost.exe`; the workflow step only warns when it fails).
- `docs/MADEIRA_DOCK.md`, `docs/STEAM_SIGNIN.md`, `docs/STEAM_LIBRARY.md` (upstream text).

## What differs from upstream

- 221 has no `Library.swift`, so the Steam screens are replaced by one page,
  `SteamHubView` (cloud button in the library's top bar): account, Valve's client
  components, the owned games with Install / Pause / Resume / Remove, and Play.
- Play goes through `MadeiraDockLauncher` (`DockLaunch.swift`), which does what
  upstream's `ContentView.startDock` does (checks, one-use sign-in transfer, host
  environment, one-time installers) and returns a `LaunchRequest` with `dock = true`;
  `RootView` starts it like any library game.
- `LaunchRequest.apply` exports `MADEIRA_DOCK_SESSION=1` for a Dock launch only;
  `WineProcessBridge.m` then publishes no fixed Steam identity (the 221 engine
  otherwise gives every guest Thumper's App ID).
- `SteamOwnedLibrary` no longer touches a library model: no per-game library entries.
- Not ported: upstream's Steam game cards and per-game settings (`SteamGames.swift`),
  the Dock start screen, the "Start with: The game" direct start, the compact JIT pool option.
- `Info.plist` gains `BGTaskSchedulerPermittedIdentifiers` for background downloads.

## Engine hooks the 221 tree may lack

Dock sets these for its session; an engine without them ignores them, which can
change how far Valve's client gets (check the log for `[dock-report]`):
`MADEIRA_IMAGE_MAP_GUARD`, `MADEIRA_GDI_SHARED_SECTION`, `MADEIRA_MADSYNC_SESSION`.
`MADEIRA_JIT_IMAGE_RETIRE` exists in 221's `virtual_ios.c`.
