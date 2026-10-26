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
    helper = ('/* madeira-doge: MADEIRA_DOCK_SHORTCUT, see tools/patch-dock-shortcut.py. */\n'
              'static bool sh_launch_shortcut_mode(void)\n'
              '{\n'
              '    wchar_t v[4] = {0};\n'
              '    return GetEnvironmentVariableW(L"MADEIRA_DOCK_SHORTCUT", v, 4) == 1 && v[0] == L\'1\';\n'
              '}\n\n')
    block_start = '    static char actual_utf8[32768];\n'
    block_end = '    o->event("launch-install-directory-verified", 1);\n'
    gameid = '    uint64_t gameid = appid;\n'
    gameid_new = ('    /* madeira-doge: a shortcut is launched and watched by its CGameID. */\n'
                  '    uint64_t gameid = sh_launch_shortcut_mode() ? (((uint64_t)appid << 32) | 0x02000000u) : (uint64_t)appid;\n')
    for a in (anchor_fn, block_start, block_end, gameid):
        if src.count(a) != 1:
            sys.exit("patch-dock-shortcut (launch.c): anchor changed (%r found %d times)" % (a.strip()[:50], src.count(a)))
    s = src.index(block_start); e = src.index(block_end) + len(block_end)
    block = src[s:e]
    wrapped = ('    if (sh_launch_shortcut_mode()) o->event("launch-shortcut", 1);\n'
               '    else {\n' + ''.join('    ' + l + '\n' if l else '\n' for l in block.rstrip('\n').split('\n')) + '    }\n')
    src = src[:s] + wrapped + src[e:]
    src = src.replace(gameid, gameid_new, 1)
    src = src.replace(anchor_fn, helper + anchor_fn, 1)
    open(path, "w").write(src)
    print("madeira-dock: shortcut mode (MADEIRA_DOCK_SHORTCUT) patched into launch.c")
    sys.exit(0)

sys.exit("patch-dock-shortcut: expected session.c or launch.c")
