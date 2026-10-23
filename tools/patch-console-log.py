#!/usr/bin/env python3
"""madeira-doge: copy every program's console output into the Madeira log.

Programs that AllocConsole() and print to it (Gundam EXVS2 IB's bngrw.dll logs
every emulated card-reader / serial / file call there) show nothing on iOS: the
console has no window. The wineserver sees each write before it forwards it to
conhost, so print it as "[console] pid=...: text" lines on stderr (the session
log). WriteConsoleW (IOCTL_CONDRV_WRITE_CONSOLE, UTF-16) and WriteFile on a
console handle (bytes) are both covered. At most 20000 lines per server run.
MADEIRA_CONSOLE_LOG=0 turns it off.

Patches a copy of server/console.c; idempotent.
"""
import sys

MARK = "tools/patch-console-log.py"

HELPER_ANCHOR = '#include "wine/condrv.h"\n'
HELPER = HELPER_ANCHOR + r'''
#include <stdlib.h>
/* madeira-doge: console output -> session log (tools/patch-console-log.py) */
static int madeira_console_log_on = -1;
static unsigned int madeira_console_lines;
static void madeira_console_emit( const char *text, size_t len )
{
    static char line[1024];
    static size_t used;
    size_t i;
    for (i = 0; i < len; i++)
    {
        char c = text[i];
        if (c == '\r') continue;
        if (c == '\n' || used >= sizeof(line) - 1)
        {
            if (madeira_console_lines < 20000)
            {
                fprintf( stderr, "[console] madeira-doge pid=%04x: %.*s\n",
                         current && current->process ? current->process->id : 0, (int)used, line );
                if (++madeira_console_lines == 20000)
                    fprintf( stderr, "[console] madeira-doge: 20000 lines logged, the rest is not\n" );
            }
            used = 0;
            if (c == '\n') continue;
        }
        line[used++] = c;
    }
}
static void madeira_console_log( int wide, const void *data, size_t size )
{
    if (madeira_console_log_on < 0)
    {
        static const char name[] = "MADEIRA_CONSOLE_LOG";
        const char *e = getenv( name );
        madeira_console_log_on = !(e && *e == '0');
    }
    if (!madeira_console_log_on || !data || !size) return;
    if (!wide) { madeira_console_emit( data, size ); return; }
    {
        const unsigned short *w = data;
        size_t n = size / 2, i;
        char buf[4];
        for (i = 0; i < n; i++)
        {
            unsigned int ch = w[i];
            size_t k = 0;
            if (ch < 0x80) buf[k++] = ch;
            else if (ch < 0x800) { buf[k++] = 0xc0 | (ch >> 6); buf[k++] = 0x80 | (ch & 0x3f); }
            else { buf[k++] = 0xe0 | (ch >> 12); buf[k++] = 0x80 | ((ch >> 6) & 0x3f); buf[k++] = 0x80 | (ch & 0x3f); }
            madeira_console_emit( buf, k );
        }
    }
}
'''

WRITE_ANCHOR = """static void screen_buffer_write( struct fd *fd, struct async *async, file_pos_t pos )
{
    struct screen_buffer *screen_buffer = get_fd_user( fd );
"""
WRITE_NEW = WRITE_ANCHOR + """
    madeira_console_log( 0, get_req_data(), get_req_data_size() );   /* madeira-doge */
"""

IOCTL_ANCHOR = """static void screen_buffer_ioctl( struct fd *fd, ioctl_code_t code, struct async *async )
{
    struct screen_buffer *screen_buffer = get_fd_user( fd );
"""
IOCTL_NEW = IOCTL_ANCHOR + """
    if (code == IOCTL_CONDRV_WRITE_CONSOLE)   /* madeira-doge */
        madeira_console_log( 1, get_req_data(), get_req_data_size() );
"""


def main(src, dst):
    s = open(src, encoding="utf-8", errors="surrogateescape").read()
    if MARK not in s:
        for old, new in ((HELPER_ANCHOR, HELPER), (WRITE_ANCHOR, WRITE_NEW), (IOCTL_ANCHOR, IOCTL_NEW)):
            if s.count(old) != 1:
                print("patch-console-log: anchor not found once: " + old.splitlines()[0], file=sys.stderr)
                return 1
            s = s.replace(old, new)
    open(dst, "w", encoding="utf-8", errors="surrogateescape").write(s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
