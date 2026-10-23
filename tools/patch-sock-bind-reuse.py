#!/usr/bin/env python3
"""madeira-doge: Windows bind semantics for a wildcard/specific pair on one UDP port.

Windows lets a socket bind 0.0.0.0:P while another holds 127.0.0.1:P (and
the reverse) unless SO_EXCLUSIVEADDRUSE is set. Darwin refuses the second
bind with EADDRINUSE unless SO_REUSEADDR is set on it. Gundam EXVS2 IB's
cabinet binds 127.0.0.1:49000 and its LiveMonitor then binds 0.0.0.0:49000:
on iOS the LM got STATUS_SHARING_VIOLATION (0xc0000043), never heard the
cabinet, and both stalled after MTHD_REGISTER_PCB (2026-10-23 07:42 log).

Wine already tracks winsock address conflicts itself (check_addr_usage runs
before the host bind), so when the HOST bind of a datagram socket fails with
EADDRINUSE and the socket is not exclusive, set SO_REUSEADDR on the unix fd
and retry once. Patches a copy of server/sock.c; idempotent.
"""
import sys

OLD = """        if (bind( unix_fd, &bind_addr.addr, unix_len ) < 0)
        {
            if (errno == EADDRINUSE && sock->reuseaddr)"""
NEW = """        /* madeira-doge: Windows wildcard/specific UDP bind (tools/patch-sock-bind-reuse.py v2).
         * Darwin's in_pcbbind refuses 0.0.0.0:P next to 192.168.x.y:P unless BOTH sockets have
         * SO_REUSEPORT (127.0.0.1 happened to pass with SO_REUSEADDR alone). Exact duplicates are
         * still refused by check_addr_usage above, which keeps Windows semantics for those. */
        if (sock->type == WS_SOCK_DGRAM && !sock->exclusiveaddruse)
            setsockopt( unix_fd, SOL_SOCKET, SO_REUSEPORT, &(int){1}, sizeof(int) );
        if (bind( unix_fd, &bind_addr.addr, unix_len ) < 0
            && !(errno == EADDRINUSE && sock->type == WS_SOCK_DGRAM && !sock->exclusiveaddruse
                 && !setsockopt( unix_fd, SOL_SOCKET, SO_REUSEADDR, &(int){1}, sizeof(int) )
                 && (fprintf( stderr, "[sock-bind] madeira-doge: UDP port in use by another address; "
                              "retrying with SO_REUSEADDR+SO_REUSEPORT (Windows semantics)\\n" ), 1)
                 && (!bind( unix_fd, &bind_addr.addr, unix_len )
                     || ({ int e_ = errno; fprintf( stderr, "[sock-bind] madeira-doge: retry failed, errno %d\\n", e_ ); errno = e_; 0; }))))
        {
            if (errno == EADDRINUSE && sock->reuseaddr)"""

def main(src, dst):
    s = open(src, encoding="utf-8", errors="surrogateescape").read()
    if "tools/patch-sock-bind-reuse.py" not in s:
        if s.count(OLD) != 1:
            print("patch-sock-bind-reuse: anchor not found once", file=sys.stderr)
            return 1
        s = s.replace(OLD, NEW)
    open(dst, "w", encoding="utf-8", errors="surrogateescape").write(s)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
