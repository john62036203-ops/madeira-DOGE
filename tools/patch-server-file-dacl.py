#!/usr/bin/env python3
"""madeira-doge: a world-readable file's default DACL also allows BUILTIN\\Users to read
(NutsEmu Build 1650, Wine patch 0141-default-dacl-allows-users-to-read, LGPL-2.1,
"Generated-by: LLM").

Wine builds a file's DACL from its Unix mode: SYSTEM, the owner and Everyone.
Windows' own folders also allow BUILTIN\\Users to read. Steam's hardware survey
module (run by SteamService in its only module thread) picks folders of
C:\\windows and system32 until one's DACL allows READ_CONTROL to Authenticated
Users or Users; with none it never stopped, and Steam's DRM step for a game
(its per-user executable, made in that same thread) failed after 100 s with
RemoteCallFailed on every try (NutsEmu, Black Ops, 2026-10-21). World-readable
files and folders now also allow BUILTIN\\Users FILE_GENERIC_READ |
FILE_GENERIC_EXECUTE (inherited like the others on folders).

Usage: patch-server-file-dacl.py wine/server/file.c [out.c]
Patches a copy; idempotent.
"""
import sys

MARK = "tools/patch-server-file-dacl.py"

SIZE_OLD = "    if (mode & S_IRWXO) dacl_size += sizeof(*ace) + sid_len( &world_sid );\n"
SIZE_NEW = SIZE_OLD + "    if (mode & S_IROTH) dacl_size += sizeof(*ace) + sid_len( &builtin_users_sid );  /* madeira-doge: tools/patch-server-file-dacl.py */\n"

COUNT_OLD = "    if (mode & S_IRWXO) dacl->count++;\n"
COUNT_NEW = COUNT_OLD + "    if (mode & S_IROTH) dacl->count++;  /* madeira-doge (NutsEmu 0141) */\n"

ACE_OLD = '''        if (mode & S_IWOTH) ace->mask |= FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD;
    }
'''
ACE_NEW = ACE_OLD + '''    /* madeira-doge (NutsEmu 0141): and read for BUILTIN\\Users, as Windows gives it on its own
     * folders. Steam's hardware survey (SteamService's only module thread) picks folders of
     * C:\\windows and system32 until one's DACL allows READ_CONTROL to Authenticated Users or
     * Users; with only SYSTEM, the owner and Everyone it never found one, and Steam's DRM step
     * for the game, waiting behind it in that thread, failed after 100 s (RemoteCallFailed). */
    if (mode & S_IROTH)
        set_ace( ace_next( ace ), &builtin_users_sid, ACCESS_ALLOWED_ACE_TYPE, flags,
                 FILE_GENERIC_READ | FILE_GENERIC_EXECUTE );
'''


def main(src, dst):
    s = open(src, encoding="utf-8", errors="surrogateescape").read()
    if MARK not in s:
        for name, old in (("size", SIZE_OLD), ("count", COUNT_OLD), ("ace", ACE_OLD)):
            if s.count(old) != 1:
                print("patch-server-file-dacl: anchor '%s' found %d times, expected 1" % (name, s.count(old)), file=sys.stderr)
                return 1
        s = s.replace(SIZE_OLD, SIZE_NEW).replace(COUNT_OLD, COUNT_NEW).replace(ACE_OLD, ACE_NEW)
    open(dst, "w", encoding="utf-8", errors="surrogateescape").write(s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
