#!/usr/bin/env python3
"""UDP broadcast sends fan out to local unicast addresses (iOS has no broadcast).

iOS refuses every IPv4 broadcast send without the multicast entitlement
(sendmsg: EHOSTUNREACH, WS2_sendto 0xc000023d). Wine processes on the same
phone that find each other by broadcast (EXVS2 cabinet + LM on 49000..49015,
48011) never meet. try_send() now sends a datagram addressed to
255.255.255.255 or to a local interface's directed broadcast as unicast to
127.0.0.1:<port> and to every local IPv4 address on <port> instead, and reports
the full length when at least one copy went out. A socket bound to 0.0.0.0:P
gets the loopback copy; one bound to 192.168.x.y:P gets the copy to that
address. The sender may receive its own copy, as on Windows. If every copy
fails, the original sendmsg runs as before.

Log: [sock-bcast] madeira-doge fan-out port=P sent=N/M (first 32, then every
256th).

Patches wine/dlls/ntdll/unix/socket.c in place. Idempotent.
Usage: patch-wine-sock-bcast.py wine/dlls/ntdll/unix/socket.c
"""
import sys

MARKER = "madeira-doge sock-bcast"

path = sys.argv[1]
src = open(path).read()
if MARKER in src:
    print("already patched"); sys.exit(0)

HELPERS = r'''#ifdef __APPLE__
/* madeira-doge sock-bcast (tools/patch-wine-sock-bcast.py): iOS rejects IPv4
 * broadcast sends; deliver them as unicast to loopback and every local IPv4
 * address on the same port. */
#include <ifaddrs.h>
#include <net/if.h>

static int madeira_bcast_is_broadcast( in_addr_t dst )
{
    struct ifaddrs *ifs, *ifa;
    int hit = 0;

    if (dst == htonl( INADDR_BROADCAST )) return 1;
    if (getifaddrs( &ifs ) < 0) return 0;
    for (ifa = ifs; ifa && !hit; ifa = ifa->ifa_next)
    {
        in_addr_t addr, mask;
        if (!ifa->ifa_addr || ifa->ifa_addr->sa_family != AF_INET) continue;
        if (!ifa->ifa_netmask || (ifa->ifa_flags & IFF_LOOPBACK)) continue;
        addr = ((struct sockaddr_in *)ifa->ifa_addr)->sin_addr.s_addr;
        mask = ((struct sockaddr_in *)ifa->ifa_netmask)->sin_addr.s_addr;
        if (mask != 0xffffffff && dst == (addr | ~mask)) hit = 1;
        else if ((ifa->ifa_flags & IFF_BROADCAST) && ifa->ifa_broadaddr
                 && ifa->ifa_broadaddr->sa_family == AF_INET
                 && ((struct sockaddr_in *)ifa->ifa_broadaddr)->sin_addr.s_addr == dst) hit = 1;
    }
    freeifaddrs( ifs );
    return hit;
}

/* Returns the bytes sent (the datagram length) or -1 when no copy went out. */
static ssize_t madeira_bcast_fanout( int fd, const struct msghdr *orig, int flags,
                                     const struct sockaddr_in *dst )
{
    static unsigned int calls;
    struct ifaddrs *ifs = NULL, *ifa;
    in_addr_t targets[32];
    int count = 0, sent = 0, i;
    ssize_t best = -1;
    unsigned int n;

    targets[count++] = htonl( INADDR_LOOPBACK );
    if (getifaddrs( &ifs ) == 0)
    {
        for (ifa = ifs; ifa && count < 32; ifa = ifa->ifa_next)
        {
            in_addr_t addr;
            if (!ifa->ifa_addr || ifa->ifa_addr->sa_family != AF_INET) continue;
            if (!(ifa->ifa_flags & IFF_UP)) continue;
            addr = ((struct sockaddr_in *)ifa->ifa_addr)->sin_addr.s_addr;
            if (!addr) continue;
            for (i = 0; i < count; i++) if (targets[i] == addr) break;
            if (i == count) targets[count++] = addr;
        }
        freeifaddrs( ifs );
    }

    for (i = 0; i < count; i++)
    {
        struct sockaddr_in to = *dst;
        struct msghdr hdr = *orig;
        ssize_t ret;

        to.sin_addr.s_addr = targets[i];
        hdr.msg_name = &to;
        hdr.msg_namelen = sizeof(to);
        do ret = sendmsg( fd, &hdr, flags ); while (ret == -1 && errno == EINTR);
        if (ret >= 0)
        {
            sent++;
            if (ret > best) best = ret;
        }
    }

    n = __atomic_fetch_add( &calls, 1, __ATOMIC_RELAXED );
    if (n < 32 || !(n % 256))
        dprintf( 2, "[sock-bcast] madeira-doge fan-out port=%u sent=%d/%d dst=%08x n=%u\n",
                 ntohs( dst->sin_port ), sent, count, ntohl( dst->sin_addr.s_addr ), n + 1 );
    return best;
}
#endif

'''

anchor = "static NTSTATUS try_send( int fd, struct async_send_ioctl *async )\n{\n"
if src.count(anchor) != 1:
    sys.exit("patch-wine-sock-bcast: try_send anchor not found exactly once")
src = src.replace(anchor, HELPERS + anchor)

loop = """    hdr.msg_iov = async->iov + async->iov_cursor;
    hdr.msg_iovlen = async->count - async->iov_cursor;

    while ((ret = sendmsg( fd, &hdr, async->unix_flags )) == -1)
"""
if src.count(loop) != 1:
    sys.exit("patch-wine-sock-bcast: sendmsg loop anchor not found exactly once")
src = src.replace(loop, """    hdr.msg_iov = async->iov + async->iov_cursor;
    hdr.msg_iovlen = async->count - async->iov_cursor;

#ifdef __APPLE__
    if (hdr.msg_name && sock_type == SOCK_DGRAM && unix_addr.addr.sa_family == AF_INET
        && madeira_bcast_is_broadcast( unix_addr.in.sin_addr.s_addr ))
    {
        ret = madeira_bcast_fanout( fd, &hdr, async->unix_flags, &unix_addr.in );
        if (ret >= 0) goto madeira_bcast_sent;
    }
#endif

    while ((ret = sendmsg( fd, &hdr, async->unix_flags )) == -1)
""")

after = """    async->sent_len += ret;
    ios_sock_big_note( fd, 1, ret, 0 );
"""
if src.count(after) != 1:
    sys.exit("patch-wine-sock-bcast: sent_len anchor not found exactly once")
src = src.replace(after, """#ifdef __APPLE__
madeira_bcast_sent:
#endif
""" + after)

open(path, "w").write(src)
print("patched " + path)
