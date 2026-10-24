#!/usr/bin/env python3
"""Show friends what is being played: set the Dock client's persona state online.

Madeira Dock (madeira-dock/src/session.c, upstream submodule) signs Valve's
genuine client in and starts the game with LaunchApp; the client then reports
the running game to Steam itself. Without the Steam desktop UI the headless
client never sets a persona state, so the account stays offline to friends and
"playing <game>" is not shown. Once the client reports the account signed in,
this asks it to go online through its own IClientFriends::SetPersonaState.

Pinned to the January 2026 client (SHA-256 71b391fe..., layout 202601, the one
Madeira downloads), found by RTTI + IPC name on 2026-10-24:
  IClientEngine slot 13  GetIClientFriends(hUser, hPipe)  RVA 0x943510
      (same wrapper as slot 8 GetIClientUser; returns the per-user record's
       +0x20 field, where the IClientFriendsMap factory's result is stored)
  IClientFriendsMap slot 4  GetPersonaState()     RVA 0x768a20 (IPC 0x534bc194)
  IClientFriendsMap slot 5  SetPersonaState(int)  RVA 0x848460 (IPC 0xe333cf87)
Any other client, or a method pointer that does not match, skips the call
(report field presence-unsupported / presence-abi-mismatch); sign-in, licence
check and launch are untouched either way.

env.MADEIRA_DOCK_PRESENCE: unset or 1 = online (default), 3 = away,
7 = invisible (signed in, not shown), 0 = do not touch the persona state.
Report fields: presence-before (state the client had), presence-set.

Usage: patch-dock-presence.py madeira-dock/src/session.c (idempotent)
"""
import sys

path = sys.argv[1]
src = open(path).read()
if "MADEIRA_DOCK_PRESENCE" in src:
    print("already patched"); sys.exit(0)

anchor_fn = 'static bool enabled(const char *name)\n'
helper = r'''/* madeira-doge: MADEIRA_DOCK_PRESENCE, see tools/patch-dock-presence.py. */
typedef void *(__thiscall *madeira_get_friends_fn)(void *, int32_t, int32_t);
typedef int32_t (__thiscall *madeira_get_persona_fn)(void *);
typedef void (__thiscall *madeira_set_persona_fn)(void *, int32_t);
static void madeira_presence(HMODULE module, void *engine, int32_t user, int32_t pipe,
                             const struct dock_client_layout *layout, const struct sh_observer *o)
{
    const char *setting = getenv("MADEIRA_DOCK_PRESENCE");
    long state = setting && *setting ? strtol(setting, NULL, 10) : 1;
    if (state == 0) { o->event("presence-off", 1); return; }
    if (state < 1 || state > 7) state = 1;
    if (!layout || layout->revision != 202601) { o->event("presence-unsupported", 1); return; }
    if (!dock_method_is((uintptr_t)module, engine, 13, 0x943510)) { o->event("presence-abi-mismatch", 13); return; }
    void *friends = ((madeira_get_friends_fn)(*(void ***)engine)[13])(engine, user, pipe);
    if (!friends) { o->event("presence-friends-missing", 1); return; }
    if (!dock_method_is((uintptr_t)module, friends, 4, 0x768a20) ||
        !dock_method_is((uintptr_t)module, friends, 5, 0x848460)) { o->event("presence-abi-mismatch", 5); return; }
    void **f = *(void ***)friends;
    o->event("presence-before", ((madeira_get_persona_fn)f[4])(friends));
    ((madeira_set_persona_fn)f[5])(friends, (int32_t)state);
    o->event("presence-set", (int32_t)state);
}

''' + anchor_fn

online = '                o->event("session-authenticated-online", 1);\n'
call = online + '                if (!presence_done) { presence_done = true; madeira_presence(module, engine, user, pipe, layout, o); }\n'

decl = '    bool was_online = false, offline_reported = false;\n'
decl_new = decl + '    bool presence_done = false;\n'

for anchor, n in ((anchor_fn, 1), (online, 1), (decl, 1)):
    if src.count(anchor) != n:
        sys.exit("patch-dock-presence: anchor changed (%r found %d times)" % (anchor.strip(), src.count(anchor)))
src = src.replace(anchor_fn, helper, 1).replace(online, call, 1).replace(decl, decl_new, 1)
if '#include "client_layout.h"' not in src and 'client_layout.h' not in open(path.replace("session.c", "session.h")).read():
    src = src.replace('#include "session.h"\n', '#include "session.h"\n#include "client_layout.h"\n', 1)
open(path, "w").write(src)
print("madeira-dock: persona state (MADEIRA_DOCK_PRESENCE) patched into session.c")
