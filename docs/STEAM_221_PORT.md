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
- Per-game settings for Steam games (`SteamGameSettings.swift`, the game's ⋯ menu): AVX,
  NVIDIA, safe sync, Wine VC++ runtime, MetalFX, frame generation, FPS limit, the D3D12
  options and the raw game config, stored as `steam:<App ID>` and applied to the Dock
  session's LaunchRequest. Rows show Steam's store header image.
- Not ported: upstream's library-wide Steam game cards (they need upstream's whole
  `Library.swift`), the Dock start screen, the "Start with: The game" direct start, the
  compact JIT pool option.
- `Info.plist` gains `BGTaskSchedulerPermittedIdentifiers` for background downloads.

## Engine hooks the 221 tree may lack

Dock sets these for its session; an engine without them ignores them, which can
change how far Valve's client gets (check the log for `[dock-report]`):
`MADEIRA_IMAGE_MAP_GUARD`, `MADEIRA_GDI_SHARED_SECTION`, `MADEIRA_MADSYNC_SESSION`.
`MADEIRA_JIT_IMAGE_RETIRE` exists in 221's `virtual_ios.c`.

## Fixes taken from upstream build 270 (bahacan16 87830f1, willfaust "round 3")

Most of round 3's 32-bit fixes already came from the 221 lineage and were present
(unaligned LSE atomics on the Mach path, the teb-tsd data-map bound, PAGE_READONLY
outside the WoW64 windows, the x86 side-by-side store every session). Added here:
- `build/wineserver/fd_ios.c`: overwriting a read-only symlinked DLL (an installer's
  CopyFile over system32/syswow64) replaces the link instead of failing (PR #74).
- `build/ntdll-unix/server_ios.c`: a thread killed inside an uninterrupted section
  leaves the section before exiting, so it no longer takes fd_cache_mutex with it
  (PR #66; MADEIRA_DEFER_SECTION_ABORT=0 restores the old exit).
Not taken: fixes that live in the wine submodule (async I/O APC requeue, the WoW64
GDI shared section's win32u side), which 221 pins at a different wine.

## More 32-bit work from upstream build 270 (round 4)

- **xtajit.dll (FEX WOW64 module)** rebuilt in CI by `tools/build-xtajit-wow64.sh`
  with build 270's two fixes: the CPUID brand-string/hybrid leaves index the
  per-CPU table in range (`patch-fex-ios-cpuid-index.py`; a no-op at the pinned
  FEX, which bounds it itself), and the WinAPI shims take the TEB from Wine's TSD
  slot instead of x18, which reads 0 on some iOS threads
  (`patch-fex-ios-teb-tsd.py`). This tree's FEX submodule predates the iOS WOW64
  module, so the script builds from its own checkout (`FEX-wow64/`) at the FEX
  revision build 270 pins (26859e1). The submodule, libFEXCore and xtajit64.dll
  are not touched. On a failed build, or exports that differ from the committed
  module, the committed xtajit.dll ships unchanged.
- **32-bit media** (`docs/MEDIA.md`): winegstreamer's unix side on FFmpeg
  (WMA/xWMA, MP3, WAV, MP4 demux) and VideoToolbox/AudioToolbox (H.264/HEVC, AAC)
  in `libntdll_unix.a`, FFmpeg 7.1.1 built by `build/ffmpeg/build.sh` (LGPL-only),
  and an i386 `winegstreamer.dll` built in CI from the wine submodule (its
  winegstreamer sources are identical to build 270's pin). Bound for 32-bit
  processes only; `MADEIRA_WG_64BIT=1` is accepted but 64-bit processes have no
  arm64ec winegstreamer.dll, as upstream. If the unix side fails to compile, a
  stub table (`winegstreamer_stub_ios.c`) keeps the old behaviour.
- Not taken: build 270's lazy 32-bit address windows and the wineserver's
  resume-time SetThreadContext for 32-bit threads. Both need changes in the wine
  submodule (`server/thread.c`/`thread.h`) and in the VM code (`virtual_ios.c`)
  where this tree's JIT work lives; porting them would risk the JIT pool fixes
  that make 221 start at all.

## Steam store search, free games, no overlay (madeira-doge)

- Steam page › "Find more games on the Steam store" (`SteamStoreView.swift`):
  Steam's public store search. Owned games: Install. Free-to-play games: Get,
  which sends `ClientRequestFreeLicense` (EMsg 5572) over the app's own Steam
  connection (`SteamOwnedLibrary.requestFreeLicense`), reloads the owned list and
  starts the download. Paid games: Buy on Steam opens the store page; after
  buying, refresh the library. Nothing downloads a game the account does not own.
- Madeira Dock sessions disable the Steam Overlay (`WineProcessBridge.m`,
  `gameoverlayrenderer,gameoverlayrenderer64=d` appended to WINEDLLOVERRIDES).
  On iOS its hook search failed ~14,000 times in Among Us and its Present hook
  cut the frame rate by a third. Per game: Game settings › "Allow the Steam
  Overlay" (`env.MADEIRA_STEAM_OVERLAY = 1`), or the same line in madeira.cfg.
