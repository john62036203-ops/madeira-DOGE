# madeira-bcd: what this fork adds to willfaust/Madeira

Rebased on upstream `5a82d39` (2026-09-24) on 2026-09-24; tracks upstream main by merge, plus upstream PRs #28 (WoW64, D3D9) and #29 (controller layouts) by 125hz. Upstream carries the
runtime (Wine, FEX, DXMT, the native D3D12 runtime); this fork carries a CI
build and the app-side pieces below. Everything else is upstream's.

## CI build (`.github/workflows/build-ipa.yml`)

Builds an unsigned IPA on a GitHub macOS runner from a clean checkout: Wine's
unix side, wineserver, win32u, FEX's iOS archives, LLVM 15 for iOS, DXMT's unix
half and the app. The PE-side DLLs (ntdll, DXMT) are upstream's tracked
builds; `madeira_d3d12.dll`, `xtajit64.dll` and `faultrep.dll` are built from
source (below). The Microsoft VC++ runtime is fetched from
Microsoft at build time and never committed. Archived as Debug, per upstream's
docs/BUILDING.md.

**Version.** CI stamps `Info.plist` with version `0.1.<run number>` and build
`<run number>` before archiving, and names the IPA (and its artifact)
`Madeira-0.1.<run number>-unsigned.ipa`, so the version an installer such as
Feather shows is the Actions run it came from. The committed plist keeps 0.1.0.

**Metal Shader Converter.** The D3D12 runtime's unix half compiles against
Apple's converter headers, which upstream does not track. Apple's installer
(`Metal_Shader_Converter_4.0_beta_2.pkg`, from developer.apple.com/download) is
kept as an asset of a DRAFT release tagged `msc-private` -- drafts are visible
only to people with write access, so the package is never published. CI
expands it, stages the Apache-2.0 public headers in
`build/madeira-d3d12/msc-include/` (ignored) and copies the package's iOS
library over `app/Madeira/d3d12/libmetalirconverter.dylib`, so the headers and
the library always come from one build. First run (build 122): converter
4.0.1, iOS library sha256 `073f903b...` -- identical to upstream's tracked one.
Without the asset `build/madeira-d3d12/madeira_ir_stub.c` answers every
conversion with `MADEIRA_IR_NO_DYLIB`: D3D12 pipelines fail by name, D3D11 is
unaffected. The job has `contents: write` only because listing drafts needs it.

**Upstream fixes applied in CI.** Upstream builds from long-lived trees; a clean
checkout of its pins does not build. The workflow works around each, and every
step says so when it becomes a no-op:
- wine `dlls/ntdll/arm64ec_x64_export_iat.c` is included but was never
  committed: an empty placeholder for makedep (PE-side only, never compiled).
- wine `dlls/ntdll/unix/sync.c` includes `build/madeira_cfg.h` before
  `config.h` on purpose; makedep's ordering check is made a warning.
- `server_ios.c` reads `rusage_info_v6.ri_page_wait_time_mach`, absent from the
  runner's SDK: the `pgw=` figure of the `[xp]` line reads 0.
- FEX (`tools/patch-fex-ios-probes.py`): two diagnostic probes compiled outside
  their guards, and `rpm_cas_snapshot_take` (rpmalloc, not built with
  `ENABLE_FEX_ALLOCATOR=OFF`) gets a weak fallback; `IOS_RPM_GUARD` gets a
  no-op definition in the system-allocator branch.

## Update packs (`.github/workflows/build-pack.yml`, `app/Madeira/UpdatePacks.swift`)

Why: on iOS the Windows-side DLLs are data. Wine maps the PE file a system32
farm link resolves to (`loader_ios.c`, `load_builtin` returns
`STATUS_IMAGE_ALREADY_LOADED`), copies it into the JIT pool, and binds its unix
side by DLL name (`virtual_ios.c`, `load_builtin_unixlib`) -- nothing about a
PE needs signing or has to live in the bundle. So a fix in the D3D12 runtime
can reach the phone without a new IPA.

- **Pack.** A zip with `madeira-pack.json` at its root (format 1: build, commit,
  created, `native_abi`, notes, files with SHA-256) and the DLLs under
  `arm64ec-windows/` (also accepted: `aarch64-windows/`, `i386-windows/`).
  Today it carries `madeira_d3d12.dll` and the same file as `d3d12.dll`.
- **Build.** `build-pack.yml` runs on every push to the dev branch that touches
  `research/madeira-d3d12/src/pe` (or by hand): DXMT submodule only, the four
  DXMT source patches, llvm-mingw, `tools/build-madeira-d3d12-dll.sh`. The
  artifact is the pack itself. `tools/pack-index.py` publishes it on the rolling
  public prerelease `packs` with `index.json` (newest 25 packs; plus the last
  IPA builds' ABI, recorded by `build-ipa.yml`, metadata only).
- **Compatibility.** `tools/native-abi.sh` hashes `git ls-files -s` over the
  native half (app/ minus the pack-replaceable PE files, build/, DXMT, the
  D3D12 conversion service and ABI header, the patch scripts, the wine and FEX
  commits) plus an `EPOCH`. The IPA stamps it into Info.plist
  (`MadeiraNativeABI`, with `MadeiraShaderCacheID`, `MadeiraCommit`,
  `MadeiraBuilt`, `MadeiraRepo`); a pack with another value is refused, and so
  is a pack created before the app was built (it would override newer DLLs).
- **App.** Settings > Updates checks `index.json`, installs the newest
  compatible pack (or any older compatible one), or a zip from Files; the home
  screen shows a banner when one is waiting and a "Pack N" chip when one is
  active. The zip reader is the app's own (stored/deflate via Compression,
  zip64 aware). Install verifies every SHA-256 into a staging directory and
  swaps it in; every launch verifies again before exporting
  `MADEIRA_PACK_DIR`/`MADEIRA_PACK_ID`. `WineProcessBridge.m`
  (`madeira_pe_source`) then links those farm entries to the pack's files and
  logs `[pack] arm64ec-windows/<dll> from the update pack (...)`.
- **Shader cache.** The cache identity is the converter's, i.e. the app's: the
  app exports `MADEIRA_SC_ID` from Info.plist and `madeira_d3d12` uses it in
  place of its compiled-in value (same bytes as before, so existing caches
  stay). The runtime's `device created:` line names its build (`ipa N` or
  `pack N (sha)`).

## Per-game config (`app/Madeira/GameProfiles.swift`)

A game's own `madeira.cfg`, in `Application Support/GameConfigs/<fnv>.cfg`,
exported as `MADEIRA_CFG_GAME` when it sets anything. `build/madeira_cfg.h`
reads it after madeira.cfg (and the legacy files), so its keys win;
`WineProcessBridge.m` exports its `env.*` lines after madeira.cfg's; a `dxmt`
line there is appended to DXMT_CONFIG. The game sheet has pickers for
`metalfx-upscale`, `fps-limit` (applied when the session starts) and
`dxil-tess-max-factor`, and an editor for the raw file.

## WoW64 and D3D9 (125hz, upstream PR #28, not yet merged upstream)

Merged from `willfaust/Madeira` pull request #28 (125hz): 32-bit programs run
in a 4 GB guest window at a per-process base (`docs/WOW64.md`), with Wine's
i386 set in `app/Madeira/i386-windows/`, FEX's WoW64 module
(`aarch64-windows/xtajit.dll`) and DXMT's D3D9 frontend. The binaries are
125hz's prebuilt farm (`docs/BINARIES-WOW64.md` lists every file with its
SHA-256), including new 64-bit `ntdll`, `nsi`, DXMT DLLs and `xtajit64.dll`.
That `xtajit64.dll` was built from 125hz's FEX change, which the FEX
submodule does not pin; its ARM64EC interface is upstream's plus one
diagnostic export, so `tools/build-xtajit64.sh` keeps building the AVX
variant from the pinned source and checks it against upstream's pre-merge
module (fetched by commit). The two conflicts with this fork were the same
TEB retarget fix (125hz's version kept) and the `[xp]` `pgw` placeholder.

The series' unix side needs 125hz's companion source changes, so the `wine`
and `research/dxmt` submodules point at 125hz's public forks:
`125hz/wine` `pr/wow64-core` (c9c186e, upstream's wine pin 723d1bf plus 10
commits: `ProcessWineIosWowGuestBase`, the wow64 thunks, fastsync) and
`125hz/dxmt` `pr/d3d9` (462a77e, upstream's dxmt pin ca8a251 plus 18 commits:
the D3D9 frontend and its unix-call slots 145-150, which the series'
`winemetal.dll` calls). Without them the ntdll unix side and DXMT's unix half
do not build (build 154), and a D3D11 title would call unix slots the old
`winemetal_unix.c` does not have. When upstream moves either pin, the sync
has to move to a 125hz commit that contains upstream's, or drop the series.

With the series the only monitor is the virtual one, which has no source.
`NtUserDisplayConfigGetDeviceInfo` (`build/win32u-unix/sysparams_ios.c`)
dereferenced `monitor->source->gpu` for it and Ghost of Tsushima died in the
syscall; it now skips source-less monitors, as `NtUserQueryDisplayConfig`
already did.

## Runtime

- TEB retarget pass (`build/ntdll-unix/virtual_ios.c`, pass 0 of the x18
  patcher): its literal-pool guard indexed the per-word BITMAP as a byte per
  word, reading past the allocation for code beyond the first eighth of
  `.text`. Upstream's FEX module keeps its hand-written TEB reads near the
  start and never tripped it; a rebuild that links them later lost all six
  retargets and FEX read the TEB from the wrong TSD slot (NULL).

- `xtajit64-avx.dll`: FEX's ARM64EC module rebuilt by
  `tools/build-xtajit64.sh` with `tools/patch-fex-ios-avx.py`, shipped beside
  upstream's untouched `xtajit64.dll` and linked in as
  `system32\xtajit64.dll` only for a game with AVX on (WineProcessBridge.m): the iOS path of
  `FetchHostFeatures` never sets `SupportsAVX` and skips the HostFeatures
  override, so titles compiled for AVX (Ghost of Tsushima) die on their first
  VEX instruction (c000001d). `MADEIRA_FEX_AVX=1` turns on FEX's 128-bit AVX
  emulation for that launch; the game settings' "AVX / AVX2" switch sets it.
  Off by default, so titles that check CPUID keep their SSE paths. The script
  first rebuilds the unpatched source and ships nothing unless it matches the
  committed DLL (sections and exports); the recipe (`MINGW_TRIPLE`,
  `FEX_IOS_HOST_BUILD`, `-DFEX_IOS_HOST=1` for C, C++ AND the assembler, LTO off;
  builds 138-148 missed the assembler flag, got the stock `ExitToX64` and
  crashed every x64 DLL entry point with a misaligned sp) is not in upstream's
  `build/fex-arm64ec/build.sh`.
- `faultrep.dll` (`build/faultrep`, `tools/build-faultrep-dll.sh`): upstream's
  Wine set has none, and games that import it fail in the loader with
  STATUS_DLL_NOT_FOUND. Wine's exports plus `WerReportHang`, all succeeding
  without doing anything.
- Extra Wine DLLs (`tools/build-wine-extra-dlls.sh`): the VC++ 2002-2012
  runtimes (msvcr70-110, msvcp60-120, vcomp*), D3DX9 24-42, D3DX10, D3DX11,
  d3dcompiler_33-46, d3d10, d3d10_1, avifil32, msvfw32, dinput, XAudio2 /
  X3DAudio / XAPOFX, built from the wine submodule for arm64ec in CI the way
  upstream configures `wine/build-arm64ec`, stripped and padded like the
  shipped builtins, never replacing one upstream ships. Crysis's
  `Crysis64.exe` needs msvcr80. The msvcr* builds carry
  `tools/patch-wine-msvcrt-datasync.py`: an ARM64EC DLL runs from its JIT-pool
  copy, so its live globals are the copy's and an importer's data imports
  (bound to the PE mapping) read a stale snapshot -- Crysis64's CRT startup
  read a NULL `_acmdln`. At the end of process attach the DLL copies its
  writable sections over the PE mapping's -- with plain stores after a
  VirtualQuery, never VirtualProtect: on a pool-copied image the protect path
  syncs the PE side into the running copy and would wipe the DLL's state. A local build reproduces upstream's
  `msvcr120.dll` section for section. About +11 MB compressed.
- `nvapi64.dll` (`tools/build-dxmt-nvapi.sh`): DXMT's own NVAPI
  (`research/dxmt/src/nvapi`), which its build leaves out, compiled for
  arm64ec against import libraries of the shipped `winemetal.dll`/`dxgi.dll`.
  The library's per-game "Report an NVIDIA GPU" switch sets
  `DXMT_ENABLE_NVEXT=1`: DXGI then reports vendor 0x10DE and NVAPI answers
  `NvAPI_Initialize` and the driver version (999.99). Ghost of Tsushima, a
  Nixxes port, otherwise creates its D3D12 device, finds an Apple (0x106B)
  adapter it has no driver query for, logs "Failed to get GPU Driver Info" and
  says no graphics card is installed.
  `tools/patch-dxmt-nvapi.py` (applied to a copy at build time) adds the
  entry points the game then asked for and DXMT lacks
  (`NvAPI_GetLogicalGPUFromPhysicalGPU`, `NvAPI_GetPhysicalGPUsFromLogicalGPU`,
  `NvAPI_GetAssociatedNvidiaDisplayHandle`, `NvAPI_GetAssociatedDisplayOutputId`,
  `NvAPI_GPU_GetPCIIdentifiers`, `NvAPI_GPU_GetThermalSettings` -- one GPU
  sensor at 50 C) and logs each queried function once as `[nvapi] query`.
- `madeira_d3d12.c`: `GetAdapterLuid` returns the adapter's LUID and
  `GetDeviceRemovedReason` returns S_OK unless the device is lost; both were
  generated stubs (a zero LUID, E_NOTIMPL). Ghost of Tsushima polls the
  latter and took E_NOTIMPL for "Device removed detected", then crashed.
- `madeira_d3d12.c` `mad_air_resolve`: a DXBC (SM5) shader's static samplers
  were refused ("not yet placed in the sm5 argument table") and the draw was
  skipped. They now take the descriptor the root signature already builds for
  the DXIL path (its ml923 static sampler table). Ghost of Tsushima lost one
  draw every frame to this: intro videos with sound and no picture, then a
  black screen at ~17 fps.
- Lazy pipelines (`madeira_d3d12.c` `mad_pso_realize`, `mad_cpso_realize`):
  plain render pipelines (no GS or tessellation) and compute pipelines keep
  their Metal descriptors and are built by the first draw or dispatch that
  uses them. Ghost of Tsushima creates ~14,000 pipelines at New Game; built
  eagerly they took 5.1 GB of Metal memory and iOS killed the app at 7.8 GB
  on the loading screen. `pso-lazy = 0` in madeira.cfg restores eager
  creation.
- Per-game "Safe thread sync (no fastsync)" launch option (`HomeView.swift`,
  `LaunchRequest.safeSync`): sets `MADEIRA_FASTSYNC=0` for that launch, to test
  whether Madeira's in-process event/wait fast path lets a wait return early
  (Ghost of Tsushima's workers free a 1 MB block another thread still reads).
  The valid build 185 test at 2026-09-27 18:29 showed `mode=off`, zero
  fastsync counters, and nevertheless another freed-while-read crash. The
  fast path alone cannot explain the failure; the reported 3–5 extra seconds
  of gameplay is a single observation, not proof of a speed/stability gain.
- Parallel first use of lazy pipelines (`mad_prebuild_lists`): each pipeline
  has its own build lock (was one global lock), and before a batch is replayed
  the not-yet-built pipelines its lists bind are built on up to 4 threads.
  Ghost of Tsushima's first gameplay seconds needed hundreds at once and
  `ExecuteCommandLists` reached 2.3 s per frame. The helpers are a persistent
  pool of 3 threads (creating Wine threads per batch cost an 8 MB stack, a TEB
  and FEX state each). `pso-parallel = 0` in madeira.cfg turns it off.
- The 64-bit fallback above the 32-bit windows (`ios_wow_high_side`) searches
  up to the user-space limit, not only to the furniture ceiling: on device
  0x7200000000..0x73ffff0000 is already occupied.
- Persistent shader cache (`madeira_d3d12.c` `mad_ir_convert_cached`): every
  DXIL/DXBC -> metallib conversion is keyed by a hash of all its inputs
  (bytecode, entry, root signature, static samplers, input layout, paired
  stages, pixel flags, target, and the converter identity) and stored
  with all the converter's outputs in
  `%LOCALAPPDATA%\Madeira\ShaderCache\<identity>\`. The second launch of a game
  skips the converter for every shader it has seen; caches of other identities
  are deleted in the background. Ghost of Tsushima's New Game converts ~29,000
  stages (several hundred MB on disk). `shader-cache = 0` in madeira.cfg
  turns it off.
  The identity is `MAD_SC_CONVERTER_ID`, which `tools/build-madeira-d3d12-dll.sh`
  computes from everything that shapes a conversion (the service in
  `research/madeira-d3d12/src/unix` and the IR ABI, `build/dxmt-ios/build.sh`,
  DXMT's airconv and DXBC parser as patched, LLVM's `llvm-config.h`, the iOS
  `libmetalirconverter.dylib` and the MSC headers), plus the runtime switches
  that change the output (`vsps-fill`, `MADEIRA_IR_NO_BOUNDS_CHECK`,
  `MADEIRA_AGS_ROUNDTRIP_ONLY`); the start-up log line prints both. Before, the
  identity was the DLL's `__DATE__ __TIME__`, so EVERY new build converted all
  ~29,000 stages again. A local build without the define still gets a cache
  per build. Also: the caller converts in two calls (size, then fill); a miss
  used to run the DXIL converter twice and a hit read its file twice. Now a
  missing sizing call converts once with room for every output, stores it and
  hands the entry to the fill call on the same thread (`mad_sc_memo`); a
  metallib larger than the 4 MB guess is converted again into its exact size,
  and a shader the converter refuses answers the sizing call directly. Checked
  on the host against a mock converter (86 -> 45 conversions for 48 shaders
  cold, 0 warm, same outputs, torn entries rewritten, 8 threads).
- DXIL tessellation through the converter's own emulation (`madeira_d3d12.c`
  `mad_dtess_convert` / `mad_ts_draw`, `madeira_ir_unix.mm` hull/domain
  reflection, `tools/patch-dxmt-dxil-tess.py`): a DXIL hull+domain pipeline is
  built the way `IRRuntimeNewGeometryTessellationEmulationPipeline` builds it --
  the vertex shader (converted with emulation and a separate stage-in
  function) as the object function with `tessellationEnabled`, the hull
  library's `irconverter_hull_shader` + `irconverter_tessellator` (function
  constants `vertex_shader_output_size_fc`, `max_tessellation_factor_fc`)
  linked into the object stage with the stage-in function, the domain
  library's `irconverter_dxil_domain_shader` linked into the mesh stage, whose
  function is the converter's passthrough geometry shader for the tessellator
  output. Draws follow `IRRuntimeDraw[Indexed]PatchesTessellationEmulation`
  (draw info at 5, draw params at 4, vertex-buffer table at 6, the top-level
  argument buffer also at `kIRArgumentBufferHullDomainBindPoint` 3, 15360 bytes
  of object threadgroup memory -- carried in the mesh draw's reserved words,
  which the CI patch makes winemetal honour). Hull and domain reflection
  (`IRShaderReflectionCopyHullInfo` / `CopyDomainInfo`) are checked against
  each other as `IRRuntimeValidateTessellationPipeline` does; anything missing
  or inconsistent keeps the old placeholder. Ghost of Tsushima draws its water
  with 23 such pipelines (`ps_Main_techWaterMain` ...), which were
  placeholders, so the water was missing. `dxil-tess = 0` in madeira.cfg turns
  it off; log lines `DXIL tessellation: ...`, `[winemetal] DXIL tessellation
  pipeline OK/REFUSED`, and `DXIL tessellation: N drawn` in the ml1050 report.
- Shared Metal libraries (`mad_libshare_*`): identical metallib bytes with
  the same entry share one MTLLibrary/MTLFunction (each pipeline holds its own
  reference). Ghost of Tsushima made 30,370 libraries from ~11,400 distinct
  outputs; with lazy pipelines alone Metal still held 5.1 GB and the game
  stopped itself after a failed allocation at 7.9 GB. A tessellation pipeline
  the runtime cannot build is now a placeholder (draws skipped) rather than
  E_FAIL, as ml1138 already did for geometry shaders.
- Robust buffer access for converted shaders (`madeira_ir_unix.mm`):
  `IRCompatibilityFlagBoundsCheck` is now set with
  `IRCompatibilityFlagForceTextureArray`, so a DXIL shader's out-of-range
  buffer read returns 0 and an out-of-range write is dropped, as D3D12
  requires. Ghost of Tsushima's GPU hang was a normal-recompute kernel
  dispatched with its thread count rounded up to the group size: the extra
  threads read their adjacency range from past the end of a structured buffer,
  got garbage instead of 0,0 and looped until Metal timed the command buffer
  out (error 2) -- found by capturing the kernel's DXIL (below) and reading it.
  `MADEIRA_IR_NO_BOUNDS_CHECK=1` restores the old conversion.
- Three more D3D12 guarantees from the converter (`madeira_ir_unix.mm`, MSC
  compatibility flags, each on by default and switchable in madeira.cfg):
  `msc-position-invariance` (the same vertex shader gives bit-identical
  positions in every pipeline; Metal compiles a vertex function per pipeline
  and may optimise the position math differently, so a depth-EQUAL pass after
  a depth pre-pass loses pixels at random -- Ghost of Tsushima issues ~350
  such draws a frame for cloth, moving objects and hair; DXVK and vkd3d-proton
  make position invariant by default for the same reason),
  `msc-strict-nan` (`IRCompatibilityFlagDisableNanInfOptimization`: MSC 4.0
  turned on Metal's no-NaN/no-Inf arithmetic assumption by default, so
  `isnan()` may fold to false and min/max lose their NaN rules; D3D12 keeps
  IEEE semantics and Ghost of Tsushima clears its RG16F velocity target to NaN
  every frame on purpose), and `msc-sampler-lod-bias` (the shader applies
  `MipLODBias`, which the runtime already writes into each sampler
  descriptor's metadata; Metal samplers have no bias of their own). The
  start-up line `[madeira-ir] MSC 4.0.1 compatibility: ...` shows the state;
  the PE shader cache keys on all of them. Build 217 adds two more, also on by
  default, for Ghost of Tsushima's dark specks and smears around fire and
  smoke: `msc-sample-nan-zero` (`IRCompatibilityFlagSampleNanToZero`: NaN
  sampling COORDINATES are flushed to 0, as D3D hardware treats them --
  Apple's man page: "Flush NaN sampling coordinates to zero". The game clears
  its velocity target to NaN on purpose, so a reprojection `uv - velocity` can
  be NaN; Metal's result for such a sample is undefined, and a bad value that
  reaches the temporal resolve stays in its history and spreads. The NaN
  VALUES the game tests with isnan() are untouched) and `msc-position-inf-nan`
  (`IRCompatibilityFlagVertexPositionInfToNan`: an infinite vertex position,
  how particle systems kill a particle, becomes NaN, which Metal discards like
  D3D instead of rasterising a sliver). Non-zero biases are logged
  (`sampler with MipLODBias`, `static sampler sN with MipLODBias`).
- GPU fault attribution (`mad_fault_*`, `tools/patch-dxmt-gpu-fault-info.py`):
  batch command buffers are created with
  `MTLCommandBufferErrorOptionEncoderExecutionStatus` (winemetal
  `madeira_ctl` op 8, patched into `winemetal_unix.c` at build time), and a
  failed one logs `GPU fault encoders: [FAULTED] <label> ...` (op 9). After the
  first fault every encoder is labelled, each compute encoder runs one
  pipeline, and a render pass is labelled with the pipelines it drew with; a
  pipeline a faulted encoder names alone is skipped from then on
  (`GPU fault: ... will be skipped`). Ghost of Tsushima hung the GPU in its
  first gameplay frames, Metal then ignored the queue and the game stopped
  itself, and the error named no shader. `gpu-fault-info = 0` /
  `gpu-fault-skip = 0` in madeira.cfg turn it off / keep such pipelines.
  From the first fault on, every dispatch's bindings are also copied into a
  ring keyed by its encoder, and a faulted compute encoder is logged with its
  pipeline, dimensions, root parameters and the first descriptors of each
  table resolved to the resources they point into (`GPU fault dispatch C#...`,
  `RUNS PAST THE END`); op 9 prefixes the Metal error code.
- UAV counters for DXBC shaders (`mad_uavctr_*`): `CreateUnorderedAccessView`'s
  counter resource was ignored and the sm5 table's counter word was 0, so a
  shader appending to a buffer wrote through a null pointer (a GPU page fault;
  DXMT's own comment on that 0 says as much). The counter address
  (`counter->gpu_address + CounterOffsetInBytes`) is remembered by the view's
  buffer address and written into the table. For DXIL (Metal Shader
  Converter) shaders the counter is what `IRRuntimeCreateAppendBufferView`
  builds: an R32Uint texture-buffer view over the counter's 4 bytes, named by
  the UAV descriptor's texture id, with its element offset in metadata bits
  32..39 (the descriptor used to carry texture id 0, so the converter's
  counter atomics hit nothing).
- 64-bit allocations above the 32-bit windows (`build/ntdll-unix/virtual_ios.c`,
  `ios_wow_high_side`): with PR #28's slot-0 placeholder at 0x7100000000,
  window exclusion kept only the band below it, so a 64-bit program's clamped
  allocations had 0x7038000000..0x7100000000 (3.2 GB) and never the ~8 GB
  above. A request with a caller-set lower bound cannot relax to a kernel pick,
  so once that band filled it got STATUS_NO_MEMORY (Ghost of Tsushima: 1 MB,
  then the game stopped itself). The band above the windows is now tried
  before relaxing or failing (`[wow-window] ... placed above them`).
- The unix DXBC shader cache (`madeira_ir_unix.mm`, `Documents/shadercache/
  *.mdsc`) binds every entry to its build (ml1020), so each build wrote a fresh
  set that nothing removed. The first cache access of a process now compares
  `shadercache/.build` with the build stamp and, when it differs, removes the
  entries written before the process started in a background thread (`DXBC
  shader cache: removed N entries of earlier builds`).
- Pipeline-creation timing (`madeira_d3d12.c` `mad_pso_time_report`): graphics
  and compute pipeline creation, the shader conversion + cache inside them,
  new Metal library creation, root signatures and lazy pipeline builds at the
  first draw are timed (QPC, summed over threads) and logged as `pso time
  (...)` every 2000 graphics pipelines and with the periodic ml1049 report --
  to see how much of the "Compiling shaders" screen is Madeira's and how much
  the game's own (emulated) work.
- Compute-shader dumps are opt-in (`madeira_d3d12.c` `mad_cs_dump_on`,
  madeira.cfg `cs-dump = 1`): ml931 wrote the first 400 compute shaders of
  every launch to `C:\madeira-cs\cs_<pipeline pointer>_<size>.dxil`, and the
  pointer changes from run to run, so each launch added up to 400 files
  (~16 MB) that nothing removed. With the switch off the old dumps are deleted
  in the background at the first compute pipeline (`removed N old
  compute-shader dumps`). Faulting shaders are still kept by hash
  (`fault-shaders.txt`, `fault_<hash>.dxil`).
- CAP contact sheets (`research/madeira-d3d12/src/pe/madeira_d3d12.c`,
  `mad_sheet_*`, `mad_capture_drain`, `mad_capture_dispatch_outputs`): the
  overlay's CAP button now turns every render-pass attachment of the captured
  frame AND the texture UAVs each compute dispatch can write (bounded table
  ranges) into numbered 320x180 thumbnails on PNG sheets of 20
  (`Documents/capture/f<frame>_sheetNN.png`, stored-deflate PNG written in the
  PE), with an index (`f<frame>_sheets_index.txt` and `[capture-sheet]` log
  lines: number, encoder, kind, size, Metal/DXGI format, resource, pass or
  `cs <bytecode hash> <groups>`). NaN/Inf texels are magenta and counted, depth
  is stretched over its own range, integer formats get distinct colours per
  value. Captures are thumbnailed and freed at the end of each
  ExecuteCommandLists once 48 MB are pending, so a frame never holds more than
  the budget; at most 480 thumbnails. `madeira.cfg`: `capture-uav = 0` drops
  compute outputs, `capture-raw = 1` also writes the raw files for
  `build/tools/capture-to-png.py`. Replaces the Mac-only raw workflow.
- Depth-stencil planes in copies (`madeira_d3d12.c`,
  `mad_subresource_plane`, `exec_copy_aspect`, `tools/patch-dxmt-b2t-aspect.py`):
  subresource indices of a depth-stencil resource are split into mip, slice
  and PLANE (plane 1 = stencil) instead of reading plane 1 as array slice 1.
  Texture<->buffer copies pass the aspect as MTLBlitOptionDepthFromDepthStencil
  / StencilFromDepthStencil (buffer->texture through the command's reserved[0],
  which the CI patch makes winemetal honour); texture<->texture copies between
  a depth or stencil plane and a colour texture (or with differing formats) go
  through a private staging buffer in two blit encoders. Ghost of Tsushima
  copies its stencil plane to an R8 texture and back each frame; the write-back
  landed past the texture, over depth and stencil: the black squares and the
  green block pattern.
- Alias report for captures (`madeira_d3d12.c`, `mad_pl_*`, `mad_alias_desc`,
  `mad_capture_log_op`): every resource gets a creation number (`r#N`), every
  heap one (`heapN`), and each DEFAULT heap keeps the list of resources placed
  in it with offset and Metal size. `[placed]` logs each placement; every
  contact-sheet line ends with the resource's number, heap range and the live
  resources overlapping it; during a CAP frame `[capture-op]` logs every clear
  and copy with its target, and `[capture-uavbuf]` every placed buffer a
  dispatch can write. Block-compressed textures are no longer thumbnailed and
  every thumbnail read is bounds-checked (a BC1 UAV target read past its copy
  and hung the second CAP of build 190).
- RtlPcToFileHeader knows JIT-pool aliases (`build/ntdll-unix/virtual_ios.c`,
  `ios_patch_rtl_pc_to_file_header`, called from both ntdll hook sites in
  `loader_ios.c`): the pool copy of the prebuilt PE ntdll's RtlPcToFileHeader
  gets its third instruction (`mov x20, x0`) replaced by a BL to a
  six-instruction trampoline in the padding after ntdll's .text, which maps
  x0 through `ios_jit_reverse_translate_addr` first. ARM64EC builtins compute
  their own addresses PC-relative in the pool, so Wine's `_CxxThrowException`
  recorded image base 0 for a pool ThrowInfo (magic still 0x19930520) and
  Microsoft's `__CxxFrameHandler4` read 0 + RVA: Ghost of Tsushima's crash
  when Wine's msvcp140 throws std::runtime_error (after a save, sometimes at
  start-up). Every instruction is verified before patching; log `[pc2fh]`.
  Also fixes RTTI and GetModuleHandleEx(FROM_ADDRESS) on pool addresses.
- C++ throw repair (only reached with a debugger attached -- ARM64EC RtlRaiseException dispatches in user mode; superseded by the entry above) (`build/ntdll-unix/thread_ios.c`, `NtRaiseException`): a
  64-bit C++ exception (0xE06D7363, 4 parameters) whose ThrowInfo pointer is a
  JIT-pool alias is mapped back to the PE image and gets that image's base as
  ThrowImageBase; a ThrowImageBase of 0 is filled from the owning MEM_IMAGE
  allocation. Otherwise `__CxxFrameHandler4` reads 0+RVA and the game dies
  (Ghost of Tsushima after saving). Log: `[cxx-throw]`.
- Delayed release (`build/ntdll-unix/virtual_ios.c`, `ios_fd_*`): a whole-view
  MEM_RELEASE of a private 1-16 MB guest-band allocation succeeds at once but
  stays mapped for `MADEIRA_FREE_DELAY_MS` (default 2000 ms, 0 = off; at most
  128 MB in flight). Ghost of Tsushima's job workers release a block others
  are still reading; the freed VA was reused at once (by the game, or by
  Metal, whose objects then got corrupted). A mitigation, not a fix.
- View history and stack quarantine (`build/ntdll-unix/virtual_ios.c`,
  `ios_vh_*`, `ios_stack_release`): Ghost of Tsushima's worker threads faulted
  copying 2 MB from a range that had been an exited thread's native stack and
  had no Wine view any more. Guest-band views of 1 MB or more are recorded when
  created and deleted (thread, time, reason), and a fault on an address Wine
  does not own prints the records that covered it (`[fault-rgn] history:`).
  An exited thread's native stack is decommitted but kept reserved for the
  next 8 stack frees before release; if it was freed or replaced meanwhile the
  release is skipped and `[stack-quarantine] ... FREED OR REPLACED` is logged.
- Free-site diagnostics (`virtual_ios.c`, `ios_vh_capture_free_site`): in the
  build 185 fastsync-off log, tid `00f8` deleted a `0x210000` view at
  `0x70f0dd0000`; 7–8 ms later three threads read `base+0x40` while copying
  2 MB via ntdll, with no new GPU command-buffer failure. For full
  `NtFreeVirtualMemory(MEM_RELEASE)` deletions of guest-band views >=1 MB,
  snapshot the native return address, FEX state RIP, saved AMD64 context RIP
  and RSP, plus up to eight main-exe address candidates from the saved stack.
  The existing view-history ring carries the snapshot and prints it only if a
  future fault covers that view (`[free-origin]`, addresses and exe-relative
  RVAs). Stack scanning is not an unwind; EC contexts can be stale, so the
  candidates need comparison with the reader's fault-time `[callret]` trace.
- Texture UAV clears (`mad_record_uav_tex_clear`, `MC_FILL_TEX`):
  `ClearUnorderedAccessViewUint/Float` on a texture view used to be skipped.
  The view's mip, slices and format are remembered by view id at
  `CreateUnorderedAccessView`; the texel is packed in the view format (uint
  clears copy each channel's low bits, float clears convert: 32/16-bit float,
  unorm, snorm, int, 10:10:10:2, 11:11:10) and blitted from a pattern buffer in
  row bands. Formats whose texel is not one repeating 32-bit word (a 64- or
  128-bit texel with different channels) are still skipped, with a log line.
- Virtual display adapter in the registry (`build/win32u-unix/sysparams_ios.c`,
  `ios_register_virtual_gpu`): this port never enumerates display devices, so
  the registry had no display adapter at all -- no `Enum\PCI` entry for
  SetupAPI, no `Class\{display}\0000` with `DriverVersion`, no DirectX key, and
  the `DeviceKey` EnumDisplayDevices returns did not exist. Each process now
  writes one adapter with Wine's `write_gpu_to_registry` (not added to the GPU
  list; the topology stays the virtual monitor's). It is Apple 106B:0001, or
  NVIDIA GeForce RTX 3060 10DE:2544 with driver 35.0.15.6094 when the game's
  "Report an NVIDIA GPU" is on, in which case DXGI gets
  `dxgi.customDeviceId=2544` too (appended to `DXMT_CONFIG`), so DXGI,
  EnumDisplayDevices, SetupAPI and NVAPI name one GPU. Ghost of Tsushima still
  said "Failed to get GPU Driver Info" with NVAPI alone.
- `vulkan-1.dll` (and d3d10/avifil32 if the build above failed)
  (`tools/build-stub-dlls.py`):
  stand-ins generated from Wine's `.spec` export lists, for games that import
  them statically (Crysis Remastered). vulkan-1 reports
  VK_ERROR_INCOMPATIBLE_DRIVER and NULL from the *ProcAddr entry points (Wine's
  forwards to winevulkan, which needs a host driver), so games fall back to
  D3D; d3d10 keeps Wine's forwards to the shipped d3dcompiler_43 and answers
  E_NOTIMPL otherwise; avifil32 returns AVIERR_UNSUPPORTED.

- `NtFlushInstructionCache` (`build/ntdll-unix/virtual_ios.c`) invalidates the
  icache under `WINE_IOS` regardless of `HAVE___CLEAR_CACHE`. CI's generated
  config.h does not define it, and without the flush every x64 guest died in a
  FEX JIT block tail (fault PCs all 64-byte aligned).

- User folders (`WineProcessBridge.m`, after upstream's ml719): Wine's profile
  is named after the unix user (`mobile`), not the template's `madeira`, so
  `C:\users\mobile\Documents` and friends can be missing; Ghost of Tsushima
  stops with "Unable to create the game's save folder". Documents, Desktop,
  Downloads, Music, Pictures, Videos, Saved Games and AppData\{Local,
  LocalLow,Roaming} are made real directories for both names at launch.

- `device_Release` (`research/madeira-d3d12/src/pe/madeira_d3d12.c`) released
  the device's GPU-timeline `MTLSharedEvent` before the heap reclaim that
  reads it; a device created and dropped at once (Ghost of Tsushima's adapter
  probe) crashed in `objc_msgSend` and the game reported "No installed
  graphics card". The event is now released last.

## App

- `HomeView.swift`: a library-first home screen (games with covers and
  per-game settings, the Windows desktop, test programs, settings). The
  original panel is still there under Settings > Developer tools.
- `ContentView.swift` (MetalBackedView) hands Winios the game's CAMetalLayer
  (`winios_set_game_layer`) and publishes the game rect on every change
  (`winios_set_game_rect`, `winios_overlay_relayout`, `winios_cursor_relayout`).
  Upstream's Swift side of the direct-launch GDI overlay was never merged, so
  a directly launched game's plain GDI windows (Ghost of Tsushima's launcher,
  message boxes, choosers) had no host layer and stayed dark.
- Pointer modes (Session panel, portrait bar): **Trackpad** (default; drag
  moves the pointer, tap clicks, hold then drag drags, two fingers scroll or
  right-click), **Touch** (the pointer jumps to the finger, a touch clicks
  there) and **Relative** (mouse-look motion, no clicks). A direct launch used
  to ignore the setting and always behave like Touch; it now uses the same
  trackpad handling as the Windows desktop, clamped to the game's live display
  mode and starting from the drawn cursor. Stored in
  `Documents/madeira-input.json` (`directTouch`).
- Screen size (per-game settings, direct launch only): the virtual monitor's
  default size, `MADEIRA_SCREEN_W/H` with `MADEIRA_SCREEN_SRC=game`. win32u
  advertises only modes up to that many pixels (ml1140), so the 1024x768
  default hid 1280x720; pick 1280x720 to offer 720p. "Fill the screen"
  (experimental) is 720 lines at the panel's aspect (`UIScreen.nativeBounds`;
  iPhone 17 Pro Max 2868x1320 -> 1564x720). A direct launch without
  one now unsets the variables instead of inheriting a previous desktop
  session's size. The game rect and touch mapping follow the guest's live
  mode (`winios_screen_size`, re-laid-out on `MadeiraDisplayModeChanged`)
  instead of a fixed 4:3 1024x768, so a 16:9 mode is no longer squeezed.
- `GameControllerManager.swift`: physical controllers mapped to keyboard and
  mouse (ported from SaimSuhailQu/Madeira 72ca339). Since upstream #22 hands
  pads to games as real XInput controllers (`GamepadInput.swift`), this
  mapping is opt-in while XInput is on (Controllers sheet, "Also send keyboard
  and mouse"), so a game does not get every press twice; detection and the
  live input tester work either way.
- `SessionUI.swift`, modelled on upstream's unreleased new UI (Madeira
  Discord), without its Steam sign-in and downloads: a launch screen with the
  game's cover until its first frame (or 8s after a window appears, for
  programs that never present), the game alone on screen, and a Session panel
  -- touch controls on/off and opacity, edit controls, keyboard, FPS limit,
  display fit (4:3 or stretch), performance overlay, ECO, pointer mode and
  sensitivities, live log. Landscape opens it from the touch-controls bar
  (the game surface is a window-level view, so it lives on that window);
  portrait from the bar under the game. A game started from the library no
  longer shows the developer view, which stays under Settings > Developer
  tools.
- Library (`GameLibrary.swift`, `HomeView.swift`): scans 12 levels deep,
  includes `C:\users` (without AppData/Temp), skips redistributable folders,
  splits a folder that only holds other games into one card each, shows each
  card's exe folder and exe count, and a Games / Every .exe switch. 64-bit exes
  are preferred as a title's default; 32-bit ones launch through the WoW64
  series below (the settings sheet marks them experimental).
- `FixedBaseImage` (`GameLibrary.swift`): a 64-bit exe linked /FIXED below
  4 GB (Crysis `Bin64\Crysis64.exe`, base 0x37000000) cannot be placed on iOS
  and Wine refuses to move it (c0000018). Before launch the library rebuilds
  its relocation table from the aligned in-image pointers in its data
  sections, adds it as a `.mreloc` section, clears RELOCS_STRIPPED and keeps
  the original as `<exe>.madeira-orig`. Validated against the real `.reloc` of
  41 x64 binaries; images with a writable executable section are skipped.
- Session logs (`LogStore.startSessionLog`): every launch also names its log
  `Documents/logs/<exe>-<yyyy-MM-dd_HH-mm-ss>.txt` -- a hard link to
  madeira-log.txt, so every writer's lines land in both and the next
  launch's rotation leaves the finished run under its own name. The newest
  40 are kept.
- Game Mode (`GCSupportsGameMode`, `LSSupportsGameMode`, games category) in
  Info.plist; `LSSupportsGameMode` silences the Metal HUD's "key not found"
  warning.
- Metal Performance HUD insights off by default (`MadeiraApp.init`,
  `MTL_HUD_INSIGHTS_ENABLED=0` unless already set): the HUD keeps its metrics
  panel but no longer stacks shader-compile / render-pass / blit notes over the
  game. `env.MTL_HUD_INSIGHTS_ENABLED = 1` in madeira.cfg brings them back.
- Settings > Experimental > Storage-backed memory writes `swap-mb = 3072` to
  `Documents/madeira.cfg`, which turns on upstream's file-backed guest data tier
  (virtual_ios.c ml1077). Measured on an iPhone 17 Pro Max / iOS 27.0 with this
  fork's earlier implementation: 256 MB of dirtied file-backed memory moved
  phys_footprint by 0 MB against +256 MB anonymous.
  `swap-min-kb = N` (madeira.cfg or a game's config, 256..65536) lowers the
  tier's eligibility floor from 8 MB, for games whose data comes in smaller
  commits (God of War sits at the 8 GB limit with only its big blocks
  backed). A game's config can also raise `swap-mb`. Every third heartbeat
  prints `[swap] ml1077 stats` with the MB turned away by reason: under the
  floor, outside the guest band, not plain valloc, partly committed.
- Frame generation (experimental, game sheet > Frame generation, i.e.
  `env.MADEIRA_FRAMEGEN = 1` in the game's config; tools/patch-dxmt-framegen.py):
  winemetal's present path copies each drawable into a history texture (the
  layer becomes framebufferOnly = NO), estimates motion by block matching on
  1/8-size luma (the game gives no motion vectors), runs MetalFX's
  MTLFXFrameInterpolator (iOS 26) on the previous and current frame with that
  motion and a flat depth, and presents the generated frame at once and the
  real one half a frame later. Twice the frames on screen, half a frame of
  latency; FPS caps are bypassed while it is on. Knobs: MADEIRA_FRAMEGEN_RADIUS
  (search radius in 1/8 px, default 6), MADEIRA_FRAMEGEN_MVSCALE (default 1),
  MADEIRA_FRAMEGEN_MVSIGN (-1 flips the vectors). Log: `[framegen]`.
- Screen size "Fill with MetalFX 1.5x": the panel's shape at 480 lines
  (1042x480 on a 17 Pro Max), which MetalFX 1.5x brings to about 1564x720;
  picking it sets MetalFX 1.5x when MetalFX was off.
- Bundle identifier `com.willfaust.mythicemu`, so an installed copy keeps its
  container (Wine prefix, library, covers) across updates.
- Update packs and per-game config: see their sections above. Game sheet >
  Graphics & performance: MetalFX upscaling (Off / 1.5x / 2x), FPS limit at
  start, tessellation detail, and the game's raw config.
- MetalFX upscaling (`metalfx-upscale`): the D3D12 swapchain
  (`mad_swap_make_fx`) creates a 2D view of each back buffer (they are 2D
  arrays), a private output texture of factor x size and an
  `MTLFXSpatialScaler`; Present encodes the scale, then blits the output into a
  drawable of that size (the layer's drawable size follows). Under fence-chain
  6 the scaler waits on and updates the device fence, so the blit's wait orders
  after it. Any setup failure logs and keeps the plain copy. D3D11 games use
  DXMT's own MetalFX swapchain (`DXMT_METALFX_SPATIAL_SWAPCHAIN=1`,
  `d3d11.metalSpatialUpscaleFactor`).
- Settings > Storage (`StorageSection.swift`): sizes of frame captures,
  session logs, the D3D12 shader cache (every profile's
  `AppData\Local\Madeira\ShaderCache`), the D3D11 shader cache, the update pack
  and the whole Windows drive, with delete buttons (confirmed) for the first
  four.
- Game sheet, D3D12 experiments: "command encoding" (`async-submit`, ml1120:
  the runtime replays command lists on a worker instead of inside the game's
  ExecuteCommandLists) and "GPU sync" (`fence-chain` 6 instead of 1); the
  overlay's F pill starts from the game's value.
- Settings > Saves (`SavesAndShortcuts.swift`): "Back up saves" writes one
  uncompressed zip (own writer, CRC-32) of every `C:\users\<name>`'s
  Documents, Saved Games and AppData, skipping caches (Madeira, Temp,
  ShaderCache, D3DSCache, NVIDIA, Microsoft, *cache*, logs) and files over
  256 MB, and hands it to the share sheet; "Restore saves" unpacks such a zip
  back into drive_c (only `users/...` entries, overwriting).
- Home Screen shortcuts: `madeira://play?exe=<Windows path>` (CFBundleURLTypes
  `madeira`) starts that exe through the library's own launch path once the
  scan has found it (JIT first as usual). The game sheet copies the link; the
  Shortcuts app's Open URLs + Add to Home Screen makes the icon.
- Performance overlay: a thermal-state pill (OK / WARM / HOT / CRIT from
  `ProcessInfo.thermalState`); transitions are logged as `[thermal]` with the
  FPS at that moment, and every `[present]` line carries the state and low
  power mode.
