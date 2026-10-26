#!/usr/bin/env python3
"""Generate app/Madeira/ConfigCatalog.generated.swift: every option Madeira reads.

Two kinds of option live in Documents/madeira.cfg:
  - plain keys ("vram-mb = 4352"), read through build/madeira_cfg.h
    (madeira_cfg_get/int/bool), the D3D12 runtime (mad_cfg_int_pe/str_pe) or
    the app (MadeiraConfig.get/bool/flag);
  - environment switches ("env.NAME = value"), which the app exports before
    Wine starts; any MADEIRA_*/DXMT_*/MYTHIC_* name the code reads with getenv,
    GetEnvironmentVariable, env::getEnvVar, madeiraSwitch or a flag helper.

The scan covers the tracked sources of this repository and of the wine, DXMT
and FEX submodules. Each option gets its type and default from the reading
call, a subsystem from the file it is read in, and the comment next to the
first read. OVERLAY adds titles and fixed choices for the options that have a
dedicated place in Settings.

    build/tools/gen-config-catalog.py           rewrite the Swift catalog
    build/tools/gen-config-catalog.py --check   exit 1 if it is out of date
"""
import collections, json, os, re, subprocess, sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(ROOT, "app", "Madeira", "ConfigCatalog.generated.swift")
REPOS = {
    ".": ["build", "app", "madeira-d3d12/src", "madeira-dock/src"],
    "dxmt": ["src"],
    "wine": ["dlls", "server"],
    "FEX": ["Source", "FEXCore/Source"],
}
EXT = (".c", ".h", ".m", ".mm", ".cpp", ".hpp", ".cc", ".swift")
SKIP = ("/host-tests/", "/ffmpeg/", "ConfigCatalog.generated.swift")

CFG = re.compile(r'\b(madeira_cfg_(?:get|int|bool)|mad_cfg_(?:int|str)_pe|'
                 r'MadeiraConfig\.(?:get|bool|flag))\(\s*"([A-Za-z0-9._-]+)"\s*(?:,\s*([^,)]+))?')
ENV = re.compile(r'\b(getenv|GetEnvironmentVariable[AW]?|env::getEnvVar|madeiraSwitch|'
                 r'madeira_switch_for_caller|mad_env_is_zero|flag|envFlag)\(\s*L?"((?:MADEIRA|DXMT|MYTHIC)_[A-Z0-9_]+)"'
                 r'\s*(?:,\s*(?:fallback:|default:)?\s*([^,)]+))?')
BOOL_READERS = {"madeira_cfg_bool", "MadeiraConfig.bool", "MadeiraConfig.flag", "flag", "envFlag",
                "madeiraSwitch", "madeira_switch_for_caller", "mad_env_is_zero"}
INT_READERS = {"madeira_cfg_int", "mad_cfg_int_pe"}

# Titles, kinds and fixed choices for options with a dedicated Settings row.
# "choices" are (value, label); the empty value means "remove the key".
OVERLAY = {
    "static-cbv": {"category": "Direct3D 12", "title": "Constant buffers as the draw was recorded",
                "kind": "int", "default": "0",
                "note": "Default off: the GPU reads every descriptor of a table when it runs. 1: a descriptor table's "
                        "single constant-buffer ranges are read when each draw or dispatch is recorded, as NVIDIA's "
                        "driver and vkd3d-proton do; a game that rewrites one after recording the draw no longer makes "
                        "that draw use another object's constants. Ranges marked VOLATILE stay as before. 2: VOLATILE "
                        "ones too (vkd3d-proton's force_static_cbv). 3: only count the rewrites ([static-cbv] lines). "
                        "Read once per game start."},
    "ring-share": {"category": "Direct3D 12", "title": "Share argument buffers between command lists",
                "kind": "bool", "default": "0",
                "note": "Default off. 1: a command list gives the argument-buffer chunks its replay wrote back as "
                        "soon as the GPU is done with them, instead of keeping them until it is recorded again; "
                        "all lists then share one pool. Red Dead Redemption 2 kept 1.5 GB of them (half of its "
                        "Metal memory) with the switch off."},
    "env.MADEIRA_PIN_GRAPHICS_DLLS": {"category": "Memory & JIT pool", "title": "Keep graphics DLLs loaded",
                "kind": "bool", "default": "0",
                "note": "Default off. On a D3D12 device/probe call, pins already loaded D3D12, DXGI and Wine Metal "
                        "DLLs until normal process shutdown, preventing repeated unload/reload copies. Keeps DLL "
                        "data live; does not recycle executable ranges or change GPU capabilities. Restart the "
                        "session after changing it.",
                "sources": ["madeira-d3d12/src/pe/madeira_d3d12.c"]},
    "env.MADEIRA_POOL_RECYCLE_IMAGES": {"category": "Memory & JIT pool", "title": "Images in retired code-buffer space",
                "kind": "bool", "default": "0",
                "note": "Default off. If other image allocations fail, retired region-C code buffers up to 64 MB "
                        "may enter the image freelist after a 3-second grace, executable-page and thread-PC checks. "
                        "Requires pool-low; 64-bit processes only. Live buffers and the pool-low-margin stay unchanged."},
    "env.MADEIRA_X64_IMAGE_NOCOPY": {"category": "Memory & JIT pool", "title": "Pure-x64 images without a JIT-pool copy",
                "kind": "bool", "default": "0",
                "note": "Default off. 1: an x64-only image (not ARM64EC hybrid, not a Wine builtin) in a 64-bit "
                        "process is not copied into the JIT pool; the emulator runs its code from the loaded "
                        "image, as 32-bit programs already do, and its executable protections are applied without "
                        "EXEC. Frees the pool for hybrid DLL copies and code buffers. Hybrid images keep their "
                        "copy. Set it in the game's own file; restart the session after changing it."},
    "env.MADEIRA_EC_HOOK_TRACE": {"category": "Debugging / logs", "title": "Log code patches the emulated copy misses",
                "kind": "bool", "default": "1",
                "note": "Default on, logging only. Compare executable PE sections and their pool copies before "
                        "sync, including x64 entry thunks. Separate budgets preserve later graphics-jump records "
                        "after native startup rewrites. A difference alone does not prove an inline hook. 0 disables it."},
    "env.MADEIRA_X64_GRAPHICS_ENTRY": {"category": "Direct3D 12 (Madeira)", "title": "Patchable x64 graphics method entries",
                "kind": "bool", "default": "0",
                "note": "Default off. 1 exposes typed x64 ARM64EC entries for swapchain Present/Present1, "
                        "ResizeBuffers/ResizeBuffers1 and queue ExecuteCommandLists/GetTimestampFrequency/GetClockCalibration/GetDesc/Signal/Wait. "
                        "With MADEIRA_DXGI_SRC=1, "
                        "also selects the factory's patchable MakeWindowAssociation and swapchain-creation entries. "
                        "The x64 entries use the loader's PE addresses so code patches and nearby allocations agree. "
                        "Existing native implementations remain behind the entries. Restart the game session."},
    "env.MADEIRA_POOL_LOW_IMAGES": {"category": "Memory & JIT pool", "title": "Small images in spare code-buffer space",
                "kind": "bool", "default": "0",
                "note": "Default off. If the normal JIT image allocation fails, copies up to 16 MB may use "
                        "unallocated region C, preserving 4 MB for code buffers. Requires pool-low; 64-bit "
                        "processes only. Does not shrink live buffers or the pool-low-margin."},
    "env.MADEIRA_IMAGE_PATCH_TRACE": {"category": "Debugging / logs", "title": "DLL code patch trace", "kind": "bool", "default": "0",
                "note": "1 logs up to 64 successful 1–16 byte executable-image protection requests and their PE/pool bytes. Read-only, owner-aware diagnostics; does not alter hooks or code."},
    "env.MADEIRA_DLL_LOCAL": {"category": "Wine core (ntdll)", "title": "App-local DLL reads", "kind": "text", "default": "",
                "note": "Optional semicolon-separated DLL filenames, including .dll. A source.dll=proxy.dll entry "
                        "redirects requests outside the executable's directory to that local proxy, preserving initial "
                        "loads from the executable's own directory. Bare filenames prefer the same local DLL. "
                        "Only read-only opens and attribute queries are redirected. Missing local files, "
                        "writes, create/delete operations, relative paths and non-file devices keep the normal path. "
                        "Off by default; set only in the game's own file."},
    "swap-mb": { "note": "Moves game data to a file on this device's storage when memory runs short, up to this size. Off by default; read at launch.", "category": "Memory & JIT pool","title": "Swap tier size", "kind": "choice",
                "choices": [("", "Off"), ("1024", "1 GB"), ("2048", "2 GB"), ("3072", "3 GB"), ("4096", "4 GB")]},
    "env.MADEIRA_SWAP_COVERAGE": {"category": "Memory & JIT pool", "note": "Which allocations the swap tier backs with its file (only when the tier is on). Large allocations (classic, the default): single 8 MB+ commits in the guest band. All allocations of 1 MB+ (blocks). 1 MB+ and overflow (wide): blocks plus allocations outside the band and fresh reservations. Whole reservations 4 MB+ (broad, ml1257): every new reservation of at least swap-min-mb (4 MB) below FEX's band backed whole when made, holes punched on decommit, swap-mb caps the disk it uses (a soft cap, checked when a block is backed). Unset: broad if swap-mode = 2, else classic.", "title": "Swap tier coverage", "kind": "choice",
                "choices": [("", "Large allocations (8 MB+)"), ("blocks", "All allocations of 1 MB+"), ("wide", "1 MB+ and overflow"), ("broad", "Whole reservations 4 MB+ (broad)")]},
    "swap-mode": {"category": "Memory & JIT pool", "title": "Swap tier mode (2 = broad)",
                "note": "2 selects broad swap coverage (ml1257) when env.MADEIRA_SWAP_COVERAGE is unset; any other value, classic. The coverage key wins when set."},
    "swap-min-mb": {"category": "Memory & JIT pool", "title": "Swap tier floor (MB)",
                "note": "The smallest allocation the swap tier backs (ml1257): 8 MB in classic, 1 MB in blocks and wide, 4 MB in broad unless set. MADEIRA_SWAP_MIN_KB overrides it for blocks, wide and broad."},
    "inproc-sync": { "category": "Synchronisation","title": "Madsync (in-process sync)", "default": "0",
                "note": "1 selects madsync (Settings > Sync engine > Madsync). Unset: fastsync, the default engine; 0 without env.MADEIRA_FASTSYNC: Wine standard sync."},
    "env.MADEIRA_FASTSYNC": {"category": "Synchronisation", "title": "Fastsync (in-process sync, default)", "kind": "choice",
                "note": "Fastsync is the default engine: with neither this nor inproc-sync set, the app exports auto. Settings > Sync engine > Fastsync removes both keys. Never runs while madsync is on. auto arms the fast wake path on heavy event traffic, 1 from the start, cells only answers polls, 0 is off.",
                "choices": [("", "Default (auto)"), ("auto", "Auto"), ("1", "On"), ("cells", "Poll answers only"), ("0", "Off")]},
    # Read by winemetal (the DXGI budget) and, for the opt-in D3DKMT adapter, by
    # build/win32u-unix/d3dkmt_ios.c; keep the DXMT category and note.
    "vram-mb": {"title": "Video memory budget (MB)", "category": "Direct3D 9/10/11 (DXMT)",
                "note": "ml1095: madeira.cfg vram-mb = N"},
    "pool": { "category": "Memory & JIT pool","title": "JIT pool size (MB)"},
    "barrier-render-uav": {"title": "Split render passes at UAV barriers",
                "note": "1 (default): a UAV barrier inside a render pass that has already drawn closes the pass, so a buffer a pixel shader wrote is complete before a later vertex shader of the same pass reads it (RE Engine's visibility G-buffer tile masks; Apple GPUs run a pass's vertex stage first). 0: ignore, as before."},
    "totalphys": { "category": "Memory & JIT pool","title": "Reported physical memory (MB)"},
    "eco": { "note": 'Runs guest threads at a lower iOS QoS class so the system favours efficiency and saves power; can cost speed. Class chosen by eco-qos.',"title": "Eco scheduling"},
    "eco-qos": {"title": "Eco QoS class", "kind": "choice", "note": "The QoS class guest threads run at while eco is on.",
                "choices": [("", "Utility (default)"), ("background", "Background"), ("initiated", "User initiated")]},
    "env.MADEIRA_WG_VIDEO": {"title": "Media: MP4 video (32-bit programs)",
                "note": "0 limits the media parser to MP3/WAV; by default MP4 with H.264/HEVC video decodes through VideoToolbox."},
    "env.MADEIRA_WOW_RWX_PLAIN": {"category": "Memory & JIT pool", "note": "Unset: a 32-bit window's anonymous RWX memory is plain read/write to the host once Wine Mono's libmono-2.0-x86.dll is mapped there (ml1279/ml1282). 1: in every 32-bit window. 0: never (stores go through the JIT pool's alias, and FEX's Mono bridge stays off)."},
    "env.MADEIRA_WINEMONO_BRIDGE": {"note": "FEX's Mono backpatcher bridge (ml712). On by itself for Wine Mono, 32- and 64-bit (ml1282/ml1286); for the 32-bit runtime in a guest window it also turns SMC detection off once the backpatcher is found (ml1280). 0 keeps it off."},
    "env.MADEIRA_MONO_DEFAULTS": {"category": "Wine libraries", "note": "Wine Mono, 32- and 64-bit: mscoree sets MONO_THREADS_SUSPEND=coop and adds keep-delegates to MONO_DEBUG before Mono loads, and puts the previous values back once Mono has read them (ml1282); values already set win. 0 sets nothing."},
    "cpu-count": {"title": "Reported CPU count (0 = device)"},
    "desktop-size": {"title": "Virtual desktop size (WxH)",
                     "note": "The developer interface's Wine desktop size (ml1127); its Resolution menu writes it (ml1157). Madeira Dock sessions without a game's Resolution use it too. Unset: this screen's shape at 1280x720's pixel count (ml1172: 1408x648 on a 19.5:9 iPhone, 1152x800 on an 11-inch iPad). Applies at the next app start."},
    "env.MADEIRA_DOCK_PRESENCE": {"category": "Steam & Dock", "title": "Friends see you as (Madeira Dock)", "kind": "choice",
             "default": "1",
             "note": "madeira-doge: once Valve's client in a Dock session is signed in, it is asked to set this persona "
                     "state (IClientFriends::SetPersonaState), so friends see the game being played. Unset or 1 online, "
                     "3 away, 7 invisible, 0 leaves the client's state alone (offline to friends, as before). January "
                     "2026 client only; any other client skips it. Settings > Steam has the same picker.",
             "choices": [("", "Online, playing the game"), ("3", "Away"), ("7", "Invisible"), ("0", "Offline (as before)")]},
    "d3d9": {"title": "Direct3D 9 frontend (32-bit)", "kind": "choice",
             "choices": [("", "Default (emulated)"), ("native", "Native ARM64 frontend")]},
    "fence-chain": {"title": "D3D12 fence chain mode"},
    "async-submit": {"title": "D3D12 asynchronous submission"},
    "upload-swap": {"title": "D3D12 upload buffers on file-backed memory"},
    "d3d12-typed-uav-load": {"title": "D3D12 typed UAV loads (report support)"},
    # Read by DXMT's DXGI and by win32u's display adapter (sysparams_ios.c); a
    # library entry's "Report an NVIDIA GPU" sets it.
    "env.DXMT_ENABLE_NVEXT": {"category": "Direct3D 9/10/11 (DXMT)", "title": "Report an NVIDIA GPU (all games)",
                "note": "1: DXGI names NVIDIA as the vendor, DXMT's NVAPI answers and win32u registers the display "
                        "adapter as a GeForce RTX 3060 (driver 581.57). Per game: Game details > Report an NVIDIA GPU, "
                        "which also sets the matching DXGI device id."},
    "ags-rewrite": {"title": "D3D12 AMD AGS 64-bit atomics rewrite"},
    "env.MADEIRA_EXE": {"title": "Program to start at launch (Windows path or name)"},
    "env.MADEIRA_ONBOARDING": {"title": "First-run Steam setup"},
    "env.MADEIRA_XINPUT": {"title": "Physical controllers (XInput)"},
    "env.MADEIRA_TOUCH_XINPUT": {"title": "Touch controller as XInput player 1"},
    "env.MADEIRA_DINPUT_PAD": {"title": "DirectInput joystick from the host gamepad"},
    # ml2100: the HID controller (build/wineserver/hidpad_ios.c, docs/CONTROLLERS.md).
    "env.MADEIRA_PAD_MODE": {"category": "Controllers", "title": "Controller API (player 1)", "kind": "choice",
                "note": "XInput (default): every controller is an Xbox pad. hid: player 1 becomes a HID game controller, "
                        "a DualSense (054C:0CE6) when it is a PlayStation pad, else a generic HID gamepad, and leaves "
                        "XInput. dualsense/generic force the identity. Read at session start; the game's own file wins.",
                "choices": [("", "XInput (default)"), ("hid", "DirectInput / HID"), ("dualsense", "HID, always a DualSense"),
                            ("generic", "HID, always a generic gamepad")],
                "sources": ["app/Madeira/GamepadInput.swift"]},
    "env.MADEIRA_HIDPAD": {"category": "Controllers",
                "note": "Set by the app at session start from env.MADEIRA_PAD_MODE (dualsense or generic) for the "
                        "wineserver and ntdll; not meant to be set by hand."},
    "env.MADEIRA_HIDPAD_NAME": {"category": "Controllers",
                "note": "Set by the app: the product string a generic HID gamepad reports (the physical pad's name)."},
    "env.MADEIRA_HIDPAD_XINPUT": {"category": "Controllers", "title": "HID mode: keep player 1 on XInput too", "kind": "bool",
                "default": "0",
                "note": "1: with the HID controller on, player 1 also stays an XInput pad. Off by default, so a game "
                        "that reads both APIs does not see the same pad twice.",
                "sources": ["app/Madeira/GamepadInput.swift"]},
    # ml2106: game output to the physical pad (app/Madeira/PadOutput.m).
    "env.MADEIRA_PAD_OUTPUT": {"category": "Controllers", "title": "Rumble, adaptive triggers and lightbar to the pad",
                "kind": "choice",
                "note": "On (default): XInput rumble plays on the controller (CoreHaptics), and in DualSense HID mode the "
                        "game's output reports drive rumble, adaptive triggers (closest GameController mode), lightbar "
                        "and player LEDs. hid: only the DualSense's; xinput: only XInput rumble; 0: none. Read at "
                        "session start; the game's own file wins.",
                "choices": [("", "On (default)"), ("hid", "DualSense output only"), ("xinput", "XInput rumble only"),
                            ("0", "Off")],
                "sources": ["app/Madeira/GamepadInput.swift", "app/Madeira/PadOutput.m"]},
    "env.MADEIRA_PROMOTE": {"title": "Hold the display at its maximum rate"},
    # madeira-bcd: GTA V Enhanced's Social Club (StikJITHelper.swift, process_ios.c, virtual_ios.c).
    "env.MADEIRA_POOL_IMAGES": {"category": "Memory & JIT pool", "title": "Wine's ARM64EC DLLs live in the JIT pool",
                "kind": "bool", "default": "0",
                "note": "Default off: every ARM64EC builtin DLL is mapped at a normal address (never executable on "
                        "iOS) and copied into the JIT pool, and a call that reaches the original address costs a "
                        "Mach exception. 1: such a DLL is mapped directly in the pool -- one copy, executable where it "
                        "is, no redirect; its data pages are protected on the pool pages. ntdll and non-builtin images "
                        "keep the copy. Needs 16 KB section alignment (Wine's builtins have it). Restart the session "
                        "after changing it.",
                "sources": ["build/ntdll-unix/virtual_ios.c"]},
    "pool-split": {"category": "Memory & JIT pool", "title": "Split JIT pool around the main thread's stack",
                "kind": "bool", "default": "0",
                "note": "1: when the pool would shrink below its size (pool, 896 MB by default) because the main "
                        "thread's stack splits the only executable band, the free run above the stack becomes a "
                        "second debugger region and both form one pool (about 880 MB instead of 560-630 MB). Costs "
                        "the second region's size in memory. Off by default; read at launch, the game's own file "
                        "wins."},
    "pool-page-fit": {"category": "Memory & JIT pool", "title": "Fit split pool regions to memory pages",
                "kind": "bool", "default": "0",
                "note": "With pool-split on: fit regions A/B to 16 KB pages instead of 16 MB steps, retaining small "
                        "remainders in free runs without increasing the requested pool budget. With pool-low on, "
                        "also fit region C to pages while preserving pool-low-margin. Costs the additional pages in memory. Off by default; read at "
                        "launch, the game's own file wins. Restart Madeira and enable JIT again after changing it."},
    "pool-pair": {"category": "Memory & JIT pool", "title": "Split JIT pool: prefer two runs above the window",
                "kind": "bool", "default": "1",
                "note": "With pool-split on: the pool takes two runs above the 0x140000000 executable window when "
                        "together they are larger than the single run it would get -- whether that run lies below the "
                        "window, where the pool cannot split (GTA V: 368 + 320 MB instead of 464 MB), or is the higher "
                        "of two runs above it (The Adventures of Elliot: 240 + 288 MB instead of 288 MB). Falls back to "
                        "the single run if the placement misses. On by default; 0 turns it off. Read at launch, the "
                        "game's own file wins."},
    "pool-low": {"category": "Memory & JIT pool", "title": "JIT code buffers below the executable window",
                "kind": "bool", "default": "0",
                "note": "1: the largest free run below the 0x140000000 executable window (less pool-low-margin) "
                        "becomes a third debugger region for the emulator's code buffers, so the whole JIT pool is "
                        "left to DLL copies (GTA V: about 300 MB more). Needs the pool above the window; costs the "
                        "region's size in memory. Off by default; read at launch, the game's own file wins."},
    "pool-low-margin": {"category": "Memory & JIT pool", "title": "Code-buffer region: MB left free below the window",
                "kind": "int", "default": "128",
                "note": "With pool-low on: how much of the free run below the executable window stays free for "
                        "programs that load there (child processes' main executables). 128 by default."},
    "env.MADEIRA_SC_CEF": {"category": "Wine core (ntdll)", "title": "Social Club's Chromium in one process",
                "kind": "bool", "default": "1",
                "note": "On by default; 0 turns it off. SocialClubHelper.exe runs --single-process with "
                        "PartitionAllocBackupRefPtr disabled and V8 --jitless (MADEIRA_JITLESS = 0 keeps V8's JIT), its "
                        "--type= children are refused, and a process with socialclub.dll mapped that is not the "
                        "helper (the game) gets no JIT-pool copy of libcef.dll: its load fails, as it did when the "
                        "pool was full. No effect on programs without Social Club."},
    "env.MADEIRA_SC_CEF_FLAGS": {"category": "Wine core (ntdll)", "title": "Extra SocialClubHelper.exe switches",
                "note": "Appended verbatim to SocialClubHelper.exe's command line while env.MADEIRA_SC_CEF is on, "
                        "e.g. --disable-gpu or --enable-logging=file --v=1."},
    "env.MADEIRA_SC_PA_POOLS": {"category": "Memory & JIT pool", "title": "Room for Social Club's PartitionAlloc pools",
                "kind": "choice", "default": "",
                "choices": [("", "Off"), ("1", "Layout 1 (chrome_elf.dll only)"), ("2", "Layout 2 (chrome_elf, libcef, Oilpan)")],
                "note": "1: Wine boots with the emulator's arena at 0x7d00000000 (12 GB instead of 16 GB) and keeps "
                        "0x7c00000000 +4 GB free, so SocialClubHelper.exe's 32 GB PartitionAlloc reservation, which "
                        "must start on a 32 GB boundary, gets 0x7800000000 (20 GB of it really reserved). 2: also "
                        "libcef.dll's (0x7000000000) and Oilpan's; the JIT pool's RW alias moves to 0x7900000000. "
                        "Off by default; set it in the game's own file; read at session start."},
    # madeira-bcd: the opt-in source build of DXMT's 64-bit dxgi.dll (tools/build-dxgi-dll.sh).
    "env.MADEIRA_DXGI_SRC": {"category": "Direct3D 9/10/11 (DXMT)", "title": "DXGI built from DXMT source (IDXGIFactory7)",
                "kind": "bool", "default": "0",
                "note": "1: the game runs the 64-bit dxgi.dll the CI builds from the dxmt submodule (dxgi-src.dll): "
                        "upstream's DXMT dxgi plus IDXGIFactory7 and EnumAdapterByLuid (GTA V Enhanced stops with "
                        "ERR_GFX_D3D_NOD3D12 without Factory7). Off (default): upstream's committed dxgi.dll. Set it in "
                        "the game's own file, not for every game; read at session start."},
    # madeira-bcd: the opt-in source build of DXMT's 64-bit d3d11.dll (tools/build-d3d11-dll.sh).
    "env.MADEIRA_D3D11_SRC": {"category": "Direct3D 9/10/11 (DXMT)", "title": "D3D11 built from DXMT source (context state swap)",
                "kind": "bool", "default": "0",
                "note": "1: the game runs the 64-bit d3d11.dll the CI builds from the dxmt submodule (d3d11-src.dll): "
                        "upstream's DXMT d3d11 plus SwapDeviceContextState, which Wine's Direct2D (d2d1) calls and "
                        "upstream's aborts in (Rockstar Games Launcher exited with code 3). Off (default): upstream's "
                        "committed d3d11.dll. Set it in the game's own file, not for every game; read at session start."},
    # madeira-bcd: the D3D12/DXGI GPU as a D3DKMT adapter (build/win32u-unix/d3dkmt_ios.c).
    "env.MADEIRA_KMT_ADAPTER": {"category": "Windows, display & input", "title": "D3DKMT adapter for the GPU (WDDM 3.1)",
                "kind": "bool", "default": "0",
                "note": "1: D3DKMTEnumAdapters2 lists the GPU DXGI and D3D12 report (same LUID) and "
                        "D3DKMTQueryAdapterInfo answers like a WDDM 3.1 driver (driver version, caps, device ids, "
                        "memory, performance data); with env.MADEIRA_DXGI_SRC = 1 DXGI's CheckInterfaceSupport gives "
                        "the same driver version. Off (default): no adapter is listed, as before. Set it in the game's "
                        "own file; read at session start."},
    # madeira-bcd: the wineserver request-path switches (willfaust/Madeira #294).
    "env.MADEIRA_SRV_DIRECT": {"category": "Wine server", "title": "Run simple server requests on the calling thread",
                "kind": "text", "default": "0",
                "choices": [("", "Off (default)"), ("1", "Files, handles, registry, events, semaphores"),
                            ("2", "Also waits, timers and the cursor")],
                "sources": ["build/wineserver/request_ios.c", "build/wineserver/fd_ios.c", "build/ntdll-unix/server_ios.c"],
                "note": "Default off. 1: the Wine server's simplest requests (opening files and their descriptors, "
                        "closing handles, mappings looked up, registry keys and values, events, semaphores, mutexes, "
                        "completion ports) run on the thread that asks, under the server's lock, instead of a round "
                        "trip through a pipe to the server thread: no thread switches, and the work runs on the asking "
                        "thread's core. 2: waits (select), timers and set_cursor too. Every other request goes through "
                        "the pipe as before. Horizon Zero Dawn's menu sends ~7000 requests a second. Read at each launch."},
    "env.MADEIRA_SRV_ECO_FOLLOW": {"category": "Wine server", "title": "Server thread follows ECO",
                "kind": "bool", "default": "0",
                "sources": ["build/wineserver/fd_ios.c", "app/Madeira/WineProcessBridge.m"],
                "note": "Default off. 1: while ECO is on, the Wine server thread runs at utility QoS (ECO's default "
                        "class) instead of user-interactive, so it moves to the efficiency cores with the game's "
                        "threads, and back when ECO goes off. In Horizon Zero Dawn's menu with "
                        "eco = 1 the server was the only thread left on a performance core (0.54 cores at ~3.9 GHz). "
                        "Server requests may take longer. Read at each launch."},
    "env.MADEIRA_SRV_IDLE_US": {"category": "Wine server", "title": "Server loop's longest sleep (us)",
                "kind": "int", "default": "1000",
                "sources": ["build/wineserver/fd_ios.c", "app/Madeira/WineProcessBridge.m"],
                "note": "Default 1000 (1 ms, as before); 100 to 50000. Requests and timers wake the Wine server at "
                        "once; only its socket polls and fd scans wait for this tick, so a longer one means fewer "
                        "server wake-ups while idle (1000 a second at the default) and slower readiness of network "
                        "sockets and pipes. Mostly useful with env.MADEIRA_SRV_DIRECT. Read at each launch."},
    "env.MADEIRA_SRV_FD_SOCKET": {"category": "Wine server", "title": "File descriptors through the process socket",
                "kind": "bool", "default": "0",
                "sources": ["build/ntdll-unix/server_ios.c", "build/wineserver/fd_ios.c"],
                "note": "Kill switch, default 0: a file's descriptor comes back in the server's get_handle_fd reply "
                        "(a copy the server makes; it shares this process's descriptor table), the same descriptor "
                        "without a sendmsg, a recvmsg, an fcntl and two server log lines per file. 1: through the "
                        "process socket, as before. Read once per app run."},
    "env.MADEIRA_DIRCACHE": {"category": "Wine core (ntdll)", "title": "Remember directory listings for file lookups",
                "kind": "bool", "default": "1",
                "sources": ["tools/patch-wine-dircache.py"],
                "note": "Kill switch, default 1: a file name that does not match in its exact case is looked up in "
                        "an in-memory copy of its directory instead of a volume query and a directory read each "
                        "time (twice when the name is absent). Source-engine games such as Team Fortress 2 probe "
                        "thousands of absent paths while loading and during play. 0: as before. Read once per app run. "
                        "(upstream PR #427 / willfaust/wine #57, applied as a build-time patch.)"},
    "env.MADEIRA_DIRCACHE_TTL_MS": {"category": "Wine core (ntdll)", "title": "Directory listing trust window (ms)",
                "kind": "int", "default": "1000",
                "sources": ["tools/patch-wine-dircache.py"],
                "note": "How long a remembered listing is used without checking the directory, while no file was "
                        "created, renamed, linked or deleted through Wine. After that one stat of the directory "
                        "decides whether it is read again. 0 checks it on every lookup. Read once per app run."},
    "env.MADEIRA_SRV_LOG_ALL": {"category": "Wine server", "title": "Every per-descriptor server log line",
                "kind": "bool", "default": "0",
                "sources": ["build/wineserver/fd_ios.c", "build/wineserver/request_ios.c"],
                "note": "Kill switch, default 0: the Wine server's add_poll_user and send_client_fd log lines (one per "
                        "opened file or descriptor sent, each a formatted write to the log file on the server thread) "
                        "are written for their first 64 and then every 1000th; a failed send is always written. 1: "
                        "every line, as before. Read at each launch."},
    # madeira-bcd: the frame-cap power governor (build/ntdll-unix/server_ios.c ios_fps_gov_step,
    # madeira-d3d12 Present, tools/patch-winemetal-fps-cap.py).
    "env.MADEIRA_FPS_CAP": {"category": "Windows, display & input", "title": "Fixed frame cap (fps)",
                "kind": "int", "default": "",
                "sources": ["build/ntdll-unix/server_ios.c", "madeira-d3d12/src/pe/madeira_d3d12.c",
                            "tools/patch-winemetal-fps-cap.py"],
                "note": "Unset (default): no cap beyond the FPS limit. 10-120: frames start at most N times a second for "
                        "the whole session: a Direct3D 12 game's thread waits after each Present, a DXMT game's encode "
                        "thread before each present (a timed kernel wait, not a spin). Any value, e.g. 20 or 24, unlike "
                        "the FPS limit's 30/40/60; the lower of the two applies. While it is set, env.MADEIRA_FPS_GOV_MW "
                        "is ignored. Needs the [xp] sampler (MADEIRA_PROBES not 0). Read at session start."},
    "env.MADEIRA_FPS_GOV_MW": {"category": "Windows, display & input", "title": "Hold CPU power with a frame cap (mW)",
                "kind": "int", "default": "",
                "sources": ["build/ntdll-unix/server_ios.c", "madeira-d3d12/src/pe/madeira_d3d12.c",
                            "tools/patch-winemetal-fps-cap.py"],
                "note": "Unset (default): off. N: while the game presents, the process's CPU power ([xp]'s energy) is "
                        "held at N mW on average by moving a frame cap between 60, 40, 30, 24 and 20 fps (at most one "
                        "step per 3 s; held while nothing presents); it moves no thread to the efficiency cores. "
                        "Menus and loading at 3-4 W fill the budget after which iOS clamps the "
                        "CPU; e.g. 1500 keeps a 60 fps menu near 30-40 fps. [fps-gov] lines every 10 s. "
                        "env.MADEIRA_FPS_GOV_MIN / _MAX (20 / 60) bound the cap, _BAND_MJ (1500) is the energy the "
                        "average may drift before it moves. Needs the [xp] sampler. Read at session start."},
    "env.MADEIRA_FPS_THERMAL_CAP": {"category": "Windows, display & input", "title": "Frame cap while the device is hot (fps)",
                "kind": "int", "default": "",
                "sources": ["build/ntdll-unix/server_ios.c", "app/Madeira/WineProcessBridge.m"],
                "note": "Unset (default): off. 10-120: while iOS reports the device serious or critical "
                        "(env.MADEIRA_FPS_THERMAL_AT = fair / serious / critical), frames start at most N times a second, "
                        "with the same low-latency wait as env.MADEIRA_FPS_CAP; the cap is lifted again at nominal. "
                        "With MADEIRA_FPS_CAP the lower of the two applies while hot; with the governor, its step capped "
                        "at N. [fps-gov] logs each change. Read at session start."},
    "env.MADEIRA_FPS_THERMAL_AT": {"category": "Windows, display & input", "title": "Thermal frame cap: hot from",
                "kind": "text", "default": "serious", "sources": ["build/ntdll-unix/server_ios.c"],
                "note": "Only with env.MADEIRA_FPS_THERMAL_CAP set: the thermal state from which the cap applies: fair, "
                        "serious (default) or critical. Read at session start."},
    "env.MADEIRA_FPS_GOV_MAX": {"category": "Windows, display & input", "title": "Frame-cap governor: highest cap (fps)",
                "kind": "int", "default": "60", "sources": ["build/ntdll-unix/server_ios.c"],
                "note": "Only with env.MADEIRA_FPS_GOV_MW set: the highest frame cap the governor uses, the largest of "
                        "60, 40, 30, 24 and 20 at or below this value (20 when lower). Unset: 60. Read at session start."},
    "env.MADEIRA_FPS_GOV_MIN": {"category": "Windows, display & input", "title": "Frame-cap governor: lowest cap (fps)",
                "kind": "int", "default": "20", "sources": ["build/ntdll-unix/server_ios.c"],
                "note": "Only with env.MADEIRA_FPS_GOV_MW set: the lowest frame cap the governor goes down to, the "
                        "smallest of 60, 40, 30, 24 and 20 at or above this value, never above the highest cap. "
                        "Unset: 20. Read at session start."},
    "env.MADEIRA_FPS_GOV_BAND_MJ": {"category": "Windows, display & input", "title": "Frame-cap governor: energy band (mJ)",
                "kind": "int", "default": "1500", "sources": ["build/ntdll-unix/server_ios.c"],
                "note": "Only with env.MADEIRA_FPS_GOV_MW set: how much energy the running balance may drift above or "
                        "below the target before the cap moves one step (100-100000; unset or out of range: 1500). "
                        "Smaller moves the cap sooner and more often. Read at session start."},
    "dxmt": {"title": "DXMT options (a=b;c=d)",
             "note": "Exported as DXMT_CONFIG with the options joined by ';', a library game's own dxmt options after these: "
                     "e.g. d3d11.mipClampBC=1;d3d11.preferredMaxFrameRate=30. DXMT reads at most 259 characters of it, "
                     "and nothing at all from a longer value (ml1255)."},
    "metalfx-upscale": {"title": "MetalFX upscaling factor", "kind": "choice",
             "note": "Scales the presented picture with Apple's MetalFX spatial scaler (Direct3D 11 and 12). Usually set per game in Game details > Display.",
             "choices": [("", "Off"), ("1.5", "1.5x"), ("2", "2x")]},
}


def category(path):
    p = path.replace("\\", "/")
    rules = [
        ("madeira-d3d12", "Direct3D 12"), ("dxmt", "Direct3D 9/10/11 (DXMT)"),
        ("madeira-dock", "Steam & Dock"), ("FEX/", "x86 emulation (FEX)"),
        ("winegstreamer", "Media"), ("audio", "Audio"), ("madsync", "Synchronisation"),
        ("/sync", "Synchronisation"), ("virtual_ios", "Memory & JIT pool"), ("JITAllocator", "Memory & JIT pool"),
        ("StikJIT", "Memory & JIT pool"), ("signal_", "Exceptions & threads"), ("thread", "Exceptions & threads"),
        ("wine/server", "Wine server"), ("wineserver", "Wine server"), ("win32u", "Windows, display & input"),
        ("Winios", "Windows, display & input"), ("Input", "Windows, display & input"), ("Gamepad", "Controllers"),
        ("Touch", "Controllers"), ("dinput", "Controllers"), ("xinput", "Controllers"),
        ("Steam", "Steam & Dock"), ("Dock", "Steam & Dock"), ("Onboarding", "Steam & Dock"),
        ("Library", "App & front end"), ("FPSOverlay", "App & front end"), ("app/Madeira", "App & front end"),
        ("ntdll", "Wine core (ntdll)"), ("wine/dlls", "Wine libraries"), ("build/", "Wine core (ntdll)"),
    ]
    for needle, name in rules:
        if needle in p:
            return name
    return "Other"


def comment_near(lines, i):
    """The comment on line i, else the nearest comment block within 8 lines above."""
    def trailing(line):
        for m in re.finditer(r'//+|/\*+', line):
            if line[:m.start()].count('"') % 2 == 0:   # not inside a string literal
                return line[m.end():]
        return None
    parts = []
    t = trailing(lines[i])
    if t and t.strip(" */"):
        parts.append(t)
    else:
        j = i - 1
        while j >= 0 and j >= i - 8 and not lines[j].strip().startswith(("//", "/*", "*")) \
                and not lines[j].rstrip().endswith("*/"):
            j -= 1
        block = []
        while j >= 0 and j >= i - 14:
            t = lines[j].strip()
            if t.startswith(("//", "/*", "*")) or t.endswith("*/"):
                if not t.startswith(("//", "/*", "*")):
                    t = trailing(t) or t
                block.insert(0, t)
                j -= 1
            else:
                break
        parts += block
    text = " ".join(parts)
    text = re.sub(r'/\*+|\*+/|//+', ' ', text)
    text = re.sub(r'(^|\s)\*(\s|$)', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(" *-")
    return (text[:237] + "...") if len(text) > 240 else text


def scan():
    opts = {}
    for repo, dirs in REPOS.items():
        base = os.path.join(ROOT, repo)
        if not os.path.isdir(base):
            continue
        out = subprocess.run(["git", "-C", base, "ls-files", "--"] + dirs,
                             capture_output=True, text=True).stdout.split()
        for rel in out:
            path = os.path.normpath(os.path.join(repo, rel))
            if not path.endswith(EXT) or any(s in path for s in SKIP):
                continue
            try:
                txt = open(os.path.join(ROOT, path), errors="ignore").read()
            except OSError:
                continue
            lines = txt.split("\n")
            for pat, is_env in ((CFG, False), (ENV, True)):
                for m in pat.finditer(txt):
                    reader, name, arg = m.group(1), m.group(2), (m.group(3) or "").strip()
                    if is_env or reader == "MadeiraConfig.flag":
                        key = "env." + name
                    else:
                        key = name
                    ln = txt.count("\n", 0, m.start())
                    kind = "bool" if reader in BOOL_READERS else "int" if reader in INT_READERS else "text"
                    dflt = ""
                    if reader in ("madeira_cfg_int", "madeira_cfg_bool", "mad_cfg_int_pe"):
                        dflt = arg if re.fullmatch(r'-?\d+|0x[0-9a-fA-F]+', arg or "") else ""
                    elif reader in ("MadeiraConfig.flag", "flag", "envFlag"):
                        dflt = "0" if arg.endswith("false") else "1" if (not arg or arg.endswith("true")) else ""
                    elif reader in ("madeiraSwitch", "madeira_switch_for_caller"):
                        dflt = "32-bit only"
                    elif reader == "MadeiraConfig.bool":
                        dflt = "1" if arg.endswith("true") else "0"
                    o = opts.setdefault(key, {"key": key, "kind": kind, "default": dflt, "sites": []})
                    if o["kind"] == "text" and kind != "text":
                        o["kind"] = kind
                    if not o["default"] and dflt:
                        o["default"] = dflt
                    o["sites"].append((path, ln + 1, comment_near(lines, ln)))
    # The engine code that acts on an option describes it better than the
    # Settings UI that merely reads it back: prefer sites outside app/.
    for o in opts.values():
        sites = sorted(o.pop("sites"), key=lambda s: (s[0].startswith("app/"), s[0], s[1]))
        o["category"] = category(sites[0][0])
        o["note"] = next((n for _, _, n in sites if n), "")
        files = []
        for p, _, _ in sites:                 # file names only: line numbers would make
            if p not in files:                # the catalog stale on every unrelated edit
                files.append(p)
        o["sources"] = files[:3]
    for key, extra in OVERLAY.items():
        o = opts.setdefault(key, {"key": key, "kind": "text", "default": "", "category": "App & front end",
                                  "note": "", "sources": []})
        o.update({k: v for k, v in extra.items()})
    return [opts[k] for k in sorted(opts, key=lambda k: (opts[k]["category"], k.lower()))]


def swift_str(s):
    return json.dumps(s, ensure_ascii=False)


def render(opts):
    out = ["// Generated by build/tools/gen-config-catalog.py from the sources that read each option.",
           "// Do not edit by hand: run the script (tests/host/check-config-catalog.py fails when stale).",
           "", "extension ConfigCatalog {", "    static let generated: [ConfigOption] = ["]
    for o in opts:
        choices = ", ".join(f"({swift_str(v)}, {swift_str(l)})" for v, l in o.get("choices", []))
        sources = ", ".join(swift_str(s) for s in o["sources"])
        out.append(f'        ConfigOption(key: {swift_str(o["key"])}, title: {swift_str(o.get("title", ""))}, '
                   f'kind: .{o["kind"]}, defaultValue: {swift_str(o["default"])}, '
                   f'category: {swift_str(o["category"])}, note: {swift_str(o["note"])}, '
                   f'choices: [{choices}], sources: [{sources}]),')
    out += ["    ]", "}", ""]
    return "\n".join(out)


def main():
    text = render(scan())
    if "--check" in sys.argv:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            print("ConfigCatalog.generated.swift is out of date: run build/tools/gen-config-catalog.py")
            return 1
        print("ConfigCatalog.generated.swift is current")
        return 0
    open(OUT, "w").write(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
