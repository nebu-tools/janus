"""The `janus-workbench` command.

janus-workbench serve            the API and the client on http://127.0.0.1:8440
janus-workbench openapi          the API's OpenAPI document, for generating client types
"""

import argparse
import ipaddress
import json
import socket
import sys
from collections.abc import Callable
from typing import Any

DEFAULT_PORT = 8440

Resolve = Callable[..., list[tuple[Any, ...]]]


def addresses(host: str, port: int, resolve: Resolve = socket.getaddrinfo) -> list[str]:
    """Every address `host` stands for, a literal address or a name, in the resolver's order."""
    found = resolve(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%")[0] for info in found))


def is_loopback(address: str) -> bool:
    return ipaddress.ip_address(address).is_loopback


def host_header(host: str) -> str:
    """How a browser writes `host` in the Host header: an IPv6 address in brackets."""
    return f"[{host}]" if ":" in host else host


def main(argv: list[str] | None = None, *, resolve: Resolve = socket.getaddrinfo) -> int:
    parser = argparse.ArgumentParser(prog="janus-workbench", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the API and the client")
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="address or name to listen on (127.0.0.1); it must be this machine's own "
        "loopback address unless --listen-without-auth is given",
    )
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port ({DEFAULT_PORT})")
    serve.add_argument(
        "--listen-without-auth",
        action="store_true",
        help="allow an address other than this machine's own; anyone who can reach it "
        "can read and delete every document, because there is no sign-in",
    )
    commands.add_parser("openapi", help="print the OpenAPI document")
    args = parser.parse_args(argv)

    from janus_workbench.app import LOOPBACK_HOSTS, api, create_app
    from janus_workbench.settings import Settings

    if args.command == "openapi":
        described = api(Settings.from_env(), start=False)
        print(json.dumps(described.openapi(), indent=2, sort_keys=True))
        return 0

    # Resolved once: the check and the bind use the same address, so a name cannot change
    # between them.
    try:
        found = addresses(args.host, args.port, resolve)
    except OSError as error:
        print(f"janus-workbench: cannot resolve {args.host}: {error}", file=sys.stderr)
        return 2
    local = bool(found) and all(is_loopback(a) for a in found)
    if not local and not args.listen_without_auth:
        print(
            f"janus-workbench: {args.host} ({', '.join(found)}) is not only this machine's "
            "loopback address, and the workbench has no sign-in. Pass --listen-without-auth "
            "to serve there anyway.",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    bound = found[0]
    hosts = (*LOOPBACK_HOSTS, host_header(args.host), host_header(bound)) if local else None
    app = create_app(Settings.from_env(), hosts=hosts)
    uvicorn.run(app, host=bound, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
