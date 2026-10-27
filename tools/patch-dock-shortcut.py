#!/usr/bin/env python3
"""Start a non-Steam program through Valve's client (MADEIRA_DOCK_SHORTCUT=1).

Desktop Steam's "Add a Non-Steam Game": the client starts the program itself
and tells Steam it is being played, so friends see "playing <name>". Madeira
writes the program as a shortcut into the account's
userdata/<accountid>/config/shortcuts.vdf (MadeiraDock.swift), which the
client loads at sign-in, and starts the Dock host with
MADEIRA_STEAM_HOST_APPID = the shortcut's app id (crc32(exe + name) |
0x80000000, as Steam computes it) and MADEIRA_DOCK_SHORTCUT=1.

With that variable the host (madeira-dock/src/session.c, launch.c):
- treats the app as owned (a shortcut has no licence: the entitlement and
  subscription-list questions are skipped, offline and online);
- skips the install-directory check (no Steam install record);
- asks LaunchApp for the shortcut's CGameID ((appid << 32) | 0x02000000,
  k_EGameIDTypeShortcut) instead of a plain app id, and watches that id.
Report field launch-shortcut=1. Without the variable nothing changes.

Build 493 (log 2026-10-27 14:00): the client answered LaunchApp for the
computed shortcut game id with error 5 (no subscription): it did not know the
shortcut from shortcuts.vdf. So the host now registers the shortcut with the
client itself, through its IClientShortcuts (pinned client 71b391fe only):
the per-user record holds the IClientFriendsMap at +0x20 and the
IClientShortcutsMap at +0xf0 (both created by the record initialiser, RVA
0x9ed400); the host finds the record by its friends pointer in private memory,
checks the shortcuts map's vtable (RVA 0x12c87b0), calls slot 8
AddTemporaryShortcut(name, "exe", "") (RVA 0x7096e0, returns the app id) and
slot 1 GetGameIDForAppID(app id) (RVA 0x756340, 64-bit result through a hidden
pointer), and launches that game id. MADEIRA_DOCK_SHORTCUT_NAME /
MADEIRA_DOCK_SHORTCUT_EXE carry the name and the program's Windows path.
Fields: launch-shortcut-record (1 found), launch-shortcut-appid (the client's),
launch-shortcut-gameid-type (2 = shortcut); on any miss the computed id is used.

Build 494 (log 19:35): the temporary shortcut registered (appid from the client,
game id type 2) but LaunchApp on that game id still answered 5: the app
manager's launch is for licensed apps. The desktop client starts shortcuts
through IClientShortcuts::LaunchShortcut (slot 25, RVA 0x81c050, (app id, u32)
-> CAPIJobLaunchShortcut), so the host now calls that for a registered shortcut
(launch-shortcut-call = its return, non-zero taken as started) and keeps
watching the game id; LaunchApp stays the fallback when the client could not
register the shortcut.

Usage: patch-dock-shortcut.py madeira-dock/src/session.c
       patch-dock-shortcut.py madeira-dock/src/launch.c   (both idempotent)
"""
import sys

path = sys.argv[1]
src = open(path).read()

if path.endswith("session.c"):
    if "sh_shortcut_mode" in src:
        print("already patched (session.c)"); sys.exit(0)
    anchor_fn = 'static bool enabled(const char *name)\n'
    helper = ('/* madeira-doge: MADEIRA_DOCK_SHORTCUT, see tools/patch-dock-shortcut.py. */\n'
              'static bool sh_shortcut_mode(void)\n'
              '{\n'
              '    const char *v = getenv("MADEIRA_DOCK_SHORTCUT");\n'
              '    return v && v[0] == \'1\' && !v[1];\n'
              '}\n\n')
    repl = [
        ('            bool entitled = ((subscribed_fn)v[181])(client_user, app);\n',
         '            bool entitled = sh_shortcut_mode() || ((subscribed_fn)v[181])(client_user, app);\n'),
        ('                listed = sh_subscription_list_contains(apps, count, 65536, app);\n',
         '                listed = sh_shortcut_mode() || sh_subscription_list_contains(apps, count, 65536, app);\n'),
        ('            bool entitled = ((subscribed_fn)v[181])(client_user, (uint32_t)app);\n',
         '            bool entitled = sh_shortcut_mode() || ((subscribed_fn)v[181])(client_user, (uint32_t)app);\n'),
        ('                listed = sh_subscription_list_contains(apps, count, 65536, (uint32_t)app);\n',
         '                listed = sh_shortcut_mode() || sh_subscription_list_contains(apps, count, 65536, (uint32_t)app);\n'),
    ]
    for a, _ in repl + [(anchor_fn, None)]:
        if src.count(a) != 1:
            sys.exit("patch-dock-shortcut (session.c): anchor changed (%r found %d times)" % (a.strip()[:50], src.count(a)))
    for a, b in repl:
        src = src.replace(a, b, 1)
    src = src.replace(anchor_fn, helper + anchor_fn, 1)
    open(path, "w").write(src)
    print("madeira-dock: shortcut mode (MADEIRA_DOCK_SHORTCUT) patched into session.c")
    sys.exit(0)

if path.endswith("launch.c"):
    if "sh_launch_shortcut_mode" in src:
        print("already patched (launch.c)"); sys.exit(0)
    # The first definition (the Windows one; a stub follows under #else).
    anchor_fn = '/* madeira-bcd: see tools/patch-dock-game-scm.py. */\n'
    helper = r'''/* madeira-doge: MADEIRA_DOCK_SHORTCUT, see tools/patch-dock-shortcut.py. */
static bool sh_launch_shortcut_mode(void)
{
    wchar_t v[4] = {0};
    return GetEnvironmentVariableW(L"MADEIRA_DOCK_SHORTCUT", v, 4) == 1 && v[0] == L'1';
}

typedef void *(__thiscall *sh_get_friends_fn)(void *, int32_t, int32_t);
typedef uint32_t (__thiscall *sh_add_temp_shortcut_fn)(void *, const char *, const char *, const char *);
typedef uint64_t *(__thiscall *sh_gameid_for_app_fn)(void *, uint64_t *, uint32_t);

/* The per-user record (friends map at +0x20, shortcuts map at +0xf0): the one
 * committed private read-write slot holding the friends pointer whose record
 * carries a shortcuts map with the expected vtable. */
static void *sh_shortcut_map(HMODULE module, void *friends)
{
    const uint64_t want = (uint64_t)(uintptr_t)friends, vt = (uint64_t)(uintptr_t)module + 0x12c87b0;
    void *found = NULL;
    int matches = 0;
    uint64_t scanned = 0;
    MEMORY_BASIC_INFORMATION mbi;
    unsigned char *p = NULL;
    while (VirtualQuery(p, &mbi, sizeof(mbi)) == sizeof(mbi)) {
        unsigned char *next = (unsigned char *)mbi.BaseAddress + mbi.RegionSize;
        if (next <= p) break;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE &&
            (mbi.Protect == PAGE_READWRITE || mbi.Protect == PAGE_EXECUTE_READWRITE) &&
            mbi.RegionSize >= 0x100 && mbi.RegionSize <= ((SIZE_T)1 << 32)) {
            const uint64_t *q = (const uint64_t *)mbi.BaseAddress, *end = (const uint64_t *)(next - 0x100);
            if (scanned + mbi.RegionSize > ((uint64_t)6 << 30)) break;
            scanned += mbi.RegionSize;
            for (; q < end; ++q) {
                if (*q != want) continue;
                const unsigned char *record = (const unsigned char *)q - 0x20;
                if (record < (const unsigned char *)mbi.BaseAddress) continue;
                uint64_t map, mapvt;
                memcpy(&map, record + 0xf0, 8);
                if (!map || map % 8) continue;
                MEMORY_BASIC_INFORMATION m2;
                if (VirtualQuery((void *)(uintptr_t)map, &m2, sizeof(m2)) != sizeof(m2) || m2.State != MEM_COMMIT) continue;
                memcpy(&mapvt, (void *)(uintptr_t)map, 8);
                if (mapvt != vt) continue;
                if (++matches == 1) found = (void *)(uintptr_t)map;
            }
        }
        p = next;
    }
    return matches == 1 ? found : NULL;
}

typedef uint64_t (__thiscall *sh_launch_shortcut_fn)(void *, uint32_t, uint32_t);
static void *sh_shortcut_map_ptr;
static uint32_t sh_shortcut_client_id;

/* Starts a shortcut the client registered (IClientShortcuts::LaunchShortcut). */
static uint64_t sh_shortcut_launch(HMODULE module, uint32_t launch_option, const struct sh_observer *o)
{
    if (!sh_shortcut_map_ptr || !sh_shortcut_client_id) return 0;
    if (!dock_method_is((uintptr_t)module, sh_shortcut_map_ptr, 25, 0x81c050)) { o->event("launch-shortcut-call", -1); return 0; }
    uint64_t r = ((sh_launch_shortcut_fn)(*(void ***)sh_shortcut_map_ptr)[25])(sh_shortcut_map_ptr, sh_shortcut_client_id, launch_option);
    o->event("launch-shortcut-call", (int32_t)(r & 0x7fffffff));
    return r ? r : 0;
}

/* Registers the program as a temporary shortcut with the client and returns its
 * game id; the computed id ((appid << 32) | shortcut type) when anything is missing. */
static uint64_t sh_shortcut_register(HMODULE module, void *engine, int32_t user, int32_t pipe, uint32_t appid,
                                     const struct sh_observer *o)
{
    uint64_t computed = ((uint64_t)appid << 32) | 0x02000000u;
    static char name[512], exe[1024], quoted[1040];
    if (!GetEnvironmentVariableA("MADEIRA_DOCK_SHORTCUT_NAME", name, sizeof(name)) ||
        !GetEnvironmentVariableA("MADEIRA_DOCK_SHORTCUT_EXE", exe, sizeof(exe))) { o->event("launch-shortcut-env", 0); return computed; }
    if (!dock_method_is((uintptr_t)module, engine, 13, 0x943510)) { o->event("launch-shortcut-record", -1); return computed; }
    void *friends = ((sh_get_friends_fn)(*(void ***)engine)[13])(engine, user, pipe);
    if (!friends) { o->event("launch-shortcut-record", -2); return computed; }
    void *map = sh_shortcut_map(module, friends);
    o->event("launch-shortcut-record", map ? 1 : 0);
    if (!map) return computed;
    if (!dock_method_is((uintptr_t)module, map, 8, 0x7096e0) || !dock_method_is((uintptr_t)module, map, 1, 0x756340)) {
        o->event("launch-shortcut-abi", 0); return computed;
    }
    /* The path unquoted: the client quotes it itself (build 495, log 20:43: a quoted path
     * registered, LaunchShortcut returned a handle and the client showed an error box). */
    (void)quoted;
    uint32_t id = ((sh_add_temp_shortcut_fn)(*(void ***)map)[8])(map, name, exe, "");
    o->event("launch-shortcut-appid", (int32_t)id);
    if (!id) return computed;
    sh_shortcut_map_ptr = map; sh_shortcut_client_id = id;
    uint64_t gid = 0;
    ((sh_gameid_for_app_fn)(*(void ***)map)[1])(map, &gid, id);
    o->event("launch-shortcut-gameid-type", (int32_t)((gid >> 24) & 0xff));
    o->event("launch-shortcut-gameid-app", (int32_t)(gid & 0xffffff));
    return gid ? gid : (((uint64_t)id << 32) | 0x02000000u);
}

'''
    block_start = '    static char actual_utf8[32768];\n'
    block_end = '    o->event("launch-install-directory-verified", 1);\n'
    gameid = '    uint64_t gameid = appid;\n'
    gameid_new = ('    /* madeira-doge: a shortcut is launched and watched by its CGameID, registered with\n'
                  '     * the client itself when possible (sh_shortcut_register). */\n'
                  '    uint64_t gameid = sh_launch_shortcut_mode() ? sh_shortcut_register(module, engine, user, pipe, appid, o)\n'
                  '                                                : (uint64_t)appid;\n')
    launch_call = '    uint64_t call = ((launch_fn)(*(void ***)manager)[2])(manager, &gameid, launch_option, 0, "");\n'
    launch_call_new = ('    /* madeira-doge: a registered shortcut starts through IClientShortcuts::LaunchShortcut. */\n'
                       '    uint64_t call = sh_launch_shortcut_mode() && sh_shortcut_client_id\n'
                       '        ? sh_shortcut_launch(module, launch_option, o)\n'
                       '        : ((launch_fn)(*(void ***)manager)[2])(manager, &gameid, launch_option, 0, "");\n')
    for a in (anchor_fn, block_start, block_end, gameid, launch_call):
        if src.count(a) != 1:
            sys.exit("patch-dock-shortcut (launch.c): anchor changed (%r found %d times)" % (a.strip()[:50], src.count(a)))
    s = src.index(block_start); e = src.index(block_end) + len(block_end)
    block = src[s:e]
    wrapped = ('    if (sh_launch_shortcut_mode()) o->event("launch-shortcut", 1);\n'
               '    else {\n' + ''.join('    ' + l + '\n' if l else '\n' for l in block.rstrip('\n').split('\n')) + '    }\n')
    src = src[:s] + wrapped + src[e:]
    src = src.replace(gameid, gameid_new, 1)
    src = src.replace(launch_call, launch_call_new, 1)
    src = src.replace(anchor_fn, helper + anchor_fn, 1)
    open(path, "w").write(src)
    print("madeira-dock: shortcut mode (MADEIRA_DOCK_SHORTCUT) patched into launch.c")
    sys.exit(0)

sys.exit("patch-dock-shortcut: expected session.c or launch.c")
