#!/usr/bin/env python3
"""NVAPI prepares the process for DLSS on MetalFX (MADEIRA_DLSS=1, opt-in).

A game with DLSS Super Resolution carries NVIDIA's NGX client, which looks
for the NGX core (nvngx.dll / _nvngx.dll) where the registry value
HKLM\\SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore\\FullPath says, checks
its Authenticode signature with WinVerifyTrust and loads it. DXMT has an NGX
core that answers with the MetalFX temporal scaler
(tools/build-dxmt-nvngx.sh ships it as both names); it is not signed.

With MADEIRA_DLSS=1 in the environment (a game's config:
env.MADEIRA_DLSS = 1; only NVIDIA-reporting launches load NVAPI at all) the
first NVAPI call of the process:

1. writes FullPath = the system directory, and
2. makes the game's own WinVerifyTrust import answer "trusted": the main
   module's import slot for WINTRUST.dll!WinVerifyTrust is pointed at a
   function that returns 0. A program that does not import it statically is
   left alone and the log says so.

Both are logged through DXMT's Logger ("[dlss] ..."), which reaches the
session log. Applied by tools/build-dxmt-nvapi.sh to its copy of nvapi.cpp;
the dxmt submodule is not modified. Usage: patch-nvapi-dlss.py <copy of
nvapi.cpp>. Idempotent; anchor-checked.
"""
import sys

path = sys.argv[1]
src = open(path).read()
MARK = "madeira-doge: DLSS setup"
if MARK in src:
    print("patch-nvapi-dlss: already patched")
    sys.exit(0)

A_STATE = "static std::atomic_uint32_t s_initialization_count = 0;\n"
A_INIT = "NVAPI_INTERFACE\nNvAPI_Initialize() {\n"
A_QI = 'extern "C" __cdecl void *nvapi_QueryInterface(NvU32 id) {\n'
for name, a in (("state", A_STATE), ("NvAPI_Initialize", A_INIT), ("nvapi_QueryInterface", A_QI)):
    if src.count(a) != 1:
        sys.exit("patch-nvapi-dlss: %s anchor not found once" % name)

HELPER = r'''
/* ''' + MARK + r''' (tools/patch-nvapi-dlss.py). */
static LONG WINAPI
madeira_dlss_trusted(HWND, GUID *, void *) {
  static std::atomic_uint32_t calls = 0;
  if (calls++ < 4)
    Logger::info("[dlss] WinVerifyTrust answered: trusted");
  return 0;
}

static void
madeira_dlss_setup() {
  static std::atomic_flag done = ATOMIC_FLAG_INIT;
  if (done.test_and_set())
    return;
  char on[8] = {};
  if (!GetEnvironmentVariableA("MADEIRA_DLSS", on, sizeof(on)) || on[0] != '1')
    return;
  char line[320];

  /* 1. where the NGX client looks for the NGX core */
  WCHAR sys[MAX_PATH] = {};
  UINT n = GetSystemDirectoryW(sys, MAX_PATH);
  HKEY key = nullptr;
  LONG rc = RegCreateKeyExW(
      HKEY_LOCAL_MACHINE, L"SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore", 0, nullptr, 0, KEY_SET_VALUE, nullptr, &key,
      nullptr
  );
  if (rc == ERROR_SUCCESS) {
    rc = RegSetValueExW(key, L"FullPath", 0, REG_SZ, (const BYTE *)sys, (n + 1) * sizeof(WCHAR));
    RegCloseKey(key);
  }
  snprintf(line, sizeof(line), "[dlss] MADEIRA_DLSS=1: NGXCore FullPath = %ls (status %ld)", sys, (long)rc);
  Logger::info(line);
  for (const WCHAR *name : {L"\\nvngx.dll", L"\\_nvngx.dll"}) {
    WCHAR p[MAX_PATH + 16];
    lstrcpyW(p, sys);
    lstrcatW(p, name);
    snprintf(line, sizeof(line), "[dlss] %ls %s", p, GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES ? "is there" : "is MISSING");
    Logger::info(line);
  }

  /* 2. the main module's WINTRUST.dll!WinVerifyTrust import */
  BYTE *base = (BYTE *)GetModuleHandleW(nullptr);
  auto *dos = (IMAGE_DOS_HEADER *)base;
  auto *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
  auto &dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
  bool wintrust = false, patched = false;
  if (dir.VirtualAddress && dir.Size) {
    for (auto *imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); imp->Name; imp++) {
      if (lstrcmpiA((const char *)(base + imp->Name), "WINTRUST.dll"))
        continue;
      wintrust = true;
      auto *names = (IMAGE_THUNK_DATA64 *)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
      auto *slots = (IMAGE_THUNK_DATA64 *)(base + imp->FirstThunk);
      if (!imp->OriginalFirstThunk)
        break; /* bound by name only through the lookup table */
      for (; names->u1.AddressOfData; names++, slots++) {
        if (names->u1.Ordinal & IMAGE_ORDINAL_FLAG64)
          continue;
        auto *by_name = (IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData);
        if (strcmp((const char *)by_name->Name, "WinVerifyTrust"))
          continue;
        DWORD old = 0;
        if (VirtualProtect(&slots->u1.Function, sizeof(ULONGLONG), PAGE_READWRITE, &old)) {
          slots->u1.Function = (ULONGLONG)(void *)&madeira_dlss_trusted;
          VirtualProtect(&slots->u1.Function, sizeof(ULONGLONG), old, &old);
          patched = true;
        }
      }
    }
  }
  snprintf(
      line, sizeof(line), "[dlss] the program's WinVerifyTrust import: %s",
      patched ? "answers trusted from now on" : wintrust ? "WINTRUST.dll is imported but the slot was not changed"
                                                         : "none (WINTRUST.dll is not a static import)"
  );
  Logger::info(line);
}
'''

src = src.replace(A_STATE, A_STATE + HELPER)
src = src.replace(A_INIT, A_INIT + "  madeira_dlss_setup();\n")
src = src.replace(A_QI, A_QI + "  dxmt::madeira_dlss_setup();\n")
if "#include <atomic>" not in src:
    src = "#include <atomic>\n" + src
open(path, "w").write(src)
print("patch-nvapi-dlss: MADEIRA_DLSS setup added")
