"""The `janus-workbench` command.

janus-workbench serve            the API and the client on http://127.0.0.1:8440
janus-workbench openapi          the API's OpenAPI document, for generating client types
"""

import argparse
import ipaddress
import json
import sys

DEFAULT_PORT = 8440


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="janus-workbench", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the API and the client")
    serve.add_argument("--host", default="127.0.0.1", help="address to listen on (127.0.0.1)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port ({DEFAULT_PORT})")
    serve.add_argument(
        "--listen-without-auth",
        action="store_true",
        help="allow an address other than this machine's own; anyone who can reach it "
        "can read and delete every document, because there is no sign-in",
    )
    commands.add_parser("openapi", help="print the OpenAPI document")
    args = parser.parse_args(argv)

    from janus_workbench.app import create_app
    from janus_workbench.settings import Settings

    if args.command == "openapi":
        app = create_app(Settings.from_env(), start=False)
        print(json.dumps(app.openapi(), indent=2, sort_keys=True))
        return 0

    local = _is_loopback(args.host)
    if not local and not args.listen_without_auth:
        print(
            f"janus-workbench: {args.host} is reachable from other machines and the workbench "
            "has no sign-in. Pass --listen-without-auth to serve there anyway.",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    app = create_app(Settings.from_env(), any_host=not local)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
