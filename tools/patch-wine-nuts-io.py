#!/usr/bin/env python3
"""NutsEmu build 1748 Wine patches 0161 and 0162, opt-in per game (LGPL, Evan Bolton).

0162 (sync.c, MADEIRA_YIELD_KEEP_PRIO=1): NtYieldExecution offers the core with
thread_switch(MACH_PORT_NULL, SWITCH_OPTION_NONE, 0) instead of sched_yield().
Darwin's sched_yield() is swtch_pri(0), which drops the calling thread to the
lowest priority for up to a scheduler quantum, so a main thread spin-waiting for
its workers with Sleep(0) / SwitchToThread waits behind every busy thread
(NutsEmu: Elden Ring's main thread ~15% of samples in yields, 1% lows of seconds
while shaders compiled). The fork's adaptive yield (sleep after a streak) still
runs first and is unchanged.

0161 (file.c, MADEIRA_VOL_QUERY_CACHE=1): get_mountmgr_fs_info keeps a
directory's drive letter for 5 s and the mount manager's answer for 1 s. Every
volume query walked the file's path with a stat() per directory, then opened
the mount manager through the server (NutsEmu: Farming Simulator 25 asks for
every file it streams, ~7% of its main thread).

Both default off; [nuts-io] says once per process when one is on.
Usage: patch-wine-nuts-io.py wine/dlls/ntdll/unix/sync.c wine/dlls/ntdll/unix/file.c
Run after the other sync.c / file.c patch scripts. Idempotent; fails by name.
"""
import sys

MARK = "madeira-doge nuts-io"


def patch(path, edits):
    src = open(path).read()
    if MARK in src:
        print(f"patch-wine-nuts-io: {path} already patched")
        return
    for name, old, new in edits:
        n = src.count(old)
        if n != 1:
            print(f"patch-wine-nuts-io: anchor '{name}' found {n} times in {path}", file=sys.stderr)
            sys.exit(1)
        src = src.replace(old, new)
    open(path, "w").write(src)
    print(f"patch-wine-nuts-io: patched {path}")


SYNC = [
    ("mach includes",
     "#ifdef __APPLE__\n# include <mach/mach_time.h>\n",
     "#ifdef __APPLE__\n# include <mach/mach_time.h>\n# include <mach/mach_traps.h>   /* madeira-doge nuts-io */\n# include <mach/thread_switch.h>\n"),
    ("yield",
     "#endif\n#ifdef HAVE_SCHED_YIELD\n#ifdef RUSAGE_THREAD\n    struct rusage u1, u2;",
     """#endif
#ifdef __APPLE__
    {   /* madeira-doge nuts-io (NutsEmu 0162): a yield that keeps the thread's priority.
         * sched_yield() is swtch_pri(0) on Darwin: the thread drops to the lowest
         * priority for up to a quantum and waits behind every busy thread.
         * MADEIRA_YIELD_KEEP_PRIO=1 (per game). */
        static int keep = -1;
        if (keep < 0)
        {
            const char *e = getenv( "MADEIRA_YIELD_KEEP_PRIO" );
            keep = e && *e == '1';
            if (keep) fprintf( stderr, "[nuts-io] yield keeps the thread priority (thread_switch, MADEIRA_YIELD_KEEP_PRIO=1)\\n" );
        }
        if (keep)
        {
            thread_switch( MACH_PORT_NULL, SWITCH_OPTION_NONE, 0 );
            return STATUS_SUCCESS;
        }
    }
#endif
#ifdef HAVE_SCHED_YIELD
#ifdef RUSAGE_THREAD
    struct rusage u1, u2;"""),
]

FILE_OLD = """static NTSTATUS get_mountmgr_fs_info( HANDLE handle, int fd, struct mountmgr_unix_drive *drive, ULONG size )
{
    OBJECT_ATTRIBUTES attr;
    UNICODE_STRING string;
    char *unix_name;
    HANDLE mountmgr;
    unsigned int status;
    int letter = -1;

    if (!server_get_unix_name( handle, &unix_name ))
    {
        letter = find_dos_device( unix_name );
        free( unix_name );
    }
    memset( drive, 0, sizeof(*drive) );
    if (letter == -1)
    {
        struct stat st;

        fstat( fd, &st );
        drive->unix_dev = st.st_rdev ? st.st_rdev : st.st_dev;
    }
    else
        drive->letter = 'a' + letter;

    init_unicode_string( &string, MOUNTMGR_DEVICE_NAME );
    InitializeObjectAttributes( &attr, &string, 0, NULL, NULL );
    status = server_open_file_object( &mountmgr, GENERIC_READ | SYNCHRONIZE, &attr,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_SYNCHRONOUS_IO_NONALERT );
    if (status) return status;

    status = sync_ioctl( mountmgr, IOCTL_MOUNTMGR_QUERY_UNIX_DRIVE, drive, sizeof(*drive), drive, size );
    NtClose( mountmgr );
    if (status == STATUS_BUFFER_OVERFLOW) status = STATUS_SUCCESS;
    else if (status) WARN("failed to retrieve filesystem type from mountmgr, status %#x\\n", status);
    return status;
}
"""

FILE_NEW = """/* madeira-doge nuts-io (NutsEmu 0161): what get_mountmgr_fs_info found, kept a short
 * while. Each volume query walked up the file's path with a stat() per directory
 * (find_dos_device), then opened the mount manager through the server and asked it.
 * A directory's drive letter is kept 5 s, the mount manager's answer 1 s (it carries
 * free space). MADEIRA_VOL_QUERY_CACHE=1 (per game). */
#include <time.h>
#define NUTS_FS_INFO_CACHE 16
static pthread_mutex_t nuts_fs_info_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct { char *dir; int letter; ULONGLONG time; } nuts_fs_letters[NUTS_FS_INFO_CACHE];
static struct { int letter; ULONG64 dev; ULONG size; NTSTATUS status; char *data; ULONGLONG time; } nuts_fs_replies[NUTS_FS_INFO_CACHE];
static unsigned int nuts_fs_letter_next, nuts_fs_reply_next;

static int nuts_vol_cache_on(void)
{
    static int on = -1;
    if (on < 0)
    {
        const char *e = getenv( "MADEIRA_VOL_QUERY_CACHE" );
        on = e && *e == '1';
        if (on) fprintf( stderr, "[nuts-io] volume queries cached (drive letter 5 s, mount manager 1 s, MADEIRA_VOL_QUERY_CACHE=1)\\n" );
    }
    return on;
}

static ULONGLONG nuts_fs_now_ms(void)
{
    struct timespec ts;
    clock_gettime( CLOCK_MONOTONIC, &ts );
    return (ULONGLONG)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* the drive letter of a file's directory (or of a directory itself) */
static int nuts_cached_dos_device( const char *path, BOOL is_file )
{
    const char *slash = is_file ? strrchr( path, '/' ) : NULL;
    size_t len = slash && slash != path ? (size_t)(slash - path) : strlen( path );
    ULONGLONG now = nuts_fs_now_ms();
    unsigned int i;
    char *dir;
    int letter;

    mutex_lock( &nuts_fs_info_mutex );
    for (i = 0; i < NUTS_FS_INFO_CACHE; i++)
        if (nuts_fs_letters[i].dir && now - nuts_fs_letters[i].time < 5000 && strlen( nuts_fs_letters[i].dir ) == len &&
            !memcmp( nuts_fs_letters[i].dir, path, len ))
        {
            letter = nuts_fs_letters[i].letter;
            mutex_unlock( &nuts_fs_info_mutex );
            return letter;
        }
    mutex_unlock( &nuts_fs_info_mutex );

    if (!(dir = malloc( len + 1 ))) return find_dos_device( path );
    memcpy( dir, path, len );
    dir[len] = 0;
    letter = find_dos_device( dir );
    mutex_lock( &nuts_fs_info_mutex );
    i = nuts_fs_letter_next++ % NUTS_FS_INFO_CACHE;
    free( nuts_fs_letters[i].dir );
    nuts_fs_letters[i].dir = dir;
    nuts_fs_letters[i].letter = letter;
    nuts_fs_letters[i].time = now;
    mutex_unlock( &nuts_fs_info_mutex );
    return letter;
}

static NTSTATUS get_mountmgr_fs_info( HANDLE handle, int fd, struct mountmgr_unix_drive *drive, ULONG size )
{
    OBJECT_ATTRIBUTES attr;
    UNICODE_STRING string;
    char *unix_name;
    HANDLE mountmgr;
    unsigned int status, i;
    int letter = -1;
    int cache = nuts_vol_cache_on();
    struct stat st;
    BOOL have_st = !fstat( fd, &st );
    ULONGLONG now = 0;
    int asked_letter;
    ULONG64 asked_dev;
    char *copy;

    if (!server_get_unix_name( handle, &unix_name ))
    {
        letter = cache ? nuts_cached_dos_device( unix_name, have_st && !S_ISDIR( st.st_mode ) )
                       : find_dos_device( unix_name );
        free( unix_name );
    }
    memset( drive, 0, sizeof(*drive) );
    if (letter == -1)
    {
        if (!have_st) memset( &st, 0, sizeof(st) );
        drive->unix_dev = st.st_rdev ? st.st_rdev : st.st_dev;
    }
    else
        drive->letter = 'a' + letter;

    if (cache)
    {
        now = nuts_fs_now_ms();
        mutex_lock( &nuts_fs_info_mutex );
        for (i = 0; i < NUTS_FS_INFO_CACHE; i++)
            if (nuts_fs_replies[i].data && now - nuts_fs_replies[i].time < 1000 && nuts_fs_replies[i].letter == drive->letter &&
                nuts_fs_replies[i].dev == drive->unix_dev && nuts_fs_replies[i].size == size)
            {
                memcpy( drive, nuts_fs_replies[i].data, size );
                status = nuts_fs_replies[i].status;
                mutex_unlock( &nuts_fs_info_mutex );
                return status;
            }
        mutex_unlock( &nuts_fs_info_mutex );
    }
    asked_letter = drive->letter;
    asked_dev = drive->unix_dev;

    init_unicode_string( &string, MOUNTMGR_DEVICE_NAME );
    InitializeObjectAttributes( &attr, &string, 0, NULL, NULL );
    status = server_open_file_object( &mountmgr, GENERIC_READ | SYNCHRONIZE, &attr,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_SYNCHRONOUS_IO_NONALERT );
    if (status) return status;

    status = sync_ioctl( mountmgr, IOCTL_MOUNTMGR_QUERY_UNIX_DRIVE, drive, sizeof(*drive), drive, size );
    NtClose( mountmgr );
    if (status == STATUS_BUFFER_OVERFLOW) status = STATUS_SUCCESS;
    else if (status) WARN("failed to retrieve filesystem type from mountmgr, status %#x\\n", status);

    if (cache && !status && (copy = malloc( size )))
    {
        memcpy( copy, drive, size );
        mutex_lock( &nuts_fs_info_mutex );
        i = nuts_fs_reply_next++ % NUTS_FS_INFO_CACHE;
        free( nuts_fs_replies[i].data );
        nuts_fs_replies[i].letter = asked_letter;
        nuts_fs_replies[i].dev = asked_dev;
        nuts_fs_replies[i].size = size;
        nuts_fs_replies[i].status = status;
        nuts_fs_replies[i].data = copy;
        nuts_fs_replies[i].time = now;
        mutex_unlock( &nuts_fs_info_mutex );
    }
    return status;
}
"""


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-3])
        sys.exit(2)
    patch(sys.argv[1], SYNC)
    patch(sys.argv[2], [("get_mountmgr_fs_info", FILE_OLD, FILE_NEW)])


if __name__ == "__main__":
    main()
