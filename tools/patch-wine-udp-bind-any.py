#!/usr/bin/env python3
"""UDP sockets bound to a specific local IPv4 address bind to 0.0.0.0 on iOS.

wineserver's IOCTL_AFD_BIND turns a bind to a local interface address
(192.168.x.y:P) into bind(0.0.0.0:P) + IP_BOUND_IF=<that interface>
(bind_to_interface -> bind_to_iface_name, the IP_BOUND_IF variant Darwin
compiles). The socket then only receives datagrams that arrive THROUGH that
interface. With the sock-bcast fan-out (tools/patch-wine-sock-bcast.py) a
broadcast is delivered as unicast to 127.0.0.1 and to every local address:
the loopback copy is filtered out by IP_BOUND_IF, and the copy to the
interface's own address is what the socket got on Wi-Fi.

EXVS2 (phone-only launcher) finds its own cabinet that way on 49000. With
Wi-Fi off (airplane mode, which the owner needs for JIT) the game binds to
whatever interface is left (a utun/cellular address): the unicast copy to it
fails (EHOSTUNREACH, [sock-bcast] "sent=1/5" every 0.1 s, log 12:59) and the
loopback copy never passes IP_BOUND_IF, so the game sits on しばらくお待ち下さい
re-asking ISSUE_NODE_ID forever (log 12:59:23).

Patched: on Darwin a DGRAM bind to any specific IPv4 address becomes a plain
bind(0.0.0.0:P) with SO_REUSEADDR and no IP_BOUND_IF, so the loopback copy
reaches it whatever the interfaces are. getsockname still reports the
requested address (unchanged code after bind). MADEIRA_UDP_BIND_IF=1 in
wineserver's environment restores the pinned behaviour. Logs
[udp-bind] madeira-doge a.b.c.d:P -> 0.0.0.0:P (first 16).

Patches wine/server/sock.c in place. Idempotent.
Usage: patch-wine-udp-bind-any.py wine/server/sock.c
"""
import sys

MARKER = "madeira-doge udp-bind-any"

path = sys.argv[1]
src = open(path).read()
if MARKER in src:
    print("already patched"); sys.exit(0)

anchor = """    if (bind_addr == htonl( INADDR_ANY ) || bind_addr == htonl( INADDR_LOOPBACK ))
        return 0;
    if (sock->type != WS_SOCK_DGRAM)
        return 0;

    if (getifaddrs( &ifaddrs ) < 0) return 0;
"""
if src.count(anchor) != 1:
    sys.exit("patch-wine-udp-bind-any: bind_to_interface anchor not found exactly once")

src = src.replace(anchor, """    if (bind_addr == htonl( INADDR_ANY ) || bind_addr == htonl( INADDR_LOOPBACK ))
        return 0;
    if (sock->type != WS_SOCK_DGRAM)
        return 0;

#ifdef __APPLE__
    {   /* madeira-doge udp-bind-any (tools/patch-wine-udp-bind-any.py): no
         * IP_BOUND_IF, so the sock-bcast loopback copy of a broadcast reaches
         * a socket the game bound to its LAN address even with Wi-Fi off. */
        static int keep = -1;
        static unsigned int said;
        if (keep < 0) { const char *v = getenv( "MADEIRA_UDP_BIND_IF" ); keep = v && *v == '1'; }
        if (!keep)
        {
            static const int enable = 1;
            unsigned char *b = (unsigned char *)&bind_addr;
            setsockopt( fd, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(enable) );
            if (said++ < 16)
                fprintf( stderr, "[udp-bind] madeira-doge %u.%u.%u.%u:%u -> 0.0.0.0:%u (no IP_BOUND_IF; MADEIRA_UDP_BIND_IF=1 pins the interface)\\n",
                         b[0], b[1], b[2], b[3], ntohs( addr->sin_port ), ntohs( addr->sin_port ) );
            return 1;
        }
    }
#endif

    if (getifaddrs( &ifaddrs ) < 0) return 0;
""")

open(path, "w").write(src)
print("patched " + path)
