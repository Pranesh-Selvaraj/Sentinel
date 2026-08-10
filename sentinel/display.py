"""Rendering of command results — human terminal output and JSON.

The CLI calls the app, gets plain data, and hands it to these functions.
No business logic lives here, only presentation.
"""

from __future__ import annotations

from sentinel.diffing import render_change
from sentinel.models import CheckResult, Source
from sentinel.monitors import get_monitor
from sentinel.term import Output, type_label
from sentinel.util import human_size, local_time, mask_secrets, safe_component
from pathlib import Path


def display_added(out: Output, source: Source, warnings: list[str]) -> None:
    out.print(out.ok(f"{out.ok_sym} Added {source.name}"))
    monitor = source.config.get("monitor")
    if monitor:
        out.print(f"Monitoring: {monitor}")
    else:
        kind_config = source.config.get("jpath")
        out.print(f"Monitoring: {kind_config or 'status'}")
    for warning in warnings:
        out.print(out.dim(f"note: {warning}"))


def display_removed(out: Output, source: Source) -> None:
    out.print(out.ok(f"{out.ok_sym} Removed {source.name}"))


def display_list(out: Output, sources: list[Source]) -> None:
    if not sources:
        out.print("No sources yet. Add your first one:")
        out.print(out.info("  sentinel add"))
        return
    out.header("Sentinel Sources")
    out.print()
    rows = []
    for s in sources:
        monitor = s.config.get("monitor")
        if not monitor:
            monitor = s.config.get("jpath") or "status"
        rows.append([s.name, type_label(s.kind), monitor])
    out.table(["NAME", "TYPE", "MONITOR"], rows)
    out.print()
    out.print(f"{len(sources)} source{'s' if len(sources) != 1 else ''}")


def display_check(out: Output, results: list[CheckResult]) -> None:
    out.header("Sentinel")
    out.print()
    out.print(f"Checking {len(results)} sources...")
    out.print()

    total_changes = 0
    failed = 0
    for result in results:
        monitor = get_monitor(result.source.kind)()
        if not result.ok:
            failed += 1
            out.print(out.err(f"{out.err_sym} {result.source.name}"))
            out.print(f"  {result.error}")
        elif result.changes:
            total_changes += len(result.changes)
            out.print(out.warn(f"{out.warn_sym} {result.source.name}"))
            for line in render_change(result.changes[0]):
                out.print(line)
            for change in result.changes[1:]:
                out.print(out.dim("  +"))
                for line in render_change(change):
                    out.print(line)
        else:
            value = monitor.format_value(result.source, result.observation.value)
            out.print(out.ok(f"{out.ok_sym} {result.source.name}"))
            hint = ""
            if value == "—":
                mon = result.source.config.get("monitor")
                hint = f" no {'releases' if mon == 'release' else mon or 'value'} yet"
            if result.first:
                out.print(f"  {value}{hint} — first check (baseline recorded)")
            else:
                out.print(f"  {value}{hint} — no change")
        out.print()

    if total_changes:
        out.print(out.bold(f"{total_changes} change{'s' if total_changes != 1 else ''} detected."))
    else:
        out.print("No changes detected.")
    if failed:
        out.print(out.err(f"{failed} source{'s' if failed != 1 else ''} failed."))


def display_status(out: Output, data: dict) -> None:
    sources = data["sources"]
    out.header("Sentinel Status")
    out.print()
    if not sources:
        out.print("No sources configured yet. Add one:")
        out.print(out.info("  sentinel add"))
        return
    rows = []
    for row in sources:
        status = "—"
        if row["last_status"] == "ok":
            status = out.ok(out.ok_sym)
        elif row["last_status"] == "failed":
            status = out.err(out.err_sym)
        rows.append(
            [
                row["name"],
                type_label(row["kind"]),
                row["value"],
                local_time(row["last_checked_at"]),
                status,
            ]
        )
    out.table(["NAME", "TYPE", "VALUE", "LAST CHECK", "STATUS"], rows)

    updates = data["updates"]
    skipped = data.get("skipped", [])
    out.print()
    if updates:
        out.print(out.warn(f"{len(updates)} update{'s' if len(updates) != 1 else ''} available."))
        for plan in updates:
            installed = plan["installed_version"] or "not downloaded"
            out.print(f"  {plan['tool']}: {installed} → {plan['latest_version']} ({plan['source_url']})")
    elif skipped:
        out.print(out.dim("Updates:"))
        for item in skipped:
            out.print(out.dim(f"  — {item['name']}: {item['reason']}"))
    else:
        out.print(out.dim("No updaters registered for these sources yet — see 'sentinel upgrade'."))


def display_show(out: Output, data: dict) -> None:
    source: Source = data["source"]
    out.header(f"{source.name} ({type_label(source.kind)})")
    out.print()
    config = mask_secrets(source.config)
    for key, value in sorted(config.items()):
        out.print(f"  {key:<12} {value}")
    out.print(f"  {'added':<12} {local_time(source.created_at, '%b %d %Y', include_year=True)}")
    out.print(f"  {'last check':<12} {local_time(source.last_checked_at)} ({source.last_status or 'never'})")
    if source.last_error:
        out.print(out.dim(f"  last error: {source.last_error}"))

    snapshot = data["snapshot"]
    out.print()
    if snapshot:
        out.print(f"  Current value: {snapshot.value or '—'}")
        out.print(f"  Observed:      {local_time(snapshot.observed_at)}")
        if snapshot.raw:
            preview = snapshot.raw[:500].replace("\n", " ")
            out.print(out.dim(f"  Raw preview:   {preview}"))
    else:
        out.print(out.dim("  No observations yet — run 'sentinel check'."))

    changes = data["changes"]
    out.print()
    if changes:
        out.print("  Recent changes:")
        for c in changes:
            out.print(f"    {local_time(c['detected_at'])}  [{c['kind']}] {c['previous']} → {c['current']} {c['description']}".rstrip())
    else:
        out.print(out.dim("  No changes recorded yet."))


def display_history(out: Output, data: dict) -> None:
    source: Source = data["source"]
    out.header(f"{source.name} History")
    out.print()
    snapshots = data["snapshots"]
    if not snapshots:
        out.print("No observations yet — run 'sentinel check'.")
        return
    monitor = get_monitor(source.kind)()
    for snap in snapshots:
        when = local_time(snap["observed_at"], "%b %d", include_year=True)
        value = monitor.format_value(source, snap["value"])
        out.print(f"{when:<12} {value}")
    out.print()
    out.print(out.dim(f"{len(snapshots)} observation{'s' if len(snapshots) != 1 else ''} (most recent first)"))


def display_watch_tick(out: Output, results: list[CheckResult], tick_number: int) -> None:
    from sentinel.util import clock_time

    changes = sum(len(r.changes) for r in results)
    failed = sum(1 for r in results if not r.ok)
    stamp = out.dim(f"[{clock_time()}]")
    if failed:
        out.print(f"{stamp} {out.err(f'{out.err_sym} {failed} source{"s" if failed != 1 else ""} failed')}")
    elif changes:
        out.print(f"{stamp} {out.warn(f'{out.warn_sym} {changes} change{"s" if changes != 1 else ""} detected')}")
    else:
        out.print(f"{stamp} {out.ok(f'{out.ok_sym} No changes')}")

    for result in results:
        if result.ok and not result.changes:
            continue
        out.print()
        if not result.ok:
            out.print(out.err(f"{result.source.name}"))
            out.print(f"  {result.error}")
            continue
        out.print(out.warn(f"{result.source.name}"))
        for change in result.changes:
            for line in render_change(change):
                out.print(line)


def display_upgrade(out: Output, report, dry_run: bool) -> int:
    """Render an :class:`UpgradeReport`; returns the number of pending plans."""
    out.print("Checking official sources...")
    out.print()
    plans = report.plans
    for plan in plans:
        out.print(out.bold(plan.tool))
        out.print(f"  Installed: {plan.installed_version or 'not downloaded'}")
        out.print(f"  Latest:    {plan.latest_version or 'unknown'}")
        out.print(f"  Source:    {plan.source_url or 'unknown'}")
        dest = Path(plan.install_path).expanduser() / safe_component(plan.latest_version or "")
        for asset in plan.assets:
            out.print(f"  Asset:     {asset.name} ({human_size(asset.size)}) → {dest}/")
        if plan.verified:
            out.print(out.ok(f"  Verify:    {plan.verify_note}"))
        else:
            out.print(out.warn(f"  Verify:    {plan.verify_note}"))
        out.print()

    for skipped in report.skipped:
        out.print(out.dim(f"— {skipped['name']} ({skipped['kind']}): {skipped['reason']}"))

    if plans:
        out.print()
        n = len(plans)
        out.print(out.bold(f"{n} update{'s' if n != 1 else ''} available."))
    else:
        out.print()
        out.print("Nothing to update.")
    if dry_run:
        out.print(out.dim("(--dry-run: nothing was downloaded or changed)"))
    return len(plans)


def display_upgrade_results(out: Output, results: list) -> None:
    applied = 0
    failed = 0
    for result in results:
        if result.ok:
            applied += 1
            out.print(out.ok(f"{out.ok_sym} {result.source.name}"))
            out.print(f"  {result.message}")
            for path in result.downloaded:
                out.print(out.dim(f"  {path}"))
            if not result.verified:
                out.print(out.dim("  (unverified — no checksum was available)"))
        else:
            failed += 1
            out.print(out.err(f"{out.err_sym} {result.source.name}"))
            out.print(f"  {result.message}")
        out.print()
    out.print(out.bold(f"{applied} update{'s' if applied != 1 else ''} applied, {failed} failed."))


def display_update(out: Output, info: dict) -> None:
    out.print(f"Sentinel {info['current']}")
    out.print("Checking for updates...")
    if not info["checked"]:
        out.print(out.dim(info["message"]))
        return
    if info["available"]:
        out.print(out.warn(f"{out.warn_sym} Update available: {info['latest']}"))
        out.print(f"  {info['install_hint']}")
        if not info.get("verified"):
            out.print(out.dim(info["verify_note"]))
    else:
        out.print(out.ok(f"{out.ok_sym} {info['message']}"))


def display_config(out: Output, settings, path_only: bool = False) -> None:
    if path_only:
        out.print(settings.config_dir)
        return
    out.header("Sentinel Configuration")
    out.print()
    out.print(f"  Config dir:   {settings.config_dir}")
    out.print(f"  Database:     {settings.db_path}")
    for key, value in sorted(settings.to_dict().items()):
        if key in ("config_dir", "db_path"):
            continue
        out.print(f"  {key:<14} {value}")
    config_file = settings.config_dir / "config.toml"
    if config_file.exists():
        out.print()
        out.print(out.dim(f"Loaded {config_file}"))
