"""CLI entry point: python -m lilite <command>"""

import argparse
import logging
import sys


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        prog="lilite",
        description="LI Lite — a lighter LinkedIn experience",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("auth", help="Authenticate with LinkedIn (opens browser)")
    sub.add_parser("discover", help="Discover UI components and API calls")

    cfg_parser = sub.add_parser("configure", help="Interactive enable/disable menu")
    cfg_parser.add_argument("--discovery", help="Path to discovery JSON (default: latest)")

    build_parser = sub.add_parser("build", help="Build Chrome extension")
    build_parser.add_argument("--config", help="Path to configuration JSON (default: latest)")

    sub.add_parser("run", help="Run all phases in sequence")

    args = parser.parse_args()

    if args.command == "auth":
        from .auth import authenticate
        authenticate()

    elif args.command == "discover":
        from .discovery import discover
        discover()

    elif args.command == "configure":
        from .configure import configure
        configure(discovery_path=args.discovery)

    elif args.command == "build":
        from .build import build
        build(config_path=args.config)

    elif args.command == "run":
        from .auth import authenticate, load_cookies
        from .discovery import discover
        from .configure import configure
        from .build import build

        # Auth: always re-authenticate to ensure fresh session
        authenticate()
        disc_path = discover()
        cfg_path = configure(discovery_path=disc_path)
        build(config_path=cfg_path)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
