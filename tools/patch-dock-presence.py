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
Report fields: presence-before (state the client had), presence-step (the state
passed through when it already had the requested one), presence-set, presence-after,
presence-step-echo / presence-set-echo (change flags of Steam's PersonaStateChange
for this account, -1 = none came back within 2-3 s), presence-friend-updates.

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
/* Serves the client's callbacks for ms milliseconds and reports
 * PersonaStateChange_t (304: uint64 steamid, int32 change flags) for this
 * account: Steam's servers send it back when they took the new state. */
static void madeira_presence_pump(const struct sh_api *api, int32_t pipe, uint64_t self,
                                  uint32_t ms, const struct sh_observer *o, const char *tag)
{
    uint64_t begin = o->now_ms();
    int32_t echoes = 0, others = 0;
    while (o->now_ms() - begin < ms) {
        for (unsigned batch = 0; batch < 64; ++batch) {
            struct sh_callback cb = {0};
            if (!api->get_callback(pipe, &cb)) break;
            if (cb.id == 304 && cb.data && cb.size >= 12) {
                uint64_t who; int32_t flags;
                memcpy(&who, cb.data, 8); memcpy(&flags, (const char *)cb.data + 8, 4);
                if (who == self) { if (++echoes <= 4) o->event(tag, flags); }
                else ++others;
            }
            api->free_callback(pipe);
        }
        o->sleep_ms(50);
    }
    if (!echoes) o->event(tag, -1);
    o->event("presence-friend-updates", others);
}

static void madeira_presence(HMODULE module, void *engine, const struct sh_api *api, int32_t user, int32_t pipe,
                             uint64_t self, const struct dock_client_layout *layout, const struct sh_observer *o)
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
    int32_t before = ((madeira_get_persona_fn)f[4])(friends);
    o->event("presence-before", before);
    /* The headless client already holds "online" locally (build 430 log,
     * 2026-10-24 13:51: presence-before=1), so asking for the same state was a
     * no-op and Steam was never told. Step through another state first so the
     * client sees a real change and sends it to Steam. */
    if (before == (int32_t)state) {
        int32_t step = state == 7 ? 1 : 7;
        ((madeira_set_persona_fn)f[5])(friends, step);
        o->event("presence-step", step);
        madeira_presence_pump(api, pipe, self, 2000, o, "presence-step-echo");
    }
    ((madeira_set_persona_fn)f[5])(friends, (int32_t)state);
    o->event("presence-set", (int32_t)state);
    madeira_presence_pump(api, pipe, self, 3000, o, "presence-set-echo");
    o->event("presence-after", ((madeira_get_persona_fn)f[4])(friends));
}

''' + anchor_fn

online = '                o->event("session-authenticated-online", 1);\n'
call = online + '                if (!presence_done) { presence_done = true; madeira_presence(module, engine, api, user, pipe, id, layout, o); }\n'

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
