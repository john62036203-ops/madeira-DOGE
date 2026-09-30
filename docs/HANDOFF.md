# Handoff: state of the madeira-bcd fork (2026-09-27)

> **Türkçe özet:** Bu dosya, Claude ile bu depoda yapılan bütün işin devir
> notudur; başka bir asistan (ör. ChatGPT Codex) buradan devam edebilsin diye
> yazıldı. Kullanıcıya Türkçe yanıt verilir. Teknik ayrıntıların tamamı
> `docs/madeira-bcd.md` içinde; bu dosya "nerede kaldık, kurallar neler,
> sırada ne var" sorularını cevaplar.

This file is for whoever continues the work (another coding agent or a
person). Read it first, then `docs/madeira-bcd.md` (every change this fork
makes, with the reason and the evidence), `docs/WOW64.md`, `docs/BUILDING.md`.

---

## 1. What this repository is

`bahacan16/madeira-bcd` is a personal fork of `willfaust/Madeira`: Wine + FEX
(x86-64 JIT, ARM64EC) + DXMT (D3D11/D3D9 over Metal) + `madeira_d3d12` (a D3D12
runtime over Metal that converts DXIL with Apple's Metal Shader Converter and
DXBC with DXMT's airconv) packaged as an iOS app. The owner runs Windows games
on an **iPhone 17 Pro Max, iOS 27.0**, sideloaded with Feather. Personal use
only; the bundle id stays `com.willfaust.mythicemu`.

Upstream PRs merged into the fork (not yet merged upstream):
* **#28 (125hz)** WoW64 32-bit guests + DXMT D3D9. Needs the companion
  submodule forks: `wine` -> `125hz/wine` branch `pr/wow64-core`,
  `research/dxmt` -> `125hz/dxmt` branch `pr/d3d9` (see `.gitmodules`).
  The prebuilt DLLs from #28/#29 (i386 farm, ntdll, xtajit64) were committed
  with the owner's explicit approval.
* **#29 (125hz)** named touch-control layouts.

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
* A 12-hour "upstream sync" routine existed on the Claude side (merge
  `willfaust/Madeira` main into the dev branch, keep 125hz's submodule
  commits). It will not run elsewhere; do it by hand if needed:
  `git fetch upstream main` (remote = willfaust/Madeira), merge, keep this
  fork's additions, build, fast-forward main.

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
  use tokens from chat. A signing `.p12` (+password) and `.mobileprovision`
  were shared read-only; never commit or use them.

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
