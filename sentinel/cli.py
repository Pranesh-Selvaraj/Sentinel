"""Sentinel CLI.

Commands orchestrate application services (:mod:`sentinel.app`) and hand the
results to :mod:`sentinel.display` for rendering. No business logic here.
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from sentinel import __version__
from sentinel.app import SentinelApp
from sentinel.errors import AbortError, SentinelError, UsageError
from sentinel.monitors import get_monitor
from sentinel.term import Output, confirm, select
from sentinel import display


def create_app(config_dir=None) -> SentinelApp:
    return SentinelApp(config_dir=config_dir)


def _add_parser(subparsers, name: str, help_text: str, **kwargs):
    parser = subparsers.add_parser(name, help=help_text, **kwargs)
    parser.set_defaults(command=name)
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", metavar="DIR", help="override the config directory")

    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Sentinel — a universal source & software change monitor.",
        epilog="Add it once. Sentinel watches it. Know when it changes.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"sentinel {__version__}")
    parser.add_argument("--config-dir", metavar="DIR", help="override the config directory")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def _add_parser(name: str, help_text: str, **kwargs):
        return sub.add_parser(name, help=help_text, parents=[common], allow_abbrev=False, **kwargs)
    # -- add --------------------------------------------------------------
    p_add = _add_parser("add", "Add a source to monitor (interactive)")
    add_sub = p_add.add_subparsers(dest="add_kind", metavar="TYPE")
    p_add.add_argument("--name", help="display name (defaults to repo/host)")
    p_add.add_argument("--skip-verify", action="store_true", help="skip GitHub existence check")

    p_gh = add_sub.add_parser("github", help="monitor a GitHub repository", parents=[common], allow_abbrev=False)
    p_gh.add_argument("repo", help="owner/name, e.g. microsoft/vscode")
    p_gh.add_argument("--monitor", choices=("release", "tags", "commits"), default="release",
                      help="what to watch (default: release)")
    p_gh.add_argument("--name", help="display name (default: repo)")
    p_gh.add_argument("--skip-verify", action="store_true")
    p_gh.add_argument("--install-path", metavar="DIR",
                      help="download latest release artifacts here — enables 'sentinel upgrade'")
    p_gh.add_argument("--asset", action="append", metavar="PATTERN",
                      help="asset name pattern to download (fnmatch, repeatable; default: largest asset)")

    p_http = add_sub.add_parser("http", help="monitor a website", parents=[common], allow_abbrev=False)
    p_http.add_argument("url", help="https://example.com")
    p_http.add_argument("--name", help="display name (default: hostname)")

    p_api = add_sub.add_parser("api", help="monitor an API endpoint", parents=[common], allow_abbrev=False)
    p_api.add_argument("url", help="https://api.example.com/version")
    p_api.add_argument("--jpath", help="JSON path to extract, e.g. $.version")
    p_api.add_argument("--name", help="display name (default: hostname)")
    p_api.add_argument("--header", action="append", metavar="K=V",
                       help="extra request header (repeatable; values may use ${ENV_VAR})")

    # -- other commands ---------------------------------------------------
    p_remove = _add_parser("remove", "Remove a source")
    p_remove.add_argument("ref", help="source id, name, or unique name prefix")
    p_remove.add_argument("--yes", action="store_true", help="skip confirmation")

    p_list = _add_parser("list", "List all sources")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")

    p_check = _add_parser("check", "Check all sources and report changes")
    p_check.add_argument("refs", nargs="*", help="check only these sources (id/name/prefix)")
    p_check.add_argument("--json", action="store_true", help="machine-readable output")
    p_check.add_argument("--exit-zero", action="store_true",
                         help="always exit 0 (default: 1 when changes, 2 when failures)")

    p_status = _add_parser("status", "Overview: sources, values, health")
    p_status.add_argument("--json", action="store_true", help="machine-readable output")

    p_show = _add_parser("show", "Show details of one source")
    p_show.add_argument("ref", help="source id, name, or unique name prefix")
    p_show.add_argument("--json", action="store_true", help="machine-readable output")

    p_history = _add_parser("history", "Show a source's observation history")
    p_history.add_argument("ref", nargs="?", help="source id, name, or unique name prefix")
    p_history.add_argument("--limit", type=int, default=10, help="max observations (default: 10)")
    p_history.add_argument("--json", action="store_true", help="machine-readable output")

    p_watch = _add_parser("watch", "Check repeatedly and print changes as they happen")
    p_watch.add_argument("--interval", metavar="DURATION",
                         help="e.g. 10m, 1h, 30s (default: config check_interval)")

    p_update = _add_parser("update", "Check for updates to Sentinel itself")

    p_upgrade = _add_parser("upgrade", "Plan and apply updates for monitored software")
    p_upgrade.add_argument("refs", nargs="*", help="only these sources (id/name/prefix)")
    p_upgrade.add_argument("--dry-run", action="store_true",
                           help="show what would happen without changing anything")
    p_upgrade.add_argument("--yes", action="store_true", help="apply without confirmation")
    p_upgrade.add_argument("--allow-unverified", action="store_true",
                           help="download artifacts even when no checksum is available")
    p_upgrade.add_argument("--json", action="store_true", help="machine-readable output")

    p_config = _add_parser("config", "Show configuration and paths")
    p_config.add_argument("--path", action="store_true", help="print only the config directory path")

    return parser


def _interactive_add(app: SentinelApp, out: Output) -> int:
    choices = [
        ("GitHub repository", "github", None),
        ("Website", "http", None),
        ("API endpoint", "api", None),
        ("Software/release (GitHub releases)", "github", "release"),
    ]
    labels = [c[0] for c in choices]
    picked = select("What do you want to monitor?", labels, out)
    kind, default_monitor = next(c[1:] for c in choices if c[0] == picked)

    monitor = get_monitor(kind)
    if kind == "github":
        config = monitor.prompt(default_monitor=default_monitor)
    else:
        config = monitor.prompt()
    from sentinel.term import input_text

    name = input_text("Name", default=monitor.default_name(config))
    if not name:
        name = monitor.default_name(config)
    source, warnings = app.add(kind, config, name=name, verify=not getattr(monitor, "skip_verify", False))
    display.display_added(out, source, warnings)
    return 0


def run_command(args, app: SentinelApp, out: Output) -> int:
    if args.command == "add":
        if args.add_kind is None:
            return _interactive_add(app, out)
        config = {}
        kind = args.add_kind
        if kind == "github":
            config = {"repo": args.repo, "monitor": args.monitor}
            if args.install_path:
                config["install_path"] = args.install_path
            if args.asset:
                config["assets"] = list(args.asset)
        elif kind == "http":
            config = {"url": args.url}
        elif kind == "api":
            config = {"url": args.url}
            if args.jpath:
                config["jpath"] = args.jpath
            if args.header:
                headers = {}
                for h in args.header:
                    if "=" not in h:
                        raise UsageError(f"invalid header {h!r} (expected K=V)")
                    key, value = h.split("=", 1)
                    headers[key.strip()] = value.strip()
                config["headers"] = headers
        source, warnings = app.add(kind, config, name=args.name, verify=not args.skip_verify)
        display.display_added(out, source, warnings)
        return 0

    if args.command == "remove":
        source = app.resolve(args.ref)
        if not args.yes:
            if not out.stream.isatty():
                raise UsageError(f"add --yes to remove {source.name!r} without a terminal")
            if not confirm(f"Remove '{source.name}'?"):
                out.print("Aborted.")
                return 0
        removed = app.remove(args.ref)
        display.display_removed(out, removed)
        return 0

    if args.command == "list":
        sources = app.list_sources()
        if args.json:
            out.print_json([s.to_dict() for s in sources])
        else:
            display.display_list(out, sources)
        return 0

    if args.command == "check":
        results = app.check(args.refs or None)
        if args.json:
            out.print_json([r.to_dict() for r in results])
        else:
            display.display_check(out, results)
        changes = sum(len(r.changes) for r in results)
        failed = sum(1 for r in results if not r.ok)
        if args.exit_zero or (changes == 0 and failed == 0):
            return 0
        return 1 if changes else 2

    if args.command == "status":
        data = app.status()
        if args.json:
            out.print_json(data)
        else:
            display.display_status(out, data)
        return 0

    if args.command == "show":
        data = app.show(args.ref)
        if args.json:
            out.print_json({"source": data["source"].to_dict(),
                            "snapshot": None if not data["snapshot"] else {
                                "observed_at": data["snapshot"].observed_at,
                                "value": data["snapshot"].value,
                                "state": data["snapshot"].state,
                            },
                            "changes": data["changes"]})
        else:
            display.display_show(out, data)
        return 0

    if args.command == "history":
        if args.ref is None:
            sources = app.list_sources()
            if not sources:
                raise UsageError("no sources configured — run 'sentinel add' first")
            out.print("Pick a source:")
            picked = select("Source", [s.name for s in sources], out)
            args.ref = picked
        data = app.history(args.ref, limit=args.limit)
        if args.json:
            out.print_json({
                "name": data["source"].name,
                "kind": data["source"].kind,
                "snapshots": data["snapshots"],
            })
        else:
            display.display_history(out, data)
        return 0

    if args.command == "watch":
        interval = args.interval or app.settings.check_interval
        from sentinel.util import format_interval, parse_interval

        seconds = parse_interval(interval)
        out.header(
            f"Sentinel watching {len(app.list_sources())} sources... (interval: {format_interval(seconds)})"
        )
        out.print()
        state = {"n": 0}

        def tick() -> None:
            state["n"] += 1
            results = app.check()
            display.display_watch_tick(out, results, state["n"])
            out.print()

        try:
            app.watch(interval, tick)
        except KeyboardInterrupt:
            out.print("\nStopped.")
        return 0

    if args.command == "update":
        display.display_update(out, app.self_update())
        return 0

    if args.command == "upgrade":
        report = app.upgrade(args.refs or None)
        if args.dry_run:
            if args.json:
                out.print_json(report.to_dict())
            else:
                display.display_upgrade(out, report, dry_run=True)
            return 0
        if not report.plans:
            if args.json:
                out.print_json(report.to_dict())
            else:
                display.display_upgrade(out, report, dry_run=False)
            return 0
        if not args.yes:
            if not out.stream.isatty():
                raise UsageError("add --yes to apply updates without a terminal")
            n = len(report.plans)
            if not confirm(f"Proceed with {n} update{'s' if n != 1 else ''}?"):
                out.print("Aborted.")
                return 0
        results = [app.apply_update(p, allow_unverified=args.allow_unverified) for p in report.plans]
        if args.json:
            out.print_json({"plans": [p.to_dict() for p in report.plans], "results": [r.to_dict() for r in results]})
        else:
            display.display_upgrade_results(out, results)
        return 0 if all(r.ok for r in results) else 1

    if args.command == "config":
        display.display_config(out, app.settings, path_only=args.path)
        return 0

    raise UsageError(f"unknown command {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 0 (help) or 2 (usage error)
        return int(exc.code or 0)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    out = Output()
    try:
        with contextlib.closing(create_app(args.config_dir)) as app:
            return run_command(args, app, out)
    except AbortError:
        out.print("Aborted.")
        return 130
    except SentinelError as exc:
        out.print(out.err(f"error: {exc}"))
        return 1
    except KeyboardInterrupt:
        out.print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
