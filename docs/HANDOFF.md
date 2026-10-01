# Handoff: state of the madeira-bcd fork (2026-09-27)

> **Türkçe özet:** Bu dosya, Claude ile bu depoda yapılan bütün işin devir
> notudur; başka bir asistan (ör. ChatGPT Codex) buradan devam edebilsin diye
> yazıldı. Kullanıcıya Türkçe yanıt verilir. Teknik ayrıntıların tamamı
> `docs/madeira-bcd.md` içinde; bu dosya "nerede kaldık, kurallar neler,
> sırada ne var" sorularını cevaplar.

This file is for whoever continues the work (another coding agent or a
person). Read it first, then `docs/madeira-bcd.md` (every change this fork
makes, with the reason and the evidence), `docs/WOW64.md`, `docs/BUILDING.md`.

> **MANDATORY FOR EVERY AGENT (Claude, ChatGPT/Codex, anyone) -- owner's
> order, 2026-09-30.** The owner alternates between assistants. Every change,
> however small -- code, CI workflow, patch script, submodule pin, config
> default, build dispatched, device test result, owner decision, secret or
> account set up -- MUST be written into this file **in the same commit** (or
> the next one, before handing back to the owner): what changed, why, the
> evidence (log time / build number), and what is still open. Append; do not
> rewrite or delete earlier findings. If you only investigated and changed
> nothing, still note what you found. `AGENTS.md` and `CLAUDE.md` at the
> repository root repeat this rule. Start with section 0 (latest status).

## 0. Latest status (keep this section current; newest first)

* **2026-09-30 (Claude):** builds 244-252+ -- see "Builds 228-234" section for
  the full trail. In short:
  - 32-bit **Crysis** runs (D3D10 via DXMT, ~110 FPS unrecorded on build 249).
    Fixed: IAT sync, CPUID index, WOW64 TEB (x18), self-suspend (30 s gaps
    between intro videos), guest main thread QoS (it ran on E-cores only).
    **Open:** tree/branch geometry streaks in D3D10 (`-dx9` renders correctly
    but at ~28 FPS). Fixes in flight: zero-padded short constant buffers and
    realigned 16-bit index ranges -- the first versions skipped GpuManaged
    buffers and so never ran for static data; the build after 251 covers them
    and logs `[cb-short] ... encode:` / `[idx-align] ... encode:` counts.
  - **God of War** reaches the main menu; open issue is memory (jetsam at 8 GB).
    The owner is tired of regressions: before a risky change, keep the last
    good build as fallback. After the round-3 upstream merge fastsync is the
    default sync engine; God of War so far ran on madsync -- set its sync
    engine to Madsync in its game settings.
  - **Upstream round 3 merged** (100 commits, Steam library, fastsync default,
    FEX 26859e1 / wine 4f5b197 / dock 3cadfbe).
  - Build 254 (merge) failed on nsi_ndis/nsi_ip (HAVE_NET_ROUTE_H, fixed in
    the next build).
  - **OTA install** set up (section 2b). ECO toggle is in the in-game Session
    menu under "CPU" (LibraryHUD in Library.swift).
  - **Build 256 green** (run 36731040994, head 6e6f4c8, main fast-forwarded):
    merge + HAVE_NET_ROUTE_H fix + cb-short/idx-align with GpuManaged
    coverage. First OTA run worked: log 14:59:16 UTC notice "OTA: Madeira
    0.1.256 signed (profile expires 2027-01-27) ... kurulum-0.1.256.html
    written to the private bucket (links valid until 2026-10-07 14:59 UTC)".
    **Waiting on device test:** OTA install from kurulum-0.1.256.html,
    Crysis D3D10 trees (look for `[idx-align] ... encode: realigned` and
    `[cb-short] ... encode:` lines), ECO under Session -> CPU, God of War
    with Madsync (251 is the fallback).
  - **OTA install confirmed on device** (owner, 2026-09-30 18:27 UTC+3): the
    kurulum-0.1.256.html -> "Yükle" flow installed build 256 on the first try.
    The owner is now downloading 64-bit Crysis Remastered (19.4 GB) through the
    in-app Steam library. Note: 64-bit games use the committed PE d3d11.dll, so
    the cb-short/idx-align DXMT patches (i386 farm) do not apply to it.
    (Correction: pushing HANDOFF to main does not start a build -- build-ipa.yml
    runs on push only when the workflow file itself changes.)
    (Second correction: the first push of 6e6f4c8 to main DID start run 257,
    because main's previous head predates workflow changes that 6e6f4c8 carries;
    run 257 was a duplicate of 256 and is superseded by build 258.)
  - **Crysis Remastered (64-bit, Steam app 1715130) crash, log 2026-09-30
    18:42, build 256:** it reaches its window ("Crysis Remastered", 1024x768)
    and creates 23 DXMT D3D11 devices (FL 11_0), then its RenderThread (tid
    0108) calls RIP=0 with RCX = a stack pointer (`vkEnumerateInstanceVersion(&v)`
    shape; the host backtrace's first frame is vulkan-1.dll's base) ->
    c0000005 -> process exit; the later faults at 0x15a534000 /
    0x71f5771508 in xtajit64.dll are only fallout of the teardown (the JIT
    pool of the dead process was reclaimed while its threads ran). Cause: our
    vulkan-1.dll stand-in (tools/build-stub-dlls.py) returned NULL from
    vkGetInstanceProcAddr for everything, while the real Khronos loader always
    returns the global commands even with no driver. **Fix (build 258):** the
    stand-in now implements vkEnumerateInstanceVersion (1.3), empty instance
    extension/layer lists, vkCreateInstance -> VK_ERROR_INCOMPATIBLE_DRIVER,
    and vkGetInstanceProcAddr returns those five global commands (NULL for the
    rest), with real C prototypes so the arm64ec entry thunks pass arguments.
    Checked locally: the generated C compiles for arm64ec. Open: device test;
    if it still dies, look for the next NULL call in the same place.
  - **Build 258 green** (run 36739501697, head ab18526, main fast-forwarded):
    "vulkan-1.dll stand-in built (262 exports) and shipped"; OTA notice
    "Madeira 0.1.258 signed ... kurulum-0.1.258.html written to the private
    bucket (links valid until 2026-10-07 16:07 UTC)". Waiting on the owner's
    Crysis Remastered retry log.
  - **Owner, 2026-09-30 ~19:30 UTC+3, build 256:** 32-bit Crysis D3D10 tree
    streaks exactly as before -- the cb-short and idx-align fixes (now covering
    GpuManaged buffers) changed nothing visible (the log of that run has not
    been sent yet; ask for it to see whether their `encode:` counters fired).
    God of War: unchanged by the upstream merge, still dies of memory a
    little into play; the owner has not tried the memory swap setting yet.
  - **New lead for the tree streaks (build 259):** airconv's DXBC vertex fetch
    (dxbc_converter_basicblock.cpp) pulls attributes from base + stride*index
    with no bound, although the table entry carries the binding's length;
    the D3D9 path (dxso_compile.cpp, upstream) clamps to it -- and `-dx9`
    renders the trees correctly. D3D10 defines an out-of-range fetch as zero;
    Metal reads on. tools/patch-dxmt-vfetch-bounds.py (new, step "Patch DXMT
    vertex fetch bounds") routes a DXBC fetch at/past the length to the
    existing null-binding branch (zeros), logs `[vfetch-bounds] ... on` once,
    `MADEIRA_VFETCH_BOUNDS=0` turns it off, and bumps kDXMTShaderCacheVersion
    15 -> 16 so already-converted shaders are converted again (32-bit farm
    only; the committed 64-bit PE d3d11.dll keeps 15). airconv is native
    (dxmt-ios), so this reaches 64-bit D3D11 games too (see the correction
    below: God of War is D3D11; limited to SM 4.x shaders in build 260). Not compiled locally (no LLVM 15 headers here): CI is the check.
  - **OTA link by e-mail** (section 2b): owner asked for Google Drive instead of
    the B2 login; Drive cannot host an OTA install, so CI now e-mails the
    install page's pre-signed link when the OTA_MAIL_* secrets exist (added
    after build 259 was dispatched, so it rides the next build). Open: owner
    creates the app password and the three secrets.
  - **Log 2026-09-30 19:01 (named GoW.exe, build 256) is God of War, not the
    Crysis D3D10 run** (still missing): GoW reached the main menu on fastsync
    (inproc-sync unset -- Madsync was NOT selected) and idled there 18 min
    without dying. Memory at the menu: phys footprint ~7.7 GB (internal 4.1 GB
    + 2.35 GB compressed + 0.5 GB external), flat for the whole idle -- no
    leak at idle, but the menu alone sits just under the limit, so any
    gameplay allocation tips it over. DXMT census at the menu: METAL
    currentAllocatedSize 1.5 GB (tex-private 579 MB, buffers 793 MB), so most
    of the footprint is not GPU resources. **Correction:** God of War runs
    D3D11 through DXMT (mem-census), not D3D12 -- so the vertex-fetch-bounds
    change in airconv would have reached it. The patch now applies by default
    only to SM 4.x (D3D10-era) vertex shaders; GoW's SM 5.0 shaders convert
    exactly as before (MADEIRA_VFETCH_BOUNDS=1 all, =0 none). Build 259 (all
    shaders) was superseded by build 260 with this.
  - **Owner, 2026-09-30 evening:** will set up the Gmail app password and the
    OTA_MAIL_* secrets in the morning, and wants to "delete Backblaze from the
    workflow" once mail works. Told the owner: the e-mail only replaces the B2
    *login*; the IPA, manifest and signing files still live in the private B2
    bucket and the mailed link points there. Removing B2 needs another private
    store with expiring direct HTTPS links -- Google Cloud Storage (signed
    URLs; Google Cloud, not Drive) could replace it. **Owner's decision
    (2026-09-30 evening): keep Backblaze + the Gmail e-mail** (no migration);
    the owner adds the OTA_MAIL_* secrets in the morning from a PC. Do not
    remove B2.
  - **Crysis Remastered, log 2026-09-30 19:29, build 258:** the vulkan-1 fix
    worked -- the game starts, shows its menu, "New game" loads to 100 %, then
    dies. Before it: 15 x "DeviceTexture: Failed to register mach port for
    shared texture" (CreateTexture2D with a SHARED flag -> E_FAIL, because
    WMTBootstrapRegister/bootstrap_register2 is refused to an iOS app). Then
    RenderThread (tid 0110) reads address 0 in d3d11.dll rva 0x885ac =
    `MTLD3D11DeviceContextImplBase::ClearRenderTargetView` with a NULL view
    (the committed arm64ec d3d11.dll has symbols; `llvm-objdump -d` it). Level
    load memory: DXMT tex-private 4.5 GB, METAL currentAllocatedSize 1.9 GB.
    **Fix (next build):** tools/patch-winemetal-ios-shared-texture.py (native
    winemetal_unix.c, so it reaches the committed 64-bit PE too): on iOS a
    new shared texture gets no mach port, which DXMT's existing ml866 fallback
    turns into an unshared texture and S_OK. `[shared-tex]` logs the first 4;
    MADEIRA_SHARED_TEXTURE_PORT=1 restores the old path. God of War creates no
    shared textures (none in its 19:01 log). The null-RTV clear itself would
    still crash if it came from elsewhere (DXVK ignores a NULL view; DXMT's
    64-bit PE is a committed upstream binary, so that guard needs a PE rebuild).
  - Build 260 (5e90d18) was superseded early by build 261 (74ad830: vfetch
    bounds for SM 4.x + shared textures without mach port + OTA e-mail).
  - **Steam games' session logs (owner's request, 2026-09-30; not yet built --
    the owner said to hold it for the next build):** games started with the
    Steam licence (Madeira Dock: explorer.exe first, Valve's client picks the
    program) got no `Documents/logs/<exe>-<stamp>.txt`, because only the
    app's own launch paths call LogStore.startSessionLog. Now
    `madeira_steam_session_log` in build/ntdll-unix/process_ios.c
    (NtCreateUserProcess, after the spawn phase stamp) hard-links
    madeira-log.txt as `logs/<exe>-<local time>.txt` when a process under
    `steamapps\common\` starts (once per exe name; skips names containing
    fxc/redist/dxsetup/crash/setup/install -- Crysis Remastered spawns
    fxc.exe) and logs `[session-log] ... Steam game <exe>: logs/...`.
    Unit-tested on Linux in isolation (link made, fxc/duplicate/system exe
    skipped); ntdll-unix build on CI is the real check.
  - Owner asked (2026-09-30 night, B2 web keeps logging out) for the install
    links in chat until the mail is set up. Not possible by design: agents hold
    no B2 credentials (the key lives only in GitHub secrets; the one pasted in
    chat must not be used), and CI cannot hand the link over through the public
    Actions log. Pointed the owner to setting up the OTA_MAIL_* secrets from the
    phone (app password page + GitHub website in Safari) instead.
  - **Build 261 green** (run 36745357839, head 74ad830): all patch steps ran
    (vfetch bounds, winemetal shared textures), i386 farm rebuilt and saved,
    OTA notice "Madeira 0.1.261 signed ... kurulum-0.1.261.html ... valid until
    2026-10-07 17:04 UTC". Mail: "no OTA_MAIL_* secrets" -- the owner added
    them after the step ran. Build 262 (29c32ad: + Steam-game session logs)
    dispatched ~17:12 UTC as the first build with the secrets.
    (Correction to an earlier chat reply: 261 already contained the mail code;
    only the secrets were missing.)
  - **Build 262 green** (run 36749588085, head 29c32ad; main fast-forwarded,
    the duplicate push run 263 on main cancelled): Steam-game session logs,
    shared textures, vfetch bounds. **First e-mail went out**: log 17:29:06
    "OTA: install link for 0.1.262 e-mailed to the owner". Same log showed
    `aws: [ERROR] ... Unknown options: --only-show-errors` -- `aws s3 ls` does
    not take that flag, so the keep-the-last-10 cleanup silently never ran
    (builds 256-262 all still in the bucket). Fixed in sign-and-publish-ota.sh
    (plain `aws s3 ls --endpoint-url`); takes effect with the next build.
  - **Owner, build 262 (log CrysisRemastered.exe-2026-09-30_20-43-04.txt):** the
    mail arrived and worked; the Steam session log was named by exe (the new
    `[session-log]` line); `[shared-tex]` fired 4x and the game now gets past
    the load -- then dies "a few seconds later". Cause: JobSystem_Worker_0
    (tid 00a8) in kernelbase.dll rva 0x6d358 = **TlsGetValue** (`add x8, x18,
    w0, uxtw #3; ldr x0, [x8, #0x1480]`) with x18 == 0 (iOS zeroes x18):
    fault at 0x1570 (TLS slot 30). The mach handler's x18 emulation only
    handled Rn == 18 and printed `[x18-decline]`, so the AV killed the process
    (the xtajit64 faults after it are teardown fallout, as before). **Fix
    (next build):** `ios_x18_derived_base` in build/ntdll-unix/signal_arm64_ios.c
    -- when the instruction right before the fault is ADD (ext/shifted reg,
    imm) or MOV that wrote the faulting base register from x18, the fault
    address is the TEB offset and the existing TEB-relative emulation runs
    (logged `[x18-derived]`, first 8). Only a previously fatal path changes.
    Crysis Remastered memory at that point: footprint 4.8 GB.
  - **32-bit Crysis D3D10, build 262 (log Crysis.exe-2026-09-30_21-09-08.txt,
    2.5 min, no crash, footprint ~3 GB):** all three tree fixes fire --
    `[vfetch-bounds] ... on for SM 4.x vertex shaders` + bounded attributes,
    `[idx-align] ... encode: realigned`, `[cb-short] ... encode: zero-padded
    copy bound` (e.g. cb0 declared 80 vec4, bound 74). The owner has not yet
    said whether the trees still streak; asked. **Owner: unchanged, no
    improvement at all.**
  - **Build 264 green** (run 36755719496, head 88e1d6d, main fast-forwarded):
    x18-derived emulation; OTA mailed ("install link for 0.1.264 e-mailed"),
    the aws cleanup error is gone (8 builds in the bucket, nothing to delete).
  - **Next tree lead (build 265):** Crysis packs index data at 2-byte
    granularity; if its vertex buffers are bound at offsets/strides that are
    not multiples of 4, airconv's attribute loads (which claim natural
    alignment, 4 bytes for floats) read from rounded-down addresses on the
    GPU. tools/patch-dxmt-vb-align.py (new): SM 4.x vertex attribute pulls use
    alignment-1 loads (thread_local `madeira_vfetch_align1` set around the
    pull in pull_vertex_input, honoured in load_from_device_buffer;
    MADEIRA_VFETCH_ALIGN1=0 off, =1 all shaders; `[vfetch-align]` once);
    PE-side census `[vb-align]` of IASetVertexBuffers offsets/strides not
    4-aligned; shader cache version 16 -> 17. God of War (SM 5.0) unchanged.
    If `[vb-align]` stays silent, the theory is dead and this change is inert.
  - **Crysis Remastered, build 264 (log CrysisRemastered.exe-2026-09-30_21-19-06):**
    got further -- the owner saw the rendered scene for 5-6 s for the first
    time -- then the SAME TlsGetValue fault (pc pool+..358, addr 0x1570, x18=0,
    tid 00a8 "Main" this time) and `[x18-decline]`: the `[x18-derived]` path
    never fired, because the x18 patcher (virtual_ios.c, "via x18" form) had
    moved the `add x8, x18, w0, uxtw #3` into a trampoline (`mrs x18,
    TPIDRRO_EL0; and; ldr x18,[x18,#slot]; add; b back`), leaving `b tramp` at
    pc-4. TlsGetValue is hot enough that a preemption between the trampoline's
    ldr and its add (iOS zeroes x18) happens within seconds. **Fix (build 266):**
    ios_x18_derived_base follows a `b` at pc-4 when its target has exactly
    that trampoline shape and branches back to the fault, and checks the ADD
    inside it (unit-tested with the logged words: rn 8 -> derived, rn 9 -> not).
    Build 265 (vb-align) was superseded by 266 (vb-align + this).
  - **Build 266 green** (run 36758343731, head 72517a8; main fast-forwarded):
    i386 farm rebuilt with the [vb-align] census (725 files, exit 0, cached),
    all patch steps applied, OTA mailed ("install link for 0.1.266 e-mailed").
    Waiting on the owner: Crysis Remastered ([x18-derived]) and 32-bit Crysis
    D3D10 trees ([vfetch-align], [vb-align]).
  - **Crysis Remastered RUNS on build 266** (owner, 2026-09-30 ~22:12-22:35
    UTC+3, four logs, "harika çalışıyor"): `[x18-derived] ... base x8 from x18
    -> TEB+0x1490 emulated` fired 7x in the long run (6 min, no crash); none of
    the four logs has an access-violation exit. Open: **MetalFX upscaling did
    not engage** -- no MetalFX line in any log. Cause: a Steam game started
    with the Steam licence goes launchLibraryEntry -> startDock and returned
    before BCDLaunch.applyLibrary, so MADEIRA_CFG_GAME, DXMT_METALFX_SPATIAL_
    SWAPCHAIN / d3d11.metalSpatialUpscaleFactor, AVX, wine-vcrt and NVIDIA
    were never set for Steam games. **Fix (next build):** the Steam branch
    calls `BCDLaunch.applyLibrary(entry, sessionLog: false)` before startDock
    (the native side already names that session log after the exe); the
    `[bcd] library launch` line now also prints `metalfx=`. The committed
    64-bit d3d11.dll does contain DXMT's MetalFX spatial swapchain strings.
    Not compiled here (no Swift toolchain); CI is the check.
  - **Backblaze mail 2026-09-30 22:57 UTC+3: "Download Bandwidth Cap Reached
    75%"** of the free daily download allowance (1 GB/day on a free B2
    account). Every OTA install downloads the whole IPA (~150 MB) from the
    bucket; the owner installed about six builds today. Agents should have
    warned about this when the OTA was set up (not done). Facts for the owner:
    at 100% B2 blocks further downloads until the daily reset (00:00 UTC =
    03:00 UTC+3) -- with caps at the free level it does not charge; raising
    the cap (Caps & Alerts, needs a payment method) costs about $0.01/GB,
    i.e. ~0.15 cents per install. Longer term option: Cloudflare R2
    (S3-compatible, presigned URLs, no egress fees, 10 GB free storage) would
    need only endpoint/region/secret changes in sign-and-publish-ota.sh.
    Pending the owner's choice; nothing changed.
  - **Build 268 green** (run 36767022535, head 6e574ab, main fast-forwarded):
    Steam games get their game options. **Owner: MetalFX now works in Crysis
    Remastered.** Owner's decision: **move the OTA store to Cloudflare R2 in
    the morning** (2026-10-01). Prepared, not yet built: sign-and-publish-ota.sh
    uses R2 when R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY /
    R2_BUCKET all exist (endpoint <account>.r2.cloudflarestorage.com, region
    auto, same layout: Development.p12 + Development.mobileprovision at the
    bucket root, ota/ for builds, kurulum-<ver>.html at the root), else B2
    as before; logs `OTA: store R2|B2`. Owner's steps: create a private R2
    bucket, an R2 API token with Object Read & Write on that bucket only,
    upload the two signing files, add the four secrets. After the first R2
    build mails a working link, B2 secrets can be removed.
  - **Upstream sync 2026-10-01 (12h routine):** merged 40d5e74 "Library:
    ambient light around grid cards, a card press and a new not-installed
    look" (AmbientGlow/AmbientMovie behind grid cards, LibraryCardButtonStyle
    press, fainter not-installed cards; env.MADEIRA_LIBRARY_AMBIENT = 0 turns
    it off). One conflict in Library.swift: upstream's
    `.libraryCardButtonStyle(grid: !list)` kept together with our long-press
    context menu (Play / Game settings). ConfigCatalog regenerated (check
    PASS). No submodule changes. Build dispatched (it also carries the
    prepared, still inactive R2 support).

---

## 1. What this repository is

`bahacan16/madeira-bcd` is a personal fork of `willfaust/Madeira`: Wine + FEX
(x86-64 JIT, ARM64EC) + DXMT (D3D11/D3D9 over Metal) + `madeira_d3d12` (a D3D12
runtime over Metal that converts DXIL with Apple's Metal Shader Converter and
DXBC with DXMT's airconv) packaged as an iOS app. The owner runs Windows games
on an **iPhone 17 Pro Max, iOS 27.0**, sideloaded with Feather. Personal use
only; the bundle id stays `com.willfaust.mythicemu`.

Since build 222 (2026-09-29) the fork follows **upstream `willfaust/Madeira`
main** and its submodule pins (wine `daa17d0`, FEX `2838f3b`, DXMT `a5e0cd3`,
`research/madeira-dock`), with this fork's own work re-applied on top. The
earlier 125hz PRs (#28 WoW64 + DXMT D3D9 on `125hz/wine pr/wow64-core` and
`125hz/dxmt pr/d3d9`; #29 named touch layouts) were replaced by upstream's
own WoW64, D3D9 import and touch presets. What that switch dropped until it
lands upstream: 125hz's fastsync, fs caches and networking work in wine (125hz
is re-upstreaming them as `pr/fastsync-opt-in`, `pr/async-apc-requeue`,
`pr/image-map-notify-guard`). The pre-switch tree is the local branch
`backup/pre-upstream-switch` = commit `563ac69` on the dev branch history.

## 2. Working conventions the owner expects

* **Reply in Turkish.** Owner's clock is UTC+3.
* Work autonomously: diagnose from the log, fix, build, hand over an IPA link.
  The owner dislikes being asked things the agent can decide itself.
* The owner explicitly authorized **automatically starting this workflow after
  every crash/error report** (2026-09-27). Do not stop after pushing a fix;
  dispatch the development-branch workflow, inspect its result, and hand over
  the IPA run/artifact link. Keep this handoff append-only in substance so
  Claude and Codex can alternate without losing earlier findings.
* **Build monitoring preference (owner, 2026-09-27):** After dispatch, verify
  that the run started, then check its status **once about 10 minutes later**.
  Do not poll every step or send running-status screenshots; those wasted
  tokens during build 186. If still running, check again at a sensible longer
  interval, and report the final result and artifact link. Send a screenshot
  only when the owner asks for one.
* Develop on branch **`claude/madeira-bcd-repo-ymg5cb`**, push there.
* Build: dispatch `.github/workflows/build-ipa.yml` on that branch
  (workflow_dispatch). When it is green, fast-forward `main`
  (`git push origin <sha>:main`); if that starts an automatic push build on
  `main`, cancel it (it is a duplicate).
* Version = `0.1.<run_number>` (Info.plist stamped in CI). The artifact is
  `madeira-0.1.<N>-unsigned-ipa`; link format
  `https://github.com/bahacan16/madeira-bcd/actions/runs/<run id>`.
  Downloading artifacts needs a signed-in GitHub account (GitHub rule).
* CI failures: read annotations with
  `curl -s https://api.github.com/repos/bahacan16/madeira-bcd/check-runs/<job id>/annotations`;
  full logs via the Actions UI / API job logs.
* Commit messages: say what was wrong, the evidence, and the fix (see
  `git log`). Keep `docs/madeira-bcd.md` updated for every change.
* **Update packs (since build 215) -- prefer them to a new IPA.** A change
  confined to the D3D12 runtime's PE source (`research/madeira-d3d12/src/pe`)
  does NOT need an IPA: pushing it to the dev branch runs
  `.github/workflows/build-pack.yml` (a few minutes), which publishes
  `madeira-pack-<N>.zip` + `index.json` on the public prerelease **`packs`**.
  The owner taps Settings > Updates (or the home banner) and the next game
  start uses it. Tell the owner "pack N", not an IPA link, for such fixes.
  A pack installs only over an app whose `MadeiraNativeABI` (Info.plist)
  equals the pack's `native_abi` (`tools/native-abi.sh`: app/, build/, DXMT,
  the conversion service, patch scripts, wine/FEX commits). Anything native
  (Swift/ObjC, ntdll-unix, winemetal unix, madeira_cfg.h, DXMT patches) still
  needs the IPA build -- and after it, packs are built against the new ABI.
  If a workflow change alters the native build, bump `EPOCH` in
  `tools/native-abi.sh`. The hash is over git blobs, so ANY edit to a native
  file (a comment too) makes packs built afterwards refuse the installed app:
  batch native edits into the next IPA rather than touching them between
  builds. Check with `tools/native-abi.sh` against the app's value
  (Settings > Updates shows it). The `packs` release holds only DLLs built from this
  repository (never an IPA, Apple's converter or Microsoft's runtime).
* **Per-game config:** Settings sheet of a game > "Advanced: this game's
  config" edits `Application Support/GameConfigs/<hash>.cfg` (madeira.cfg
  syntax). Exported as `MADEIRA_CFG_GAME`; `madeira_cfg_get` lets its keys win
  over madeira.cfg and its `env.*` lines are exported last. Use it to ask the
  owner to A/B a switch for one game without any build.
* A 12-hour "upstream sync" routine runs on the Claude side (merge
  `willfaust/Madeira` main into the dev branch keeping this fork's additions,
  build, report). By hand: `git fetch upstream main` (remote =
  willfaust/Madeira), merge, keep this fork's additions, build, fast-forward
  main. Since build 222 upstream's side (and its submodule pins) wins where it
  replaced something we carried.

## 2b. Over-the-air install (owner's decision 2026-09-30)

* CI step "Sign for OTA install (private bucket)" runs
  `tools/sign-and-publish-ota.sh` after the unsigned IPA is packaged
  (continue-on-error; skips itself when a secret is missing).
* The owner's signing files live ONLY in the owner's **private** Backblaze B2
  bucket `Github-BCD` (root: `Development.p12`, `Development.mobileprovision`).
  Repository secrets: `B2_KEY_ID` (the keyID, not the key name), `B2_APP_KEY`,
  `B2_S3_ENDPOINT` (`s3.eu-central-003.backblazeb2.com`), `B2_SIGN_BUCKET`
  (`Github-BCD`), `SIGN_P12_PASSWORD`. The key is limited to that bucket.
* Output: `ota/Madeira-<ver>.ipa` + `ota/manifest-<ver>.plist` (last 10 kept;
  the cleanup only works from the build after 262, see section 0)
  and `kurulum-<ver>.html` at the bucket root with a "Yükle" button (owner
  asked for the version in the name, 2026-09-30; the last 10 are kept); links
  are 7-day pre-signed URLs. The owner opens the newest `kurulum-<ver>.html`
  from the B2 panel/app; tapping "Yükle" makes the iPhone download
  `ota/Madeira-<ver>.ipa` straight from the same private bucket.
* **Nothing is public:** the repo and its Actions logs are public, so the
  script never prints a URL or key. A public/unlisted bucket was refused by the
  session's safety check (the IPA contains Apple's converter library and the
  owner's device-bound profile) -- do not reintroduce it.
* **E-mail delivery (added 2026-09-30, owner found the B2 login tedious and
  asked about Google Drive):** Drive cannot serve the OTA itself -- iOS's
  installer fetches the manifest/IPA without any login, so a Drive file would
  have to be shared publicly (refused above), and Drive answers large files
  (>100 MB) with an HTML virus-scan page instead of the bytes. Instead, when
  the secrets `OTA_MAIL_USER` (sending Gmail/Workspace address),
  `OTA_MAIL_APP_PASSWORD` (an app password, not the account password) and
  `OTA_MAIL_TO` exist, the script e-mails the owner a 7-day pre-signed link to
  `kurulum-<ver>.html` (smtp.gmail.com:587, STARTTLS); it opens in Safari with
  no login, "Yükle" installs. The address stays in secrets (public repo); the
  log only says "install link ... e-mailed". A mail failure is a warning only.
* **Cloudflare R2** (prepared 2026-09-30, owner switches 2026-10-01): with the
  four `R2_*` secrets the same script uses R2 instead of B2 (no egress fees;
  B2's free plan allows 1 GB of downloads a day, ~6 installs).
* Signing keeps the IPA's own bundle ids (`com.willfaust.mythicemu`, extension
  `.MemoryHost`), like the owner's Feather install, so an OTA install updates
  the installed app in place. `SIGN_USE_PROFILE_BUNDLE_ID=1` would rename to
  the profile's App ID instead.

## 3. Hard rules (do not break)

* **Never commit Microsoft VC++ runtime DLLs** (`app/Madeira/x86_64-vcruntime/*.dll`
  is gitignored; CI fetches them).
* **Apple's Metal Shader Converter** installer lives ONLY as an asset of a
  **DRAFT** release tagged **`msc-private`** (`Metal_Shader_Converter_4.0_beta_2.pkg`).
  CI extracts headers + the iOS library at build time into gitignored
  `build/madeira-d3d12/msc-include/`. Never commit the pkg, headers or library,
  never publish that release. Since build 181 CI **fails** if the release is
  missing (build 180 silently shipped a stub: black screen in every D3D12 game).
* Do not publish IPAs as public releases without the owner's decision (the IPA
  contains Microsoft redistributables and Apple's converter library).
* Do not commit externally supplied binaries (exception already granted: the
  125hz PR #28/#29 DLLs).
* The owner's Ghost of Tsushima / Crysis copies are cracked (RUNE / Steam
  emulator). Fix Madeira-side bugs only; **do not help configure crack or
  Steam-emulator files** (e.g. `steam_api.ini`).
* A GitHub PAT was once pasted in chat; the owner was told to revoke it. Never
  use tokens from chat. The signing `.p12` (+password) and `.mobileprovision`
  must never be committed or printed. Since 2026-09-30 (owner's decision) CI
  uses them only from the private B2 bucket for OTA signing (section 2b);
  agents do not handle the files themselves.

## 4. Ghost of Tsushima (D3D12, Nixxes port) -- PAUSED 2026-09-29

### Where it stands (owner paused GoT on 2026-09-29; resume from here)
State: IPA 218 (native ABI 48a89bc6c3cadd93) + pack 6 (68e4735). Playable in
gameplay at ~35-45 FPS at 1280x720 with FSR3 Performance. Open items, in order:
1. **C++ exception fast-fail (0xC0000409), the main stability blocker.** It
   happens during loading and in gameplay (logs 09-28 18:53, 20:41; also
   builds 187 and 191). The stack is always the same: GhostOfTsushima+0x449681
   (recursive), +0x40a99d, VCRUNTIME140_1 frame handler, and the handler
   thunk +0xd15f0c ends in __fastfail. It is not the device list race
   (pack 5 did not change it). Hypothesis: during C++ exception dispatch
   through x64 frames under ARM64EC/FEX, the unwinder or dispatcher context
   (ControlPc / ImageBase / state) is wrong, so __CxxFrameHandler4 reaches
   terminate. Next step is native, so an IPA: log the DISPATCHER_CONTEXT of
   every frame for code e06d7363, and whether `_ThrowImageBase` is 0 (see
   "Build 191 results").
2. **Rendering corruption the owner calls "objelerdeki sıkıntı".** It must be
   re-checked with pack 6 in a session where F0 is NEVER used: every earlier
   observation after an F0 test was polluted (see "Pack 6"). If it remains,
   press CAP while it is on screen. The leading suspect is the velocity target
   (RG16F, NaN/Inf over the sky in older captures) feeding FSR3/TAA. FSR3
   Performance's jagged edges are expected (internal ~640x360); with FSR off
   the edges are clean but the corruption stays, and FPS drops a lot (GPU-bound
   at native 720p).
3. Performance: in steady gameplay the game's own CPU time under emulation
   dominates (~18 of ~25 ms). Our D3D12 layer costs 4-6 ms: encode 0.7,
   encoder open/end 1.8, the rest is the replay. async-submit=1 takes that
   off the game thread, but the worker sits at ~16 ms per frame; re-measure
   on a cool phone. F5 measured +2-3 FPS over F1 (owner, 09-28), which makes
   it a candidate per-game default.
4. Hitches of 50-550 ms are first-draw pipeline compiles (pso-lazy); the
   shader cache removes them on the next visit.

### Progress so far (each item is a commit; details in docs/madeira-bcd.md)
Save folder -> D3D12 use-after-free -> display config crash -> GPU driver info
(NVAPI entry points + a registry display adapter, "Report an NVIDIA GPU"
per-game switch) -> `GetAdapterLuid` -> `GetDeviceRemovedReason` -> DXBC
static samplers (black screen) -> intros + main menu work -> New Game OOM
(30k Metal libraries) fixed by lazy pipelines + shared libraries + a
persistent disk shader cache -> game reaches gameplay (~20-40 FPS) ->
**GPU timeout a few seconds into gameplay** (the remaining blocker).

### The GPU timeout (fixed in build 181, confirmed on device)
Every run: 2-5 s into gameplay FPS sinks from ~40 to ~20, then Metal ends a
command buffer with `MTLCommandBufferError` code 2 (timeout), ignores the queue,
and the game tears itself down (its workers then fault copying freed memory,
its crash handler `crs-handler.exe` crashes — both are consequences).
Found with the fault-attribution machinery (below): the kernel (DXIL hash
`34c565ac8322ab2a`, 3948 bytes, `Dispatch(221,1,1)`, 64 threads/group) is a
vertex-normal recompute. Each thread reads a `[first,last)` adjacency range
from a StructuredBuffer at its thread id and loops `until i == last`. The
dispatch is rounded up to the group size, so the extra threads read past the
buffer. D3D12 returns 0 there; the converter did not bounds-check
(`IRCompatibilityFlagBoundsCheck` was off), read garbage and looped forever.
**Build 181 converts with `IRCompatibilityFlagBoundsCheck`**
(`research/madeira-d3d12/src/unix/madeira_ir_unix.mm`; opt out with
`MADEIRA_IR_NO_BOUNDS_CHECK=1`). The shader-cache key changed, so the first
launch re-converts everything (the "Compiling shaders" screen takes a few
minutes and looks frozen — do not close it).

**Next step:** have the owner run build 181 (AVX on, "Report an NVIDIA GPU"
on, press Enter at the dark launcher, New Game) and check the log: there
should be no `GPU fault` line and FPS should stay flat.

### Build 181 result (log 2026-09-27 14:55, 800x600): the GPU timeout is GONE
No `GPU fault` line at all; the scene renders (banners, grass) at 50-60 FPS
before gameplay. The new wall is on the CPU: when gameplay starts,
`ExecuteCommandLists` per frame goes 25 ms -> 273 ms -> 2.3 s while the GPU
is 2-7 % busy (Metal HUD: "Detected high CPU encoding cost with encoders
spending an average of 100% of frame time encoding"; "Compiled Shaders 693 |
12.5 s"). Cause: lazy pipelines (`mad_pso_realize`) are compiled by Metal at
their first draw, on the submitting thread, one at a time, under one global
lock; the first gameplay seconds need hundreds. After ~2 s frames the game
stops itself at the same `int3` it uses for fatal errors (guest RIP ...9acd,
call chain ...b950 / ...63e5) — most likely its own hang watchdog.

**Build 183** (commit "build a batch's new pipelines in parallel"): a per-pipeline lock replaces the
global one, and before a batch is replayed the lazy pipelines its lists bind
are built on up to 4 threads (`mad_prebuild_lists`, madeira.cfg
`pso-parallel = 0` to disable; log line `pso-parallel: built N pipelines`).
Expected: the stall shrinks roughly by the core count. If frames still take
seconds, next steps (in order of payoff):
1. **Persist compiled pipelines across launches** with `MTLBinaryArchive`
   (or Metal 4 `MTL4Archive`): add winemetal calls to create/load an archive,
   add pipeline descriptors to it, serialize it next to the shader cache
   (`%LOCALAPPDATA%\Madeira\ShaderCache\<identity>\`), and pass it as
   `binaryArchives` when creating pipelines. Second launch then compiles
   nothing. Needs changes in `research/dxmt/src/winemetal` (done at build
   time through a `tools/patch-dxmt-*.py`, like the fault-info patch).
2. Start building a lazy pipeline in the background at `CreatePipelineState`
   time at low priority, capped by Metal memory (eager creation of all
   ~14k pipelines hit 5.1 GB and jetsam before; do not go back to that).

### Build 183 result (log 2026-09-27 15:34)
Main menu much smoother (ExecuteCommandLists ~2 ms/frame, 45-48 FPS; parallel
builds working: `pso-parallel: built 20..69 pipelines on 4 threads`). Gameplay
start still froze: presents stopped right after the first large prebuild
batches, then the game tore itself down (workers faulted on memory another
worker freed — the usual teardown symptom). Two problems visible in the log:
* each prebuild batch CREATED 3 Wine threads: every one costs an 8 MB stack
  (floored), a TEB and FEX thread state — a storm of `init_thread_stack` lines
  and failing 8 MB reserves (`[va-scan] FAILED ... size=0x800000`).
* the 64-bit high-band fallback only searched 0x7200000000..0x73ffff0000,
  which is already occupied on device (every `[wow-window] #N ... NOT placed`),
  and a 1 MB FEX allocation still got STATUS_NO_MEMORY.
Also note: this run had 16,968 shader-cache misses because the cache key
includes the madeira_d3d12 build stamp — every new build re-converts every
shader once (first launch after an update is slow; second launch is not).

**Build 184**: a persistent pool of 3 prebuild threads (created once), and the
high-band fallback searches everything above the 32-bit windows up to the
user-space limit (still bounded by a caller's limit_high). If gameplay still
freezes, check whether presents stop while `pso-parallel` batches run
(pipeline compile time) or with no batches (then it is something else: look
at the game's worker threads / waits).

### Build 184 result (log 2026-09-27 17:02): crash DURING "Compiling shaders" (97 %)
No GPU fault, no pipeline stall. The crash is the same memory race seen in
every earlier run, now clearly independent of the GPU: the view history shows
a 1 MB + 64 KB block (`0x110000`) CREATED by the main thread 69 s earlier and
DELETED by a JobWorker 4 ms before the main thread (or another worker) faults
memcpy'ing 1 MB out of it (source = block + 0x40). Same size and shape in
four runs. That is one thread releasing a buffer another is still reading —
on Windows the game waits for its jobs first, so a wait here returned early
or a signal arrived too soon. Prime suspect: Madeira's in-process fast path
for events/waits ("fastsync", `MADEIRA_FASTSYNC`, auto-enabled after 20k ops/10 s,
see `build/ntdll-unix` sync code).

**Build 185**: per-game switch "Safe thread sync (no fastsync)" in the game's
Launch options (sets `MADEIRA_FASTSYNC=0` for that launch). Test GoT with it ON.
If the race disappears, the bug is in fastsync (look for a wake that is
delivered before the waiter's condition is really satisfied, or a
`WaitForMultipleObjects(waitAll)` / auto-reset event edge case). If it still
crashes, add a watch: `vmwatch` in madeira.cfg cannot help (addresses differ
per run); instead log the guest call stack of the thread that frees a
0x110000 view (NtFreeVirtualMemory caller RIP) and of the reader.

### Build 185 attempted test (2026-09-27 18:21, log `GhostOfTsushima.exe-2026-09-27_18-21-33.txt`)
The game crashed again, but **this was not a fastsync-off test**: at log line
269 Wine says `[fastsync] ... mode=auto`, at line 15147 it says `AUTO-ENABLED`,
and subsequent `[perf]` lines count tens of thousands of fastsync hits. No
`[madeira-env]` line sets `MADEIRA_FASTSYNC`. The owner subsequently confirmed
that the per-game switch had not been enabled for this run.
`LaunchRequest.apply()` in `app/Madeira/HomeView.swift` does set the variable
to `0` when its saved
`safeSync` preference is true; the game's launched exe was the expected x64
`GhostOfTsushima.exe`, with AVX and NVIDIA reporting enabled. Re-check the
game's **Launch options > Safe thread sync (no fastsync)**, use **Save and play**
and confirm the next log says `[fastsync] ... mode=off` (the exact mode string
should be checked against the log). A fallback is `env.MADEIRA_FASTSYNC = 0`
in `Documents/madeira.cfg` for the experiment. Do not treat this run as
evidence for or against the fastsync hypothesis.

The original failure reproduced: a worker (tid `00f0`) deleted the
`0x706ed30000+0x110000` view **2 ms** before tid `00f8` read from
`0x706ed3c000` during a 1 MB copy (`c0000005`; `[fault-rgn]` lines
36299-36316). No new GPU timeout was logged. The process later ran the game
crash handler; its own faults are secondary. Next action is a true fastsync-off
run. If the same freed-while-read signature remains with `mode=off`, collect
the freeing and reading guest call stacks as proposed above.

### Build 185 valid fastsync-off test (2026-09-27 18:29, log `GhostOfTsushima.exe-2026-09-27_18-29-58.txt`)
The owner enabled the switch and got about **3–5 more seconds of gameplay**
before another crash (one run, so this is not established as an improvement).
Log line 273 says `[fastsync] ... mode=off (pre-ml952) peek=off`; all reported
`[perf]` fastsync hit/miss/peek counters remain zero. Thus fastsync was really
disabled, and disabling it alone did **not** prevent this crash. Do not
continue to treat the fastsync fast path as the sole cause.

At lines 36966–37076, the source address `0x70f0dd0040` belongs to a
`0x70f0dd0000+0x210000` Wine view created by tid `0024` about 8.6 s earlier
and **deleted by tid `00f8` 7–8 ms before the faults**. Threads `00ec`,
`00f0` and `0024` fault on reads from that source during 2 MB copies in
`ntdll.dll+0x64074` (different destinations). There was no new Metal command
buffer failure; the later `crs-handler.exe` faults are secondary. The log
proves a freed-while-read overlap, but does not yet prove whether the early
free is a game scheduling error, a different Madeira wait/signal problem,
or some other translation/VM behavior.

**Next diagnostic change (after this result):** `virtual_ios.c` captures the
release site on `NtFreeVirtualMemory(MEM_RELEASE)` for 1 MB+ guest-band views
and attaches it to the existing deletion-history record. On the next fault,
`[free-origin]` prints the native return address, FEX live and saved x64 RIP,
saved x64 RSP, and up to eight candidate return addresses within the main
exe (with RVAs) scanned from the saved guest stack. These are candidates,
not a verified unwind; compare them with the reader's existing `[callret]`
trace. The data prints only when a later fault overlaps the freed view.
Build and test this instrumented revision next; then identify the releasing
call site before changing scheduling or memory-lifetime semantics.
The diagnostic code and these notes were pushed together as commit
`6d758e544cffeff98ad8a7720b96690ec053cdc7` on the development branch.

**Build dispatch status (2026-09-27, Codex):** The owner authorized automatic
workflow dispatch after every error report, now recorded above. The GitHub
connector can push commits but does not expose `workflow_dispatch`; the
cloud-browser GitHub login reached the two-factor app-code step, then GitHub
returned “Your browser did something unexpected” after verification. A fresh
workflow tab remained signed out. No new workflow run or IPA has been created
yet; do **not** report build 186 as started. The development branch now includes
the diagnostic commit plus the handoff authorization note (`2e4de7f8`), while
`main` remains at the previous tested commit. Resume with an authenticated
GitHub Actions dispatch on `claude/madeira-bcd-repo-ymg5cb`, inspect the run,
and fast-forward `main` only after a successful build.

**Update 2026-09-27 18:53 (UTC+3):** The owner completed GitHub sign-in in the
cloud browser. Codex dispatched `build-ipa.yml` from
`claude/madeira-bcd-repo-ymg5cb` at commit
`0c925759891f7e63a2267faec2f63f63b34fbeb0`.
Workflow **#186**, run **36331180977**:
`https://github.com/bahacan16/madeira-bcd/actions/runs/36331180977`.
Initial status `in_progress`; await result and artifact before declaring an IPA
ready or advancing `main`.

**Build 186 result (2026-09-27 19:09 UTC+3): SUCCESS.** Run
`36331180977` completed successfully from commit `0c925759`; the `Archive
(unsigned)`, `Package unsigned IPA`, and artifact upload steps all passed.
Artifact **`madeira-0.1.186-unsigned-ipa`**, id `10935873381`, about 141 MB;
download it from the run page above while signed in to GitHub. This validates
compilation and packaging, **not** the on-device crash. The next device test
should retain AVX/NVIDIA settings and `Safe thread sync (no fastsync)` ON so
the new `[free-origin]` records can be compared with the build 185 mode-off
log. If it crashes, upload the complete session log. Compare the freed view,
release-site candidates and reader `[callret]` frames; do not infer an exact
caller from the stack scan alone.
After success, Codex fast-forwarded `main` to the development branch's
`1ec7af666a0cb4033c9ed51fb67045ea8ce129f8` documentation commit;
both refs matched. The final handoff update itself is documentation-only and
should also be fast-forwarded to `main`.

**About the Metal HUD suggestion "adopt MTL4Compiler"**: Metal 4
(iOS/macOS 26+) has `MTL4Compiler` (explicit compiler objects, async
compilation with QoS, `MTL4Archive`, flexible render pipeline states that
share compiled vertex/fragment code). Madeira's bridge (DXMT winemetal) is
written against the classic `MTLDevice newRenderPipelineState...` API and the
converter emits classic metallibs; moving to MTL4 means rewriting the
winemetal pipeline/command-buffer layer, a large job. The same benefits for
this problem (no main-thread compile stalls, reuse across launches) are
available with less risk via parallel builds (done) and `MTLBinaryArchive`
(item 1 above). The HUD's other hints ("high number of interleaved blit
encoders", "render passes with similar attachments") are performance notes,
not errors.

Note: `C:\madeira-cs\fault-shaders.txt` keeps hash 34c565ac8322ab2a, so every
launch logs that shader's bytecode once (harmless, ~8 log lines); delete the
file in the Wine prefix to stop it.

### Open issues, roughly in priority order (updated 2026-09-28 morning)
Build 203 was tested on the device (log `GhostOfTsushima.exe-2026-09-28_07-42-33.txt`):
the C++ fix was NOT applied (`[pc2fh] ... padding in use`), the water pipelines
failed at the vertex shader, the launcher stayed dark, the owner saw broken
rocks and occasional dark patches in the air. Build 204 fixes the first three
(see "Build 204" below); the rocks need a close-up screenshot.
1. **Verify 204 on the device** (`pso time (...)` lines say how much of
   "Compiling shaders" is Madeira's): `[pc2fh]` at start-up and no VCRUNTIME140_1
   crash after saving; `shader cache ON ... identity 'madeira_d3d12 bc1
   converter <hex>'` and mostly hits on the second launch; `[madeira-ir] MSC
   4.0.1 compatibility: position invariance on, strict NaN/Inf on, ...`;
   water: `DXIL tessellation: vs ...`, `[winemetal] DXIL tessellation pipeline
   OK`, `DXIL tessellation: N drawn` -- or the reason it stayed a placeholder.
2. **Remaining slight artefacts** (owner, after build 194): nature unknown until
   the screenshot. 198's flags are the best guess; if they persist, capture
   (CAP) a frame showing them.
3. **Performance**: 10-17 FPS in gameplay at 800x600. Frame 57-96 ms, GPU
   22-36 ms of it (33-60 % busy), ExecuteCommandLists 10-17 ms on the game's
   render thread, ~230 encoders a frame with a full fence chain (fence-chain
   1; mode 6 has a known flicker hole). Mostly the game's own x86 threads
   under FEX (TSO on, half barriers). Ideas: fewer useResource calls per draw
   (up to 64 + heaps), MTLBinaryArchive for pipelines, attachment store
   traffic (~500 MB a frame, 300-420 MB never read again).
4. **"Compiling shaders" on a warm cache**: ~650-700 stages/s (build 190 log,
   ~1.4 ms each) -- still one small file per shader plus ~11k Metal library
   creations. 197 halved the reads (one per hit). Build 203's `pso time (...)`
   lines split pipeline creation into conversion+cache, library creation and
   the rest; decide from them. If library creation dominates: create a plain
   pipeline's MTLLibrary/MTLFunction lazily in `mad_pso_realize` (the cache
   file is the backing store; D3D12 lets the app free its bytecode, so keep
   the cache key, never a pointer). If conversion dominates: one packed cache
   file with an index instead of ~30k files.
5. The launcher window stayed dark until Enter / gamepad X was pressed -- fixed
   in 204 (the direct-launch GDI overlay was never given its host layer).
6. `DXGIFactory::EnumAdapterByLuid` not implemented (Streamline only);
   non-occlusion queries resolve to zero; `ResolveQueryData` into GPU-only
   buffers is not delivered.
7. 32-bit games through WoW64: Crysis runs with small problems (not looked
   at yet); Crysis 3 (32-bit) exhausts the 4 GB guest window (advise Bin64 /
   lower settings).

## 5. Debugging toolkit built during this work

Log = the file the owner uploads (`GhostOfTsushima.exe-<date>.txt`). Useful greps:

| grep | meaning |
|---|---|
| `GPU fault encoders: code N` | failed command buffer; code 2 = timeout, 3/4 = page fault/ignored; `[FAULTED] C#<seq> <kernel> fn=...` names the encoder |
| `GPU fault dispatch C#` | bindings of the faulted dispatch (root params, descriptors resolved to resources, `RUNS PAST THE END`) |
| `[b64 <hash>]` | bytecode of a faulting compute shader, logged at the NEXT launch (also `C:\madeira-cs\fault_<hash>.dxil`) |
| `shader cache: N hits` / `shared shader libraries` | disk cache / library sharing |
| `currentAllocatedSize`, `[footprint]`, `[proc-mem]` | Metal memory and process footprint (limit 8192 MB) |
| `[fault-rgn]   history:` | who created/deleted the view at a faulting address (1 MB+ views) |
| `[stack-quarantine]` | a dead thread's stack was touched while quarantined |
| `[va-scan] FAILED ... STATUS_NO_MEMORY` | address-space exhaustion |
| `[wow-window] ... placed above them` | 64-bit views placed above the 32-bit slots |
| `skips by site` | draws/dispatches skipped (L<line> in madeira_d3d12.c) |

Disassembling a captured shader:
```
grep -a "^\[b64 <hash>\]" log.txt | sed 's/^\[b64 [0-9a-f]*\] //' | tr -d '\n' | base64 -d > s.dxil
pip install llvmlite
python3 tools/dxil-disasm.py s.dxil > s.ll
```

madeira.cfg keys added here: `shader-cache` (default 1), `pso-lazy` (1),
`gpu-fault-info` (1), `gpu-fault-skip` (1), `encoder-labels` (0),
`vmwatch = 0x<addr>` (existing). Env: `MADEIRA_IR_NO_BOUNDS_CHECK=1`.

Metal Shader Converter headers for reading (never commit): download the pkg
from the draft release through the API, unpack xar -> Payload (pbzx/cpio) ->
`usr/local/include/metal_irconverter{,_runtime}/`. Key facts learned there:
descriptor heap bind point 0, sampler heap 1, top-level argument buffer 2;
UAV counters are an R32Uint texture-buffer view in the descriptor's texture
id word with the element offset in metadata bits 32..39
(`IRRuntimeCreateAppendBufferView`); buffer metadata = size | texview offset
<<32 | typed<<63.

Local compile check of `madeira_d3d12` (no device needed): llvm-mingw
`arm64ec-w64-mingw32-clang -shared -O2 -Wall madeira_d3d12.c d3d12.def -I...
-lwinemetal -luuid -lole32` with an import lib generated from
`research/dxmt/src/winemetal` exports (gendef/dlltool). The Wine unix side
(`build/ntdll-unix/*_ios.c`) only compiles in CI (Darwin/Mach headers).

## 6. Where things live

* `research/madeira-d3d12/src/pe/madeira_d3d12.c` — the D3D12 runtime (PE,
  ARM64EC). Most GoT fixes are here.
* `research/madeira-d3d12/src/unix/madeira_ir_unix.mm` — shader conversion
  service (Metal Shader Converter / airconv), unix side.
* `research/dxmt` (submodule, 125hz fork) — winemetal bridge; patched at build
  time by `tools/patch-dxmt-*.py` (the submodule itself is not modified).
* `build/ntdll-unix/virtual_ios.c`, `thread_ios.c` — Wine VM/threads on iOS
  (address-space windows, swap tier, view history, stack quarantine).
* `build/win32u-unix/sysparams_ios.c` — display devices / virtual GPU registry.
* `app/Madeira/*.swift` — the app (library, per-game settings incl. AVX and
  "Report an NVIDIA GPU").
* `.github/workflows/build-ipa.yml` — the whole build.

### Build 186 (ChatGPT/Codex) and 187 (Claude), 2026-09-27 evening
* Build 185 with "Safe thread sync" ON (fastsync `mode=off`) still crashed the
  same way, so fastsync is NOT the cause (Codex's notes above).
* Build 186 (Codex) only added free-origin tracing (`[free-origin]` lines
  under `[fault-rgn] history`). Its device run crashed at ~80 % of "Compiling
  shaders" with a different signature: Metal's completion handler
  (`IOGPUMetalCommandBufferStorageDealloc` -> `objc_release`) released a
  corrupted object (`x0=0x10701`), and a Wine thread crashed in `objc_release`
  on the same value. Reading: the same freed-while-used race — the game keeps
  touching a block after it was released, the VA has meanwhile been given to
  Metal/malloc, and Metal's objects get scribbled on. No `[free-origin]`
  output in that run (no guest fault on a freed view).
* **Build 187 (mitigation, not a root-cause fix)**: DELAYED RELEASE in
  `NtFreeVirtualMemory` (`build/ntdll-unix/virtual_ios.c`, `ios_fd_*`): a
  whole-view MEM_RELEASE of a private 1-16 MB guest-band allocation returns
  success at once but the mapping stays committed for `MADEIRA_FREE_DELAY_MS`
  (default 2000; 0 = off), max 128 MB in flight, then is really released.
  Late readers find valid memory and nobody else gets that VA meanwhile.
  Log: `[free-delay] #N release of ... held for 2000 ms`.
  If GoT gets through gameplay with it, the underlying race (job refcount /
  wait ordering under FEX) is still worth finding with the free-origin trace
  (set `MADEIRA_FREE_DELAY_MS=0` in madeira.cfg `env.` to reproduce).

### Build 187 result (log 2026-09-27 20:20, 1024x768, Adaptive Power was on)
* **The freed-while-used crash is gone.** The whole opening scene played for
  ~3 minutes, horse riding and control hand-over worked, the owner played ~2
  minutes with the touchpad, opened the menu and saved. `[free-delay]` held
  8 releases (1-8 MB each). Footprint peaked at 7.34 GB (limit 8 GB).
* HUD: GPU 14-44 ms/frame, 10-32 FPS; Metal warns about many render passes
  with similar attachments, interleaved blit encoders and runtime pipeline
  compiles (1000-1600 pipelines compiled during play). The log's render pass
  report: `ended by: targets 298, clear 77, dispatch 370 ... attachment
  load+store ~14848 MB` per 600 lists -- merging passes is a real FPS lever.
* Black squares (fixed screen positions, ~64 px) and a green block pattern in
  the lower part of the image remain. Still unexplained; a Metal frame
  capture (Mac + Xcode) is the fastest way to name the pass.
* **New crash after the save**: main thread AV READ of 0x16694 in
  VCRUNTIME140_1 (x64, `__CxxFrameHandler4`): `mov r12d,[rax+rbx]` with
  rbx = ThrowInfo->pCatchableTypeArray RVA and rax = `_GetThrowImageBase()`
  = 0. So a C++ exception arrived with ThrowImageBase (parameter 3) = 0.
  The stale guest state had rax = 0x11fb3e6a0, a JIT-pool alias inside
  msvcp140.dll's pool copy -- i.e. the ThrowInfo pointer was probably a pool
  VA, which `RtlPcToFileHeader` cannot map to a module. (The later crash of
  thread 0x50 is crs-handler.exe, the game's crash reporter, reacting.)
  The PE ntdll (`app/Madeira/arm64ec-windows/ntdll.dll`) is a tracked
  upstream binary and is NOT compiled by CI, so `RtlPcToFileHeader` cannot be
  fixed there.
* **Build 188**: unix `NtRaiseException` (`build/ntdll-unix/thread_ios.c`)
  repairs 64-bit C++ throws (0xE06D7363, 4 parameters) before dispatch: a
  pool-alias ThrowInfo is mapped back to the PE VA and its module base is
  filled in; a base of 0 is filled from the owning MEM_IMAGE allocation.
  Log: `[cxx-throw] #N ThrowInfo ... base ... -> ...: <how>` (first 32) and
  `[cxx-throw] ok ...` for the first 4 normal throws. If the crash returns
  WITHOUT a `[cxx-throw] #` line, parameter 3 was fine and the vcruntime
  per-thread data (`_ThrowImageBase` in the FLS ptd) is the suspect instead.

### Build 189: contact sheets for the black squares (no Mac needed)
The owner will not have a Mac soon, so visual bugs must be diagnosed from the
phone. Build 189 adds CAP contact sheets (docs/madeira-bcd.md): press CAP in
the overlay while the black squares are visible; `Documents/capture/` then
holds `f<frame>_sheet00.png ...` (20 numbered thumbnails each) and
`f<frame>_sheets_index.txt`; the log has the same `[capture-sheet]` lines.
Ask the owner for the sheets (as images) plus the log. Reading them: find the
first thumbnail (in encoder order) where the squares appear, magenta = NaN/Inf.
If it is a `cs <hash>` thumbnail, that dispatch produced them: next step is
`capture-cs` / the fault-shader machinery on that hash (dump its DXIL with
`tools/dxil-disasm.py`). Build 189 also carries build 188's C++ throw repair.

### Build 190 capture result (log 2026-09-27 21:15, main menu, 800x600)
Contact sheets work (283 thumbnails, 15 sheets). Findings:
* The main depth-stencil (800x600 D32S8, "DepthTarget") is clean after the
  G-buffer passes (#249, enc#179408, depth 0..0.057) and has **14336 NaN
  texels in a regular grid of small squares** at the next pass (#252,
  enc#179423 `PsMain`, which does not write depth: `w0`). The stencil plane
  (#253) shows the same grid plus garbage blocks = the green block pattern.
  The black squares in `PsMain`'s output (#251) sit exactly on that grid.
  Between the two passes only compute dispatches run (cs_main 100x75x1,
  13x10x1, 1x1x1, 11 indirect, 1x16x16), none with a bounded texture UAV.
* The previous frame's HDR image (#148, RGBA16F, probably TAA history)
  carries the same NaN squares, so they also feed back frame to frame.
* The 5th G-buffer target (RG16F, dx34, likely velocity) is NaN/Inf over the
  whole sky (#167/#174/#202); its clear is not visible (clear-only passes
  are not captured).
* Hypothesis: memory aliasing. DEFAULT heaps are Metal placement heaps
  (ml1145, `heap-backing = 1`); GoT uses many RT/DS-only heaps (flags 0x84).
  A resource placed over the depth memory and written by one of those
  dispatches (or a copy) would corrupt it in a grid, since Metal's tiled
  layouts differ by format. Build 191 adds the alias report to prove or
  refute it: look at the `| r#N heapH +a..b, OVERLAPS: ...` tail of the
  depth's `[capture-sheet]` lines, then `[capture-uavbuf]` / `[capture-op]`
  for a writer of an overlapping resource. If depth overlaps nothing, the
  NaN depth is a second DepthTarget (compare r# of #249 and #252).
* The second CAP of build 190 hung the game: thumbnailing a BC1 texture
  (captured as a UAV target) read past its copy while holding the capture
  lock. Fixed in 191 (BC skipped, reads bounds-checked).

### Build 191 results (logs 2026-09-27 21:46 and 21:48)
* Run 1 died before the main menu with the SAME C++ exception crash as after
  the save in build 187 (AV READ of 0x16694 in VCRUNTIME140_1, handler
  GhostOfTsushima.exe+0xd15f0c). No `[cxx-throw]` line: build 188's repair in
  unix `NtRaiseException` is never reached, because ARM64EC
  `RtlRaiseException` (wine/dlls/ntdll/signal_arm64ec.c) dispatches in user
  mode unless `peb->BeingDebugged`; only the second chance goes to the
  syscall. The PE ntdll is a tracked binary, so the fix has to live somewhere
  else (open; needs a deeper look -- where does the zero ThrowImageBase come
  from: the record, or vcruntime's per-thread `_ThrowImageBase`?).
* Run 2: pressing CAP crashed in `mad_texel_rgb` (madeira_d3d12+0x19478,
  default case): the capture copy's Metal-allocated shared memory was not
  mapped any more (prot 0). Build 192 backs capture copies with our own
  VirtualAlloc memory (no-copy Metal buffer) and locks the list in
  `mad_capture_buffer` too.
* **The aliasing hypothesis is refuted**: not a single `[placed]` line --
  GoT never calls CreatePlacedResource; its heaps stay empty, the depth is a
  committed resource. New leading hypothesis: a compute UAV descriptor holds a
  texture resource id that now belongs to the depth texture (a stale id of a
  released texture, reused by Metal), so a dispatch writes into depth. Build
  192 logs `[capture-uavtex]` for every UAV texture id (bounded ranges and
  the first 64 of unbounded ones) that resolves to no live texture or to a
  render-target / depth texture.

### Build 192 result (log 2026-09-27 22:18): black squares ROOT CAUSE found
Two CAPs worked (no crash). Frame 2311: the depth r#465 is clean at
enc#197148 (`ps_Copy`) and has 14336 NaN at enc#197163; `[capture-op]` in
between: `copy texture r#465 -> ... r#241` (stencil plane to an 800x600 R8
texture) and `copy texture r#241 -> r#465 mip 0 slice 1` -- D3D12
subresource 1 of a one-layer D32S8 resource is the STENCIL PLANE, which
Madeira decoded as array slice 1, so the copy wrote past the texture over
its depth and stencil memory. Build 193 decodes planes and copies aspects
properly (docs/madeira-bcd.md "Depth-stencil planes in copies"). Also seen:
UAV descriptors holding texture ids that resolve to no live texture (0x6cdc..
0x6cde, many shaders) and cs 3bc86a8a91b059a4 u8 resolving to the depth
(probably unused table slots; watch after the fix).
* Longer play in the same build-192 run (log 2026-09-27 22:18, part 2): no
  crash, footprint peak 6.6 GB. When the owner switched apps, iOS refused the
  GPU work ("Insufficient Permission (to submit GPU work from background)",
  code 7); Madeira took that for a GPU fault and switched the fault
  diagnostics on for good (every compute dispatch in its own encoder = slower
  for the rest of the run). Build 194 ignores that error for diagnostics.

### Build 194 result (log 2026-09-27 22:49): black squares FIXED
Owner: ~90 % of the corruption gone, only slight artefacts left. The capture
shows no NaN in the depth any more; the stencil round trip runs as
`aspect copy r#465 stencil -> r#241 colour` and back. Remaining NaN: the
RG16F G-buffer target r#483 (likely velocity) is cleared BY THE GAME with a
NaN colour (`[capture-op] clear RT (-nan ...)`), so that one is intentional.
The C++ exception crash (VCRUNTIME140_1, AV READ of 0x16694) happened again
at the end of the run -- the next main task. Owner has been told to raise the
effort level for it.

### C++ exception crash: ROOT CAUSE and build 196 fix
Analysed with Microsoft's 14.44 runtime (msvc-runtime wheel from PyPI, only
for disassembly, never committed): the fault is `mov r12d,[rax+rbx]` at
VCRUNTIME140_1+0x17b4 in FH4's FindHandler, rax = `_GetThrowImageBase()` = 0.
FH4 copies the throw image base from ExceptionInformation[3] at entry. MS's
`_CxxThrowException` would have switched the magic to 0x01994000 (pure) on a
zero base, so the record came from WINE's builtin runtime: Madeira keeps
Wine's ARM64EC vcruntime140 + msvcp140 (WineProcessBridge.m exemptions) but
overlays MS vcruntime140_1/concrt140. At RVA 0x166a0 of the shipped
arm64ec-windows/msvcp140.dll sits a ThrowInfo whose CatchableTypeArray RVA is
0x16694 -- the fault address -- type `std::runtime_error`; build 187's stale
rax was exactly that ThrowInfo's pool alias. Wine code computes the pointer
PC-relative in its JIT-pool copy, RtlPcToFileHeader(pool VA) returns 0.
Build 196 patches RtlPcToFileHeader's pool copy to reverse-translate first
(`[pc2fh]` log line at start-up). (Run 195 was the automatic build of the
main push of build 194's commits -- same content as 194; the fix is 196.) The same crash hits every game that mixes
Wine's msvcp140 with MS's vcruntime140_1 and catches a Wine-thrown exception.
Verified offline against the shipped ntdll.dll with a harness (patch lands on
RVA 0x35ea0, trampoline at RVA 0x8ffc0, idempotent).

### Build 197: the shader cache survives new builds
Every build used to start the device's shader cache from nothing (its key
held the DLL's compile time), so each new build sat on "Compiling shaders"
while ~29,000 stages converted again, and a DXIL miss ran the converter
twice. Build 197 keys the cache by a converter identity the CI computes from
everything that can change a conversion (docs/madeira-bcd.md, "Persistent
shader cache") and converts a miss once. The first launch of 197 still
converts everything (new identity); from then on a build that does not touch
the converter, DXMT's airconv, LLVM or the MSC library starts with a warm
cache. Log: `shader cache ON: ... identity 'madeira_d3d12 bc1 converter
<16 hex>' (vsps-fill 1, no-bounds-check 0, ags-roundtrip 0; ...)`; the
`shader cache: N hits, M misses` lines should show almost only hits on the
second launch.

### Build 198: converter flags for the remaining slight artefacts
Build 194's remaining artefacts are "slight" (screenshot pending). Two MSC
defaults differ from D3D12 in ways that produce exactly that kind of damage,
and the build-194 capture shows the game depends on both: ~350 draws a frame
redraw geometry with depth test EQUAL (D3D12 func 3, `dtest=1/func3/w0` in
`[draw-dump]`: cloth, moving objects, hair) -- without position invariance
Metal may compute those positions differently from the depth pre-pass --
and the game clears its RG16F velocity target to NaN on purpose, while MSC
4.0 optimises on the assumption that no value is NaN. Build 198 converts
with position invariance, strict NaN/Inf and sampler LOD bias
(docs/madeira-bcd.md). Each is a madeira.cfg switch (`msc-position-invariance`,
`msc-strict-nan`, `msc-sampler-lod-bias` = 0) for an A/B run; each switch
change re-converts every shader once. If the artefacts are gone but FPS
dropped, try `msc-strict-nan = 0` first (the likely costliest).

### Build 199: DXIL tessellation (the missing water)
Every run logged 12-16 "tessellation pipeline could not be built; returning a
placeholder whose draws are skipped" -- all of them Ghost of Tsushima's WATER
pipelines (`ls_Main_techWaterBlend`, `ps_Main_techWaterMain`,
`ps_WaterHeight_techWaterHeight`): DXIL hull+domain shaders, and the runtime
only had DXMT's emulation for DXBC ones. Build 199 builds them through the
Metal Shader Converter's own tessellation emulation (docs/madeira-bcd.md). Not
testable off the device: check the log for `DXIL tessellation: vs ...` (pipeline
converted), `[winemetal] DXIL tessellation pipeline OK` (Metal accepted it) or
`... REFUSED` / `Metal refused it` (with the reason), and `DXIL tessellation:
N drawn` in the ml1050 lines. If water scenes misbehave (GPU fault, hang),
`dxil-tess = 0` in madeira.cfg restores the placeholders. The workflow now
FAILS when madeira_d3d12.dll does not build (it used to ship upstream's old
tracked DLL and stay green).

### Build 201: housekeeping on the phone's storage
* ml931 wrote the first 400 compute shaders of every launch to
  `C:\madeira-cs\cs_<pipeline pointer>_<size>.dxil`; the pointer differs per
  run, so every launch added up to ~16 MB that nothing removed. Now opt-in
  (`cs-dump = 1`); the old dumps are deleted in the background (log: `removed
  N old compute-shader dumps`).
* The unix DXBC cache (`Documents/shadercache/*.mdsc`) got a fresh set per
  build and never lost the old ones; entries of earlier builds are removed
  once per build (log: `DXBC shader cache: removed N entries`).

### Builds 228-234: God of War hangs at start (presents 0), 2026-09-29/30
Tried and ruled out one by one on the device (each a separate build): madsync
off, 125hz's early JIT pool (6c944a6: upstream's placement again),
swap-min-kb, 125hz's decommit_pages (0046bce). Upstream's own build of the
same game was never tested here.
* Build 230 (2f8a0f4): the 2 s watchdog prints `[guest-stk]` lines for a
  thread parked in a syscall (TEB+0x378 syscall frame, fp chain, stack scan,
  JIT addresses reverse-mapped to module+offset). FEX offsets are symbolized
  with `llvm-nm -n -C` of the SHIPPED xtajit64.dll (RVA = addr - 0x180000000);
  since build 231 the shipped module is a CI rebuild, so the committed DLL's
  symbols are off by a few hundred bytes after Module.cpp.
* Build 231 (3705656, tools/patch-fex-ios-mapview-selfshared.py): guessed a
  self-wait on CodeInvalidationMutex in NotifyMapViewOfSection. Its log line
  (`[img-map] madeira-bcd`) never appeared; still hangs. The patch is kept
  (harmless).
* The build 230 stack, symbolized properly, is a self-wait on
  InvalidationTracker::IntervalsLock (std::shared_mutex, not recursive):
  HandleMemoryProtectionNotification holds it and logs `[iOS-xrem]` -> the
  log line grows FEX's heap (rpmalloc heap_get_page_generic) -> VirtualAlloc
  -> NotifyMemoryAlloc -> HandleMemoryProtectionNotification -> the same
  lock. Build 234 (840d90f, tools/patch-fex-ios-intervals-reentry.py; run 233
  was cancelled by mistake): the
  lock remembers its exclusive owner (TPIDRRO_EL0 on iOS); the memory
  notifications return at once on that thread and are counted
  (`[iv-reentry]` from HandleImageMap). Device test pending; then madsync and
  swap-min-kb back on for GoW one at a time.
* Build 234 on the device (logs 2026-09-30 08:57 and 08:58): the hang is
  gone. GoW now gets past imm32, loads concrt140/vcruntime140_1, starts its
  job-manager threads, initialises d3d11/dxgi (video budget, the 1368 MB and
  1026 MB reservations) and then faults the same way both times: guest code
  reads 0x40 (host LDAPR x27,[x6], x6 = 0x40; State.RIP 0x14002c4e0, callret
  [0] 0x14017d7a2, [1] 0x14002c4f0), host sp 0x71fe3c0000. The pre-switch
  build (125hz, log 2026-09-29 13:48) passes the same point: the exe was
  relocated to 0x15f210000 there, the 2 MB commit in the 1026 MB reservation
  was swap-backed (swap-min-kb), and crs-client.dll loaded next. Build 236
  logs every register, 256 bytes of host code before the fault
  ([fault-full], [fault-host]) and the guest bytes of the two innermost
  frames and their direct-call targets ([guest-fn]).
* Build 236 (log 2026-09-30 09:28) names it. A static constructor
  (0x14002c4e0, from the CRT's initterm at 0x140664xxx) builds a global at
  0x1427d27f0 with ctor 0x14017d750, which allocates 0x1000 bytes through
  the thread's current allocator: GoW.exe's own TLS block (TLS[0]) holds an
  index at +0xc and a table at +0xf0; the index is negative or the entry is
  0, so the allocator is NULL. 0x14040bf10 then finds TLS[0]+0x18 == 0 too
  (the other path) and reads NULL->0x40. The TLS setup order is identical
  in the pre-switch log that passes this point, so an earlier initializer
  took another path. Only visible difference at that point: the 2 MB commit
  at the start of the 1026 MB reservation was swap-backed there
  (swap-min-kb 1024) and is plain memory now. Next test: swap-min-kb = 1024
  back in GoW's config.
  Tested (log 09:32, build 236 with swap-min-kb = 1024): the commit is
  swap-backed again and the fault is unchanged -- not the swap tier. Build
  237 prints the thread's TLS[0] block and the image's TLS template at the
  first unhandled fault ([fault-tls]).
* Build 237 (log 09:53): GoW.exe's TLS template has the allocator-stack
  index at +0xc = -1 (empty); the main thread's block has +0xc = 0 and the
  table at +0xf0 holds [0] = 0, [1] = 0x7158890000 (the 1026 MB arena from
  jumbo#2). So the arena was pushed one slot too high, or something pushed
  NULL first, or +0xc was reset to 0 before the push (a 64-bit store to +0x8
  would do that). Other changes vs the template: +0x28 = 0x14506ce60,
  +0x58 low dword 0x80000000 -> 0x80000005. Finding the writers needs the
  code: GoW.exe itself (the owner's copy, analysis only, never committed).
* GoW.exe (owner's copy, kept out of the repo) disassembled: the allocator
  stack is push `idx = movsxd [tls+0xc]; [tls+0xc] = idx+1;
  [tls+0xf0 + 8*idx + 8] = heap` (14 inlined sites, e.g. 0x14040a8f0),
  pop `[tls+0xc] = idx-1`, and one restore (0x14040b2f0) that zeroes the
  table above the restored count; nothing else stores into the table. The
  memory init at 0x14040a8a3 pushes heap A (an object in .data at
  0x1426d18b0 + n*0x238, never NULL) right after the 1368 MB VirtualAlloc,
  then the 1026 MB arena (0x14040aa2f -> 0x1404ad5c0), then pops once. The
  observed state (index 0, table[0] 0, table[1] arena) is what you get if the
  first push, the one with index -1, never reached table[0]. No module has an
  unslotted static TLS (checked every DLL the log loads). Build 238 prints
  the stack at each of the first four jumbo reservations ([jumbo-tls]):
  jumbo#1 is heap A's VirtualAlloc (before the push), jumbo#2 the arena
  (after it).
* Build 238 (log 10:28): [jumbo-tls] #1 (before the game's first push)
  already reads index 0, and #2 (right after the push of heap A into
  table[1]) reads index 0 again; the arena push then overwrote A. So
  something outside the game zeroes TLS[0]+0x8..+0xf. It is FEX:
  xtajit64's own TLS template (0x30 bytes) holds `thread_local IRCapRIP`
  (PassManager.cpp, ml623 IR capture) at offset 8, Core.cpp clears it at the
  start of every block compile, and in the ARM64EC module that implicit-TLS
  access lands in the executable's TLS[0] block (implicit TLS is banned in
  xtajit64 for this reason; the WOW64 module already uses an atomic). Build
  239: tools/patch-fex-ios-ircap-tls.py makes it an atomic in the ARM64EC
  module as well. The other xtajit64 thread_local (AllocWatch's Anchor, +0x10)
  only has its address taken.
* Build 239 on the device (logs 10:49, 10:50, 10:51): past the allocator
  fault; Metal HUD up, the Sony Interactive Entertainment intro video plays
  for about a second, then it stops. Two of three runs: the unaligned
  backpatch race. Several video/decode threads run the same block; the Mach
  exception server rewrites LDAPR/STLR -> LDR/STR (+ half-barrier) for the
  first fault, then reads the next thread's (already queued) alignment fault
  with the plain form in place, matches nothing and sends it on as unhandled
  (`ldr x8,[x27,xzr]` / `str xzr,[x6,xzr]`, kr=0x101, same pc, x18 differs).
  Build 240: kr == EXC_ARM_DA_ALIGN on a rewritten form whose barrier slot is
  in place is re-run (pc for loads, pc-4 for stores) ([mach_exc]
  UNALIGNED-REPATCHED). Third run: FEX native code with x18 = 0 read
  TEB->TlsSlots[1] (addr 0x1488, pc libarm64ecfex+0x12f908) -- the iOS x18
  problem in FEX's TlsGetValue shim (Source/Windows/Common/WinAPI/Alloc.cpp,
  GetCurrentTEB() = NtCurrentTeb() = x18). Build 241 (240 superseded while
  running): tools/patch-fex-ios-teb-tsd.py makes the ARM64EC module's
  GetCurrentTEB() read the TEB from the TSD slot (TPIDRRO_EL0 +
  IosTebTsdOffset, as IOSLoadTEB does), x18 only as the fallback.
* Crysis64 (log 2026-09-30 11:05, build 239): the same fault as every run
  since 2026-09-26: CrySystem.dll+0x79788 reads through a pointer whose high
  32 bits are gone (0x264d004c; the full value 0x70264d055c sits in x1).
  CryEngine 2's 64-bit build relies on heap addresses below 4 GB, which
  Windows' bottom-up allocation gives it; iOS reserves the whole low 4 GB as
  __PAGEZERO, so no allocation can land there. Not fixable in the allocator;
  32-bit Crysis is the route.
* 32-bit Crysis (log 11:06): dies before any game code. aarch64 wow64.dll is
  relocated off its preferred base, the loader binds its IAT (.rdata page
  +0x33000), the read-only restore fails (`[vmem-denied] set_vprot failed
  ... protect=0x2`), so NtProtectVirtualMemory's IAT sync into the JIT-pool
  copy never runs; Wow64LdrpInitialize (+0x1b5fc) calls through the copy's
  unbound slot = hint/name RVA 0x34f06. Build 242: a refused read-only restore
  inside a pool-copied image leaves the page as it is, reports success and
  lets the sync run ([vmem-denied] madeira-bcd: restore ... refused).
* Build 241 on the device (logs 11:20, 11:21): the repatch works (16
  [mach_exc] UNALIGNED-REPATCHED per run); one run got through the intro
  videos (choppy) and stopped as the main menu appeared. Next fault, both
  runs: `ldaddal w7, w8, [x6]` on 0x...b6267e (guest 0x1408df521, x86 lock
  add/xadd on a misaligned dword), which only the LL/SC and CAS forms were
  emulated for. Build 243: LSE atomics (LDADD/LDCLR/LDEOR/LDSET/LD{S,U}{MAX,MIN}
  and SWP, any A/L) on a misaligned operand are emulated on the exception
  server like CAS ([mach_exc] UNALIGNED-LSE). The owner's madeira.cfg still has
  inproc-sync = 0 from the hang hunt (madsync off), a likely part of the
  choppiness.
* Build 243 (log 11:55, madsync back on): no unhandled fault at all; 11
  [mach_exc] UNALIGNED-LSE (ldaddal) and 16 UNALIGNED-REPATCHED handled. The
  game ran 55 s and was killed by jetsam: footprint 8178 of 8192 MB
  (internal ~3.0 GB, compressed ~3.3 GB, external ~0.55 GB, swap tier 2.1 GB
  file-backed). The pre-switch runs sat at the same edge (peaks 7687 and
  7984 MB) and survived. Next: memory pool (mempool-mb, upstream's
  MadeiraMemoryHost) and/or swap coverage "wide", one at a time.
* 32-bit Crysis on build 243 (log 11:57): the IAT fix works (wow64.dll,
  libwow64fex, ucrtbase, kernel32, kernelbase all bind; 20+ `[vmem-denied]
  madeira-bcd: restore ... refused` lines), wow64 initialises and the game's
  own code runs (creates C:\users\...\My Games\Crysis, LogBackups). Then
  CPUID 0x80000002: FEX's Function_8000_0002h indexes PerCPUData with the raw
  host CPU number (1 entry on iOS, CPU 3+) and strlen()s a garbage pointer
  (0xfff68000; pc ntdll strlen, lr xtajit.dll Function_8000_0002h+0x30).
  RunFunctionName wraps the index, the leaf entry points did not. Build 244:
  tools/patch-fex-ios-cpuid-index.py for both modules; the WOW64 module
  (xtajit.dll, until now built by hand with build/fex-wow64/build.sh) is now
  built in CI by tools/build-xtajit-wow64.sh (cached FEX/build-wow64; the
  committed module stays if the build fails or its exports differ).
* 32-bit Crysis on build 244 (log 12:25): past CPUID; loads CryGame,
  CrySystem, CryAction, d3dx9/d3dcompiler_43, CryInput, CrySoundSystem
  (fmod), CryFont, CryAISystem, CryAnimation, Cry3DEngine, CryScriptSystem,
  CryEntitySystem; 489 presents in the first 30 s; ran ~4 minutes compiling
  shaders (d3dcompiler reflection fixmes). Then libwow64fex+0x11f644: the
  TlsGetValue shim with x18 = 0 read TlsSlots[20] at 0x1520 -- the same
  GetCurrentTEB() problem as GoW's on ARM64EC. Build 245 applies
  tools/patch-fex-ios-teb-tsd.py to the WOW64 module too (its IosTebTsdOffset
  is published into the same extern "C" variable).
  (That build ran as run 246, e449b17; main fast-forwarded to it.)
* Crysis intro videos, 30 s pause between each (same log, owner: "every gap
  about a minute, the videos themselves smooth"): the gaps are exactly 30.0 s
  of near-idle CPU (12:25:49.7 -> 12:26:19.7, 12:26:38.6 -> 12:27:08.5, ...).
  The video thread (00b8, then 00dc) calls SuspendThread on ITSELF every frame
  and is resumed by the main thread. On iOS a self-suspend never stops the
  thread (SIGUSR1 never reaches usr1_handler, task #32), so it spun ~46k
  SuspendThread/s and the server count sat at MAXIMUM_SUSPEND_COUNT
  ([srv-suspend] "count 127->127"). When the video ended the thread reached
  NtTerminateThread(self), whose zero-timeout server_select waits while the
  thread is suspended -- forever (teb 0x7103090000 parked in
  wait_select_reply for the rest of the log; no "read_request EOF" for 00b8
  or 00dc), so the main thread sat out a 30 s join timeout. Build 247:
  NtSuspendThread (build/ntdll-unix/thread_ios.c) waits like wait_suspend()
  when the target is the calling thread ([self-suspend] log line).
* Build 247 on device (log 2026-09-30 13:19 + screen recording): the intro
  gaps are gone ([self-suspend] #1.. for tid 00b8) and Crysis reaches the
  first level (beach, nanosuit boot HUD) at ~55 FPS, GPU ~5-6 ms, via
  CryRenderD3D10 -> DXMT d3d11 (feature level 10_0). Rendering bug: parts of
  the scene (nearby foliage, it looks like) are replaced by long vertical --
  and some horizontal -- streaks spanning the screen, i.e. vertices thrown far
  out (clip w near 0 or garbage) rather than a texture problem; rocks, beach,
  trees at distance, weapon and HUD are fine. No DXMT warnings in the log.
  There is no D3D11 capture tool yet (CAP sheets are madeira_d3d12 only).
  Asked the owner to bisect with the in-game Advanced settings (all Low, then
  raise Objects / Shaders / Game Effects one at a time) and to try the `-dx9`
  launch argument (DXMT d3d9 path) for comparison.
* Second recording (13:55): settings had been at Low; raised a notch, far
  vegetation renders correctly and the broken shapes change: streaks radiate
  from vanishing points (vertical toward zenith/nadir, horizontal toward the
  horizon), so vertices of some nearby meshes are displaced very far in WORLD
  space, not a screen-space pass. Reviewed and ruled out as obvious causes:
  airconv vertex-format pulling (half/snorm/BGRA paths look right), wine's
  d3dcompiler reflection (skips are STAT/signature padding; D3D10 GetDesc
  maps to D3D10_SHADER_DESC). Open candidates, none proven: (1) constant
  buffers bound smaller than the shader declares -- airconv loads cb[] with no
  bounds and Metal has no robustness, so D3D's zero-fill becomes garbage
  (a fix needs the declared size at encode time; MTL_SM50_SHADER_ARGUMENT is
  also mirrored in research/madeira-d3d12/src/madeira_ir_abi.h, so do not
  grow it without updating both); (2) 16-bit index buffer offsets that are
  2 mod 4 (odd StartIndexLocation) passed straight to Metal. The -dx9
  comparison is still pending.
* -dx9 renders Crysis correctly (owner, 2026-09-30) but at ~28 FPS instead of
  ~55-60 (the S25 Ultra runs it at ~110 FPS with DXVK 2.7.1), so the D3D10
  path is the one to fix. Build 248: tools/patch-dxmt-cb-short.py parses each
  shader's dcl_constantbuffer sizes (SHDR/SHEX, no airconv ABI change); a
  bound buffer shorter than declared gets a zero-padded copy in the encoder's
  argument buffer, refreshed every draw ([cb-short] lines), and 16-bit index
  offsets that are not a multiple of 4 are counted ([idx-align], log only).
  It only reaches 32-bit games: the i386 farm is rebuilt from research/dxmt,
  the 64-bit PE d3d11.dll is still the committed binary. If [cb-short] never
  appears, candidate (1) is refuted.
* Performance (the -dx9 log 14:53 and the D3D10 log 13:19 alike): the main
  thread 0024 ran 0 ms on P-cores and ~600 ms/s on E-cores (2.1-2.6 GHz),
  [cpu-split] 88-97 % x64 JIT, while the game's time-critical thread (0060)
  ran on P-cores at 4.2 GHz. wineserver's apply_thread_priority (__APPLE__
  branch of wine/server/thread.c) sets Mach precedence/throughput/latency
  policies from the Windows priority at thread start; for NORMAL threads that
  appears to override the USER_INTERACTIVE QoS the guest threads ask for.
  Build 249: tools/patch-wine-thread-qos.py skips those policies below the
  realtime band on WINE_IOS ([thread-prio] lines;
  MADEIRA_WIN_THREAD_PRIORITY=1 restores them). Check [xp-t] for 0024's P ms.
  The owner also has the in-game 60 FPS cap on; to be turned off for the test.
* Build 249 on device (log 15:46, 60 FPS cap off): ~92 FPS, GPU ~4 ms; the
  streaks remain, and the owner saw that they only appear where trees or
  branches are in view (rocks, sea, sky fine). [cb-short] fired (cb0 80/74,
  cb1 9/4..42, cb2 4/3 vec4 and more), so short constant buffers were real but
  not the cause; [idx-align] counted 659456 16-bit draws with offset 2 mod 4.
  [thread-prio] showed Crysis's main thread toggling base 0/15 and the policies
  skipped, yet 0024 still ran 0 ms on P-cores. Root cause of that: the guest
  main thread is created in WineProcessBridge.m with
  pthread_attr_setschedparam(priority 20), a fixed priority, so Darwin refuses
  pthread_set_qos_class_self_np (EPERM) -- USER_INTERACTIVE and the ECO switch
  never applied to it. Build 250: the thread gets its QoS through
  pthread_attr_set_qos_class_np instead ([main-qos] line), and
  tools/patch-dxmt-idx-align.py copies misaligned 16-bit index ranges to a
  4-byte aligned place in the argument buffer (MADEIRA_IDX_REALIGN=0 = off).
  The ECO toggle is in the session menu (Battery saver (ECO)) and the ECO pill
  of the Madeira performance overlay, not in Apple's Metal HUD.
* Upstream merge 2026-09-30 (100 commits up to fdbdef7, "round 3"): Steam
  owned library (sign-in, downloads, installs), fastsync as the DEFAULT sync
  engine (madsync only with inproc-sync = 1; Settings > Sync engine), NSI
  network tables and dnsapi unixlib, Dock GDI table for 32-bit programs, touch
  control glass faces, rebuilt 64-bit/aarch64 DLLs; pins FEX 26859e1 (#5:
  CPUID table bound -- tools/patch-fex-ios-cpuid-index.py now detects it and
  does nothing), wine 4f5b197, madeira-dock 3cadfbe. Kept ours: game cfg
  env block before the fastsync default (a game's env.MADEIRA_FASTSYNC wins),
  pointerMax, the JIT-pool second-session guard, the controls opacity, the
  memory-pool picker and MemoryHostTest row. The session menu's ECO toggle
  moved from Display to its own CPU section (the owner looked for it there).
* Build 251 on device (log 16:37): [main-qos] rc=0 class 0x21 -- the guest
  main thread now runs on P-cores (0024 ~300 ms P per 300 ms), so that fix
  works. The tree streaks are unchanged, but neither DXMT fix had actually
  run for most draws: both skipped GpuManaged allocations, and Crysis's
  static buffers are GpuManaged (578 of 653 buffers, [mem-census]). On iOS a
  GpuManaged buffer is CpuPlaced and Managed does not exist, so the CPU
  mapping IS the storage; the next build copies from it too and logs
  "encode: realigned / zero-padded copy bound / skipped" counts. The session
  menu the owner uses in a game is LibraryHUD's (Library.swift), not
  SessionUI's: the ECO toggle now also sits there under a CPU heading.
* Build 254 (7fe376d, first build of the round-3 merge) FAILED at "Verify all
  linked archives exist": libntdll_unix.a was not built because upstream's new
  nsi_ndis_ios.c / nsi_ip_ios.c did not compile -- RTM_IFINFO, RTA_IFP and
  RTF_LLINFO undeclared. Our CI configures Wine against the iPhoneOS SDK
  (no <net/route.h>), so HAVE_NET_ROUTE_H is undefined and ndis.c/ip.c never
  include upstream's shims/net/route.h (upstream builds with a macOS-configured
  config.h). Fix: both wrappers define HAVE_NET_ROUTE_H when config.h does
  not. (How the error was found: the job log is only 2649 lines; get_job_logs
  with tail_lines=2649 saves it to a file that can be grepped.)

### Build 226: first green IPA after the switch (2026-09-29, run 36595079405)
Commit 17088ab (main fast-forwarded; the automatic main run 227 cancelled).
Native ABI e708a9072e35d90d, shader cache identity 1f62cb76a67abb1f: packs
5-7 do not install over it. Contains everything under builds 222-223. The
i386 farm came from the CI cache. Not in it: the AVX variant of
xtajit64.dll (the committed module does not match a rebuild of FEX
2838f3b, so tools/build-xtajit64.sh refuses to ship one); the per-game
"AVX / AVX2" switch has no effect until that is sorted out. Device test
pending: library + madeira-bcd sections, God of War with its config.

### Build 223: library first, madeira-bcd home as a choice (2026-09-29)
Owner's request: upstream's interface by default, ours as a separate option,
our per-game options inside upstream's game page, every upstream feature.
* Also merges upstream a15332c (MadeiraMemoryHost app extension: memory
  owned by another task, used by the swap tier first; `mempool-mb = N` in
  madeira.cfg or Settings > Memory & sync, off by default; needs `swap-mb`)
  and d5a8e0a (library tab bar). The extension's bundle id was changed to
  `com.willfaust.mythicemu.MemoryHost` (must be prefixed by the app's id).
  Worth trying for God of War's memory: `mempool-mb` next to `swap-mb`.
* Interface: `FrontendChoice` has a third stored value "bcd". RootView
  starts in ContentView (library / developer) unless it is "bcd". Picker:
  library Settings > Interface, madeira-bcd home settings; the developer
  interface has a "madeira-bcd Home" button.
* `LibraryBCD.swift`: the madeira-bcd sections of `LibraryDetail` (AVX,
  Wine VCRT, NVIDIA; MetalFX, frame gen, D3D12 switches, game config file;
  Home Screen link), keyed by the Windows path as in HomeView, so both
  interfaces share settings. Library launches call `BCDLaunch.applyLibrary`
  (update pack env, the options, per-game session log). Resolution picker:
  "Screen shape for MetalFX 1.5x"; FPS picker: 40 FPS. Long press: Play /
  Game settings. Settings > Interface > "Add every game in drive_c".
  Shortcuts (madeira://play) start the library entry in library mode.
* Builds 222-224 failed on leftovers of 125hz's series: a brace lost in
  the virtual_ios.c re-apply, an SDK field in server_ios.c, 125hz's DXMT/nsi
  PE DLLs, Swift calls into 125hz's removed cursor helpers, and 125hz's
  fastsync wineserver/bridge sources (9 undefined symbols at link). Every
  file only 125hz had changed since the base now equals upstream (or is gone).
  Still 125hz's on purpose, because they build and link against upstream:
  app-side JIT pool handling (JITAllocator, StikJITHelper, the ml1330 early
  pool in ContentView) and sysparams_ios.c's weak diagnostics hooks.
* RDR2: upstream has no separate RDR2 package; its RDR2 bring-up lives in
  the runtime we merged (ntdll-unix, madeira_d3d12, the converter service,
  swap tier), plus `research/HANDOFF-rdr2-arm64ec-hooks.md`.

### Build 222: switched to upstream (2026-09-29, owner's decision)
Merge commit `4ccfcb5` brings in upstream main `15157e3` (77 commits: Library
front end, Steam sign-in, Madeira Dock, GuestDisplay/HardwareInput, WoW64,
DXMT's D3D9, swap-tier coverage modes + census, the DXIL conversion cache and
one-pass conversion). How the overlaps were resolved:
* `build/ntdll-unix/virtual_ios.c`: upstream's file, then our commits since
  `735e323` re-applied in order. Skipped as superseded: 6442b98/3115f50
  (our early storage-backed memory) and 81a799a (our swap floor). Our
  partial-page `decommit_pages` stays, now with upstream's
  `ios_swap_release_range` before the mmap-over.
* `swap-min-kb` now exports `MADEIRA_SWAP_COVERAGE=blocks` plus
  `MADEIRA_SWAP_MIN_KB` (upstream reads the floor only in blocks mode); an
  `env.MADEIRA_SWAP_COVERAGE` line still wins. Upstream prints
  `[swap] coverage=...` and a census line every 30 s instead of our
  `[swap] ml1077 stats`.
* `madeira_d3d12.c`: our PE shader cache (`mad_ir_convert_cached`) wraps both
  calls of upstream's one-pass conversion (first try and too-small retry).
  `cs-dump = 1` or `MADEIRA_D3D12_CS_DUMP=1` turns the compute dump on.
* `madeira_ir_unix.mm`: upstream's `mad_sc_path_ext` (DXIL cache files share
  `shadercache/`) keeps our `.mdsc` pruning; the hull/domain entry-name
  fallback applies to upstream's reflected name.
* `tools/patch-dxmt-framegen.py`: new present-hook anchor (DXMT now guards
  `ios_frame_encode_present` with `madeira_frame_hooks_on()`). The other DXMT
  patches apply unchanged to `a5e0cd3`. Upstream now has its own 30 FPS
  mode 3; our frame-limits patch's mode-3 branch is dead code, mode 4 (40)
  still works.
* CI: builds FFmpeg (`build/ffmpeg`, cached; the app links libav*.a) and the
  Dock host (`build/madeira-dock`, may fail without breaking the build).
  The 32-bit `i386-windows` farm is no longer committed (upstream's rule);
  CI builds it with `build/wine-i386/build.sh` (cached per wine/DXMT
  revision, continue-on-error: without it only 32-bit programs fail).
  125hz's committed DXMT/nsi PE DLLs in aarch64-windows/arm64ec-windows were
  replaced by upstream's (they called 125hz's DXMT unix slots).
* Launch log prints the game's config file (`[game-cfg]` lines).
* Removed 16 host tests from 125hz's WoW64 series that probe code no longer
  in the tree; `ConfigCatalog.generated.swift` regenerated (it lists our keys).

### Build 220 device results (God of War, logs 2026-09-29 14:42 / 14:54)
* Frame generation works: `[framegen]` generated a frame for every real one,
  HUD 40 FPS shown / 20 rendered, "Frame Interpolator Enabled". Costly: GPU
  8-10 -> 23-33 ms per frame, and the game waits ~29 ms per frame for a
  drawable (two presents per game frame on a 3-drawable pool), so the real
  rate fell from ~30 to ~20.
* The MetalFX output was 2084x960 (2x), not 1563x720, although DXMT logged
  `d3d11.metalSpatialUpscaleFactor=1.5`. The source reads it as a float, but
  the committed d3d11.dll may predate that, so 1.5 is not honoured. As a
  result the interpolator ran at 2 MP. Fix candidates: a factor-2 "fill"
  size (782x360 -> 1564x720), or MetalFX + interpolation in winemetal
  itself (the descriptor's `scaler` property lets the interpolator work at
  the scaler's input size).
* In-game: FSR 2 Ultra Performance was on (render 428x240 for a 1042x480
  output); Performance costs RAM; FSR off runs out of memory. With FG,
  ~280-300 MB stayed free. The VMCENSUS/totalphys run has not been sent yet.
* 14:54:09: the log stops at "Starting God of War" (22 lines): the app died at
  launch, cause unknown.

### Build 220: frame generation, "Fill with MetalFX 1.5x" (2026-09-29)
* God of War with build 219 + the four config lines: 10+ minutes of play
  (log 13:48). Swap tier 2.1 GB file-backed; `turned away`: under 1 MB
  0.7 GB, outside the guest band 11.9 GB (cumulative; mostly FEX's per-thread
  arenas at 0x7c.., which must stay anonymous: CpuStateFrame at +0x1140, see
  ml181), partly committed 0.1 GB. Textures 572 MB, Metal total 1.46 GB,
  footprint ~7.6 GB with 3.3-3.7 GB compressed. ~28-44 FPS, game CPU
  22-28 ms/frame, GPU 8-10 ms: GPU has room; memory limits resolution.
  Next memory step: one run with `env.MADEIRA_VMCENSUS = 1` for the
  per-band breakdown; `totalphys = 6144` to see if the game sizes its
  caches down.
* Frame generation (docs/madeira-bcd.md, App): first device test pending.
  Unknowns: motion vector scale/sign semantics, whether BGRA8 is accepted,
  pacing with the drawable pool. `[framegen]` lines say which.
* SDK probe workflow (.github/workflows/sdk-probe.yml): CI has Xcode 26.3 /
  iOS SDK 26.2; MTLFXFrameInterpolator.h was read from there.

### Build 219: swap floor knob (2026-09-29, run 36554968715, native ABI d22451074a1a1504)
* `swap-min-kb` (madeira.cfg or a game's config) lowers the swap tier's 8 MB
  eligibility floor; `[swap] ml1077 stats` prints every third heartbeat with
  the MB turned away by reason. Packs 5/6 are native-ABI 48a89bc6... and are
  ignored by 219; 219 already contains their changes.
* God of War config to try: `dxmt = d3d11.mipClampBC=2`,
  `env.WINEDEBUG = err+all,err-virtual,fixme-all`, `swap-min-kb = 1024`,
  `swap-mb = 6144`.

### Other games tried 2026-09-29 (IPA 218 + pack 5)
* God of War (2018, D3D11): the owner started
  `C:\God of War\_Windows 7 Fix\dxvk-1.10.1\GoW.exe`, a copy inside a
  DXVK "Windows 7 fix" folder. Its DLLs (libScePad, libSceJobManager,
  bink2w64, libSceGnm, libSceGpuAddress) are not next to it, so the loader
  stops with 0xC0000135 before any frame. Start the game's own GoW.exe in
  the install root instead. DXVK itself is Vulkan and cannot run here: DXMT
  is the D3D11 path, so do not use the DXVK DLLs.
* God of War, second run with the right exe (log 13:02, 43 MB): it reaches
  the main menu (~16-27 FPS); on New Game the footprint climbs to 7.7 GB and
  jetsam kills it. `[mem-census] tex-private live=4051MB` (12,411 textures),
  buffers 785 MB. The automatic BC mip clamp (dxmt ml2000, threshold 1536 MB
  headroom) engaged only at footprint 7188 MB and clamped 6 textures:
  too late for a title that loads 4 GB of textures at once. Workaround with no
  build, in the game's config: `dxmt = d3d11.mipClampBC=1` (drops the top mip
  of every eligible BC texture, ~4x less memory for them). 95 % of the log is
  `fixme:d3dcompiler:skip_u32_unknown` from D3DReflect on 4 threads:
  `env.WINEDEBUG = err+all,err-virtual,fixme-all` in the game's config.
  Candidate follow-up (dxmt, IPA): a larger auto threshold or a footprint
  trend trigger.
* Third run (13:11) with both lines: gameplay reached (a few axe swings),
  textures 4051 -> 1050 MB, Metal total ~1.7 GB, log 5 MB. The footprint
  still climbs to ~8.0 GB and sits at the limit for 2+ minutes (compressed
  3.2 GB) before jetsam. Not a leak: the game's own RAM is the rest. The swap
  tier (swap-mb 3072) already backs its big blocks (~1.6 GB), but
  `ios_swap_eligible` refuses commits under 8 MB, outside [0x70,0x7c), or not
  entirely fresh. Next without a build: mipClampBC=2 plus lower in-game
  settings. With a build: a madeira.cfg knob for the swap floor (e.g. 1 MB)
  and a breakdown of the footprint by region kind.
* Far Cry 5 (D3D11): it gets past the loading screen to a black window
  (d3d11/dxgi/winemetal loaded, no device created yet). ~50 first-chance
  write faults on read-only pages are handled (protection layer). Right after
  `EasyAntiCheat_x64.dll` (a 52 KB module from the game folder) loads and its
  TLS callbacks run, FC_m64.dll+0xe0a5d68 calls through a NULL pointer
  (AV EXEC of 0) and the game exits with 0xC0000005. Anti-cheat modules do
  not work in this environment; not investigated further.

### Pack 6: F0 no longer poisons the session (logs and videos 2026-09-28 20:35-20:41, pack 5)
* Videos matched to the 20:35 log through the HUD frame number (roughly the
  present count). At 20:36:41 (F1, no switch yet) the scene is intact but
  edges are jagged, dotted and blocky: character outline, fur, rock and
  wooden structures. It looks like the game's temporal upscaler/AA not
  resolving; libxess.dll is loaded, so the owner is to try the in-game
  upscaler options. 20:37:19 is F0: garbage expected. 20:37:44 is F1 AFTER
  F0: the scene goes black and blotchy.
* Cause of the last one: every GPU fault under F0 (no fences, i.e. races by
  design) was treated as a broken shader. `mad_fault_report` marked the
  cs_main pipelines to skip (15+ in that run) and switched the fault
  diagnostics on (one pipeline per compute encoder, labels) for the rest of
  the session. All F1/F5/F6 observations after an F0 test in the same run
  were invalid, and so was the 18:56 log. Pack 6: faults are not marked
  while F0 is in effect or for 8 presents after it; leaving F0 clears the
  skip list and the diagnostics.
* 20:41 (MetalFX 2x): the C++ exception fast-fail again, this time in
  gameplay, with the same stack (GhostOfTsushima+0x449681 recursion,
  +0x40a99d, VCRUNTIME140_1 frame handler, handler +0xd15f0c). Pack 5 did
  not fix it, so it is not the device list race. Next step is native
  (unwind / dispatcher-context diagnostics), so an IPA.
* 20:39 async-submit = 1: ExecuteCommandLists costs the game thread 0.03 ms;
  the worker is busy ~16 ms per frame and the game waits on its fences
  10 ms per frame (24 %) at the end. Thermal was WARM from the start; no
  clear win yet.

### Pack 5: device list race fixed (logs 2026-09-28 18:53 and 18:56, IPA 218 + pack 4)
* 18:56 crash: AV in the ntdll heap (ntdll+0x29634) under
  `device_CreateSampler -> mad_note_sampler -> mad_grow` (realloc) on thread
  00f0 while five game threads were streaming a new area. Symbols came from a
  local `-g` build of 6bbd6b8: same .text size as pack 4, so the RVAs match.
  `d->samplers`, `srv_res` and `uav_res` were grown, appended and
  swap-removed without a lock, although D3D12 device methods are
  free-threaded; two reallocs of one array corrupt the heap, and the heap
  lock left held gave the 60 s `RtlpWaitForCriticalSection` timeout that
  follows. It happened right after an F0 -> F1 pill switch, but the switch is
  not involved. Pack 5: `list_lock` (SRWLOCK) guards the three lists;
  membership is O(1) through `srv_slot` / `uav_slot` (the old linear scan
  covered ~15,000 textures per view creation); the per-draw fallback loops
  and `mad_texture_of_view` read under the shared lock. The heap corruption
  may also explain some of the intermittent crashes before this one.
* 18:53 crash: the known C++ exception fast-fail (handler
  GhostOfTsushima.exe+0xd15f0c, 0xC0000409) while loading into the world;
  see "Build 191 results". Still open. A corrupted heap is one possible
  source, so check whether it recurs with pack 5.
* Frame time (18:56, 1280x720, F1): steady 22-27 ms per frame. ExecuteCommandLists
  takes 4-6 ms of that: Metal encode calls 0.66 ms (583 calls),
  encoder open+end 1.76 ms (134 encoders), and the rest is the replay itself. Present
  0.25 ms, the game blocked on fences 0 ms. The remaining ~18 ms is the
  game's own CPU time under emulation, so draw batching on our side can win
  1-2 ms at most. ECL spikes of 50-550 ms per frame are first-draw pipeline
  compiles (`pso-lazy`) in new areas; the shader cache removes them on the
  next visit. useResource dedup skips ~55 % of the entries in gameplay.
* `[frame] ml1050` always says "no Present reached the presenter" for D3D12:
  that reporter only sees DXMT's presenter. Not a bug in the game path.

### Build 218: saves backup, Home Screen shortcuts, useResource dedup (2026-09-28)
* `madeira_d3d12`: one useResource per resource and encoder (`mad_use_seen`,
  `use-dedup`, default 1); a draw's entries are committed only after its
  chain was encoded. The encode split line reports the skipped entries.
* Settings > Saves (backup/restore zip) and `madeira://play?exe=...`
  shortcuts (see docs/madeira-bcd.md, App).
* 217 was CI verification only; the owner installs 218 (nothing had been
  installed since 214).

### Build 217: GoT specks/smears flags, experiments in the sheet, storage (2026-09-28)
Log analysis (13:21 and 14:04 logs, builds 211/212):
* 13:21 "40-45 then 20 FPS": the `[perf] ml1108` GPU time per frame jumps
  from 17-20 ms to 37-44 ms while ExecuteCommandLists stays ~2 ms; the game
  then waits 33-39 ms/frame on its fences. GPU-bound, the particle
  tessellation growth capped in 213 (`dxil-tess-max-factor`).
* 14:04 gameplay: frame 38-42 ms = GPU 19-20 ms (not the limit) +
  ExecuteCommandLists 10-16 ms ON THE GAME'S RENDER THREAD (~630 draws,
  ~5,600 commands a frame) + 4-8 ms fence waits. `async-submit = 1` moves our
  encode to a worker (RDR2 upstream saw no gain because its render thread
  was not the critical path; GoT may differ). Now a picker in the game sheet.
* ~220 GPU encoders a frame, each waiting for the previous one under
  fence-chain 1; the F6 picker/pill lets passes overlap.
* Render passes always Load/Store (no pending clear); census frames show
  ~225 MB loaded + ~241 MB stored, 170 MB of it never used again in the same
  list. Cross-list use is unknown, so no DontCare yet -- a candidate for a
  frame-level analysis.
Also in 217: the `[perf] encode split per frame` line (time inside the Metal
encode unix calls vs encoder open/end vs the replay itself, and the
useResource entries per frame) to find where ExecuteCommandLists' 10-16 ms
go before optimising it; Settings > Storage; the D3D12 experiment pickers.
(Run 216 was the automatic main-push duplicate, cancelled.)
The specks in the owner's screenshots sit on the fire-lit smoke and rock by
the bridge and come and go between frames: NaN/Inf, most likely through the
NaN-cleared velocity target into the temporal resolve, or particles killed
with an infinite position. Build 217 turns on `IRCompatibilityFlagSampleNanToZero`
and `IRCompatibilityFlagVertexPositionInfToNan` (`msc-sample-nan-zero`,
`msc-position-inf-nan`, both default 1; the shader cache keys on them, so the
first start converts again). (The comment in
`madeira_ir_unix.mm` was corrected in 218:) SampleNanToZero flushes NaN sampling
COORDINATES to zero (man page), it does not rewrite sampled values -- the
velocity NaN markers the game tests stay intact.

### Build 215: update packs, per-game config, MetalFX, thermal (2026-09-28)
The owner is tired of signing and installing an IPA per experiment, so the
iteration loop moved in-app (see section 2, "Update packs"). Also:
* `metalfx-upscale = <factor>` (per game from the sheet: Off / 1.5x / 2x):
  the D3D12 swapchain runs Apple's MetalFX spatial scaler on a 2D view of the
  back buffer into a private texture of factor x size, and the present blit
  copies that into a drawable of the same size (`mad_swap_make_fx`,
  `mad_present_run`). D3D11 games get DXMT's own MetalFX swapchain
  (`DXMT_METALFX_SPATIAL_SWAPCHAIN=1`, `d3d11.metalSpatialUpscaleFactor`).
  Meant with a small screen size (960x540, 1280x720) for frame rate.
* Per-game starting FPS limit (`fps-limit` = 30/40/60/max/raw) and the
  tessellation cap (`dxil-tess-max-factor`) as pickers.
* The FPS overlay shows the thermal state (OK/WARM/HOT/CRIT); `[thermal]`
  lines mark transitions and every `[present]` line carries it. Use it on the
  "starts 40-45, sinks to 20" report: a HOT at the drop means clocks, not us.
* Note: the D3D12 runtime presents through winemetal's
  `MTLCommandBuffer_presentDrawable`, so the Session panel's 30/40/60 caps
  already apply to Ghost of Tsushima.

### Build 214: upstream sync (2026-09-28)
Merged willfaust/madeira 9e9dfb6, e39be62, 735e323. Upstream vendors the
Metal Shader Converter 4.0 beta 2 public headers under
research/madeira-d3d12/third_party/metal-shader-converter and deps.sh now
hash-checks them and the tracked iOS library. Our CI does not go through
deps.sh: build/dxmt-ios/build.sh (kept ours) takes MADEIRA_MSC_INCLUDE, the
4.0.1 headers staged from the msc-private draft release, and keeps the stub
fallback instead of upstream's hard stop. Upstream moved the wine pin to
willfaust/wine d2808652; 125hz pr/wow64-core does not contain it, so the
pin stays at c9c186e. Build 214 green.

### Build 213: particle tessellation cap; the loading-screen freeze
* `[probe]` (log 2026-09-28 14:04) settles the FPS drop: the particle draws
  (`ls_SetColor`, `vs_SetColor`, `vs_SetColorCombinedAlpha`, 4 vertices x N
  instances) go 16 -> 2,929 -> 5,052 -> 6,897 -> 7,692 instances within
  seconds and then vary with the fires: not a leak, the game's particles.
  Each is a tessellated quad (max factor 9, up to 162 triangles) drawn three
  times through the emulation, and in the 13:21 log the GPU time climbed
  17 -> 44 ms as they spawned. Other indirect pipelines are steady. Build 213
  clamps the hull's max factor to 3 for pipelines declaring <= 16 (the water
  declares 64 and keeps it): madeira.cfg `dxil-tess-max-factor`, 0 = off.
* Loading-screen freeze (log 14:03): `RtlpWaitForCriticalSection ... blocked
  by 00bc`; 00bc was calling GetThreadContext on another thread thousands of
  times and getting `rip=0 rsp=0 flags=00100002` (no CONTEXT_CONTROL: the
  server had no native capture). The unix NtGetContextThread now fills the
  control (and integer) registers from the target's saved x64 state
  (ChpeV2CpuAreaInfo->ContextAmd64) when the server returns none; log
  `[ctx] madeira-bcd get ... returning the target's saved x64 state`.

### Build 212: probes for the GPU time that grows (log 2026-09-28 13:21)
* Build 211 draws the indirect tessellation (`DXIL tessellation: 3117 drawn
  (3117 indirect)`; every tessellation draw in gameplay is indirect). The
  smears and dark specks over the bridge did not change, so they are not the
  particles that were skipped.
* The owner: 40-45 FPS at first, ~20 within seconds. The perf lines agree:
  GPU per frame 17-18 ms -> 37 -> 42-44 ms (one window 61 ms) while the lists
  stay the same (~60 draws a list, 600-list totals flat) -- the GPU's own work
  grows. Best guess: a GPU-side count that is never reset (an append counter,
  so ever more particles/instances are simulated and drawn), which would also
  explain accumulating specks.
* Build 212 adds `[probe]` lines: every 3 s per pipeline the first argument
  record of each indirect draw/dispatch is copied (helper kernel
  `mad_probe_words`) to the CPU-visible ring and the previous copy is logged.
  A pipeline whose counts climb is the lead. madeira.cfg `ind-probe = 0`
  turns it off; at most 1,500 lines.

### Build 211: indirect DXIL tessellation draws (the particles)
The owner's screenshots (build 209) still show yellow brush-stroke smears and
clusters of dark specks over the bridge, where the fires' smoke and embers
are. The tessellation pipelines in use are the water and `ls_SetColor` /
`ps_SetColor_MultiLight`: 4-control-point patches, max factor 9 -- lit
particle quads -- and ~2,700 of their draws a run came through ExecuteIndirect
(GPU-driven particles) and were skipped. Build 211 draws them:
* `research/madeira-d3d12/src/pe/mad_kernels.metal` (kernel
  `mad_tess_indirect_args`) is compiled to a metallib by
  `tools/build-madeira-d3d12-dll.sh` (`xcrun -sdk iphoneos metal`) and embedded
  (`-DMAD_HAVE_KERNELS`, `mad_kernels_metallib.h`). Without xcrun the DLL
  builds without it and those draws stay skipped (log: `helper kernels: not
  built in`).
* Before such an ExecuteIndirect the render pass is split and one compute
  pass turns each argument record into MTLDispatchThreadgroupsIndirectArguments
  (ceil(count / (patches per object threadgroup x control points)) x instance
  count) in a 4 MB shared ring; each record is then drawn with
  `drawMeshThreadgroupsWithIndirectBuffer`, the D3D record bound at index 4
  for the object stage as for direct draws. tools/patch-dxmt-dxil-tess.py sets
  the object threadgroup memory for the indirect mesh draw too.
* Log: `helper kernels: ready ...`, `indirect tessellation: N record(s) ...`,
  and `DXIL tessellation: N drawn (M indirect)` in the ml1050 line.

### Build 210: the 209 test (log 2026-09-28 10:13, video)
* The C++ fix is applied (`[pc2fh] ... now maps`); the owner saved five
  times without a crash. The RGBA32 clear is exact now (`UAV clear value
  0xbf800000 0x4cbebc20 0 0: exact pattern buffer`), the big smears are gone
  and the GPU time dropped from 52-56 ms to 18-19 ms a frame at 1564x720
  (15 -> 20-22 FPS): the uncleared buffer was also costing GPU time.
* Left: dark specks and blocky haze near the bridge. Two leads:
  - 4 `ClearUnorderedAccessViewUint on a texture view the runtime does not
    know; skipped`. Now the named resource is cleared (the recorded view's
    sub-range, or all of a single-mip texture in its own format), and the log
    says why the view was unknown.
  - `indirect draw on a geometry-shader pipeline is not implemented` is the
    only skip site: 2,696 draws a run (`skips by site: L4436`). The only such
    pipelines are the DXIL tessellation ones (water, `ls_SetColor`). The log
    line now names each pipeline; implementing indirect tessellation draws
    (the object threadgroup count comes from the GPU-side arguments) is next
    if they matter.

### Build 209: the 208 test (log 2026-09-28 09:31, video, 1564x720 "Fill")
* **Smears with a still camera** (video, first 10 s: directional streaks and
  blocky patches behind the cart, the "dark patches in the air"). The log had
  `ClearUnorderedAccessViewUint on texture 'Texture' (view format 2 ...
  values 0xbf800000 0x4cbebc20 0 0) is not supported; skipped`: an RGBA32
  clear to (-1, 1e8, 0, 0), typical of a min/max depth or velocity tile
  buffer, left uncleared. Texture UAV clears only took texels that repeat
  every 4 bytes; the pattern buffers now repeat a 16-byte period, so 8- and
  16-byte texels are cleared exactly (log: `UAV clear value ... exact pattern
  buffer`). If the smears stay, the next suspects are the 4 clears on "a
  texture view the runtime does not know" and the 4 skipped indirect draws on a
  geometry-shader pipeline.
* **C++ fix still not applied**: `[pc2fh] no zero padding in the last .text
  page (000880c0..0008c000)`. On the device the tail of ntdll's last .text
  page holds file bytes (raw size 0x80000 > VirtualSize 0x780a5), not zeros.
  That range is outside every section, so the trampoline now goes at its
  start regardless of content; the pool copy is only refused when its bytes
  differ from the image's (another patch). Host test with a garbage tail:
  patched at RVA 0x880c0, idempotent, refused with foreign pool bytes.
* Water: DXIL tessellation now draws (`DXIL tessellation: ~1900 drawn`, no
  REFUSED). GPU time at 1564x720 is 52-56 ms a frame (overlay), so at that
  size the GPU is the limit (~15 FPS).

### Build 204: the three failures of the 203 test
* **C++ exception fix not applied.** `[pc2fh]` refused with "padding in use":
  the trampoline went at the end of the section gap, which this binary uses.
  It now goes in the first 48 zero bytes after `.text`'s end inside the last
  executable 16 KB page (verified offline against the real
  vcruntime140_1.dll: RVA 0x880d0). Log: `[pc2fh] ... now maps`.
* **Water: VS conversion.** `converted library has no function
  'ls_Main_techWaterMain'` / `no stage-in library`: the tessellation VS is now
  converted library-only (the function is looked up by the object-shader name
  in winemetal) and always gets the input layout for its stage-in function.
* **Dark launcher.** The launcher is an ordinary GDI window (790x445
  StretchDIBits, `[winios] present hwnd=... surf=896x512`), and its bits did
  reach Winios -- but `ContentView.swift` never called
  `winios_set_game_layer` / `winios_set_game_rect` (upstream's Swift side of
  the direct-launch overlay was never merged), so the overlay host was never
  created: no `[overlay] created host=` line in any log. MetalBackedView now
  publishes the layer once and the game rect on every change (with the two
  relayout hooks). The launcher should show and take taps; the overlay also
  arms win32u's 16 ms message poll while it is visible. `MADEIRA_DIRECT_OVERLAY=0`
  turns the overlay off.
