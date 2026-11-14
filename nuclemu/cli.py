"""Command-line discovery and reproducible, timed laboratory acquisition."""

from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
import sys

from .catalog import describe, discover
from .core import Session
from .results import Calibration, MeasurementView, net_count_rate, roi_centroid, save_product


def _assignment(text):
    try:
        key, raw = text.split("=", 1)
        value = float(raw)
        if not key or not isfinite(value):
            raise ValueError
        return key, value
    except ValueError:
        raise ValueError(f"Expected KEY=NUMBER, got {text!r}") from None


def _step(text):
    fields = text.split(",")
    try:
        duration = float(fields[0])
        if not isfinite(duration) or duration <= 0:
            raise ValueError
    except ValueError:
        raise ValueError(f"Expected a positive exposure in seconds, got {fields[0]!r}") from None
    return duration, [_assignment(field) for field in fields[1:]]


def _device(experiment, selector):
    if selector is None:
        return None
    matches = [d for d in experiment.devices if selector == d.id]
    if not matches:
        matches = [d for d in experiment.devices if selector in (d.kind, f"{d.kind}:{d.id}")]
    if len(matches) != 1:
        raise ValueError(f"Device {selector!r} must identify one instrument; use KIND:ID")
    return matches[0]


def parser():
    root = argparse.ArgumentParser(prog="nuclemu", description="A Virtual Nuclear Physics Lab")
    root.add_argument("--path", action="append", default=[], dest="root_paths",
                      metavar="DIRECTORY", help="additional trusted experiment directory (repeatable)")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("gui", "serve", "list", "validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--path", action="append", default=[], dest="paths",
                             metavar="DIRECTORY", help="additional trusted experiment directory")
        if name == "serve":
            mode = command.add_mutually_exclusive_group(required=True)
            mode.add_argument("--gui", action="store_true", help="open the desktop service launcher")
            mode.add_argument("--no-gui", action="store_false", dest="gui",
                              help="serve in this terminal without opening a browser; Ctrl+C stops without saving")
        if name in ("list", "validate"):
            command.add_argument("experiment", nargs="?")
        if name == "run":
            command.add_argument("experiment")
            command.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                                 help="initial setting, in the unit shown by list")
            exposure = command.add_mutually_exclusive_group(required=True)
            exposure.add_argument("--duration", metavar="SECONDS", type=float)
            exposure.add_argument("--step", action="append", metavar="SECONDS[,KEY=VALUE,...]",
                                  help="timed gate; settings persist into later steps (repeatable)")
            command.add_argument("--seed", type=int, default=0)
            command.add_argument("--change", action="append", default=[], metavar="SECONDS,KEY=VALUE,...",
                                 help="change settings within one --duration round, without closing gates")
            command.add_argument("--window", action="append", default=[], metavar="DEVICE=SECONDS",
                                 help="instrument window length (repeatable)")
            command.add_argument("--device", metavar="KIND:ID", help="select one device by id, unique kind, or kind:id")
            command.add_argument("--enable-output", action="append", default=[], metavar="ID",
                                 help="enable a declared detector output before acquisition (repeatable)")
            command.add_argument("--roi", metavar="FIRST:LAST", help="inclusive spectrum channels")
            command.add_argument("--calibration", metavar="FILE", help="load a two-point energy calibration")
            command.add_argument("--background", type=int, metavar="STEP",
                                 help="1-based independent measurement step for counter net rates")
            command.add_argument("--output", action="append", default=[], metavar="FILE",
                                 help="export the measured product to .csv or .json (repeatable)")
            command.add_argument("--package", metavar="FILE", help="save completed steps as a portable .nuclemu experiment")
    files = commands.add_parser("files", help="inspect, exchange and convert portable experiment files")
    operations = files.add_subparsers(dest="operation", required=True)
    inspect = operations.add_parser("inspect")
    inspect.add_argument("source")
    export = operations.add_parser("export")
    export.add_argument("source")
    export.add_argument("--item", required=True)
    export.add_argument("--output", required=True)
    merge = operations.add_parser("import")
    merge.add_argument("target")
    merge.add_argument("source")
    merge.add_argument("--item", required=True)
    merge.add_argument("--output", required=True)
    rename = operations.add_parser("rename", help="rename a saved record by stable UUID")
    rename.add_argument("source")
    rename.add_argument("--item", required=True)
    rename.add_argument("--title", required=True)
    rename.add_argument("--output", required=True)
    batch = operations.add_parser("batch-export", help="export selected UUID:FORMAT records")
    batch.add_argument("source")
    batch.add_argument("--item", action="append", required=True, metavar="UUID:FORMAT")
    batch.add_argument("--output", required=True)
    convert = operations.add_parser("convert-archive")
    convert.add_argument("source", help="legacy workbench.sqlite3")
    convert.add_argument("--archive", required=True)
    convert.add_argument("--output", required=True)
    return root


def _describe(experiment):
    entry = describe(experiment)
    print(f"{experiment.id}: {experiment.title}")
    print(f"  {experiment.description}")
    if entry["question"] != experiment.description:
        print(f"  question: {entry['question']}")
    for index, paragraph in enumerate(entry["guide"], 1):
        print(f"  guide {index}: {paragraph}")
    for p in experiment.parameters:
        print(f"  parameter {p.key}: default={p.default:g}; range=[{p.minimum:g}, {p.maximum:g}]"
              f" {p.unit}; {'integer' if p.integer else 'number'}; {p.label}")
    for d in experiment.devices:
        print(f"  device {d.kind}:{d.id}: {d.channels} channel(s); {d.label}")
        if d.input is not None:
            print(f"    input: {d.input}")
        if d.calibration_parameters:
            print(f"    calibration parameters: {', '.join(d.calibration_parameters)}")
    for output in experiment.outputs:
        print(f"  output {output.id}: {output.label}; {output.channels} channel(s);"
              f" unit={output.unit}; time_unit={output.time_unit}")
        if output.response:
            print(f"    {output.response}")
    devices = {d.id: d for d in experiment.devices}
    for part in entry["components"]:
        print(f"  component {part['kind']}:{part['id']}: {part['label']}")
        if part["description"]:
            print(f"    {part['description']}")
        if part["parameters"]:
            print(f"    parameters: {', '.join(part['parameters'])}")
        if part["device"] is not None:
            device = devices[part["device"]]
            print(f"    device: {device.kind}:{device.id}")
    for link in entry["connections"]:
        print(f"  connection {link['kind']}: {link['source']} -> {link['target']}; {link['label']}")


def _run(args, experiment):
    if args.calibration:
        source = Path(args.calibration).resolve()
        for output in [*args.output, *([args.package] if args.package else [])]:
            target = Path(output).resolve()
            if target == source or (target.exists() and target.samefile(source)):
                raise ValueError("Output must not overwrite the input calibration file")
    if args.package:
        if not experiment.outputs:
            raise ValueError("Portable live capture requires explicit instrument snapshots")
        if any(_same_path(args.package, path) for path in args.output):
            raise ValueError("Package and measurement outputs must use different files")
    selected = _device(experiment, args.device)
    devices = [selected] if selected else list(experiment.devices)
    roi = None
    if args.roi is not None:
        try:
            first, last = map(int, args.roi.split(":"))
        except ValueError:
            raise ValueError("ROI must be FIRST:LAST, inclusive integer channels") from None
        if len(devices) != 1 or devices[0].kind != "spectrum":
            raise ValueError("ROI requires one selected spectrum device")
        if not 0 <= first <= last < devices[0].channels:
            raise ValueError("ROI channels must lie within the selected spectrum")
        roi = first, last
    calibration = Calibration.load(args.calibration) if args.calibration else None
    if calibration:
        bound = _device(experiment, calibration.device)
        calibration.check(experiment.id, bound.id, bound.channels, bound.calibration_parameters)
        if bound.kind != "spectrum" or (selected and selected.id != bound.id):
            raise ValueError("Calibration requires its bound spectrum device")
    if args.background is not None and not any(d.kind == "counter" for d in devices):
        raise ValueError("Net rate requires a counter device")
    if args.background is not None and experiment.outputs and len(devices) > 1:
        raise ValueError("Select one instrument with --device when using --background")
    steps = [_step(step) for step in args.step] if args.step else [_step(str(args.duration))]
    changes = [_step(change) for change in args.change]
    if changes and (args.step or args.background is not None):
        raise ValueError("--change requires one --duration round without --background")
    if any(not settings or time >= steps[0][0] for time, settings in changes):
        raise ValueError("Each change requires settings and a time strictly inside the duration")
    if len({time for time, _ in changes}) != len(changes):
        raise ValueError("Combine settings at the same change time into one --change")
    changes.sort(key=lambda change: change[0])
    if args.background is not None and not 1 <= args.background <= len(steps):
        raise ValueError("Background segment is outside the acquisition plan")
    session = Session(experiment, seed=args.seed)
    session.configure(dict(_assignment(setting) for setting in args.set))
    for output in args.enable_output:
        session.set_output(output, True)
    for setting in args.window:
        selector, seconds = _assignment(setting)
        instrument = _device(experiment, selector)
        if instrument not in devices:
            raise ValueError("Window requires an instrument in the acquisition plan")
        session.configure_acquisition(instrument.id, window_s=seconds)
    view = MeasurementView(session)
    saved_steps = []
    for index, (duration, settings) in enumerate(steps):
        if index and experiment.outputs:
            session.clear(device=selected.id if selected else None)
        session.configure(dict(settings))
        if experiment.outputs:
            session.start(duration, device=selected.id if selected else None)
        else:
            session.start(duration)
        elapsed = 0
        for time, values in changes:
            session.advance(time-elapsed)
            session.configure(dict(values))
            elapsed = time
        session.advance(duration-elapsed)
        if args.package:
            saved_steps.append({instrument.id: session.snapshot(instrument.id).id for instrument in devices})
    product = view.product()
    if selected:
        product = dict(product, segments=[s for s in product["segments"] if selected.id in s["readings"]])
    print(f"{experiment.id}; seed={args.seed}; {len(product['segments'])} segment(s)")
    for output, enabled in session.output_enabled.items():
        print(f"detector output {output}: {'on' if enabled else 'off (zero input)'}")
    for index, segment in enumerate(product["segments"], 1):
        exposure = segment["end_s"] - segment["start_s"]
        settings = ", ".join(f"{key}={value:g}" for key, value in segment["settings"].items())
        print(f"segment {index}: {segment['start_s']:g}..{segment['end_s']:g} s; exposure={exposure:g} s; {settings}")
        for d in devices:
            if d.id not in segment["readings"]:
                continue
            counts = segment["readings"][d.id]
            print(f"  {d.kind}:{d.id}: counts={sum(counts)}; rate={sum(counts) / exposure:.6g} 1/s")
            if roi:
                centroid = roi_centroid(counts, *roi)
                detail = "None" if centroid is None else f"{centroid:.6g}"
                print(f"    ROI {roi[0]}:{roi[1]}: counts={sum(counts[roi[0]:roi[1]+1])}; centroid={detail} channel")
                if calibration and not calibration.applies_to(segment["settings"]):
                    print("    calibration does not apply to this segment; channel axis retained")
                elif centroid is not None and calibration:
                    print(f"    energy={calibration.energy(centroid):.6g} MeV")
            if args.background is not None and d.kind == "counter" and index != args.background:
                background = product["segments"][args.background - 1]
                net, uncertainty = net_count_rate(sum(counts), exposure,
                    sum(background["readings"][d.id]), background["end_s"] - background["start_s"])
                print(f"    net={net:.6g} +/- {uncertainty:.6g} 1/s (background segment {args.background})")
    for path in args.output:
        save_product(path, product, device=selected.id if selected else None, calibration=calibration)
        print(f"saved {path}")
    if args.package:
        from .exchange import bind_calibration, cache_calibration, capture_session, link_measurements, save_package
        document = capture_session(session, device=selected.id if selected else None)
        if selected is None:
            identities = {item['document']['snapshot']['id']: item['id'] for item in document['items']
                          if item['kind'] == 'measurement'}
            for step in saved_steps:
                for component in experiment.components:
                    if len(component.devices) > 1 and all(d in step for d in component.devices):
                        link_measurements(document, [identities[step[d]] for d in component.devices],
                                          members=component.devices)
        if args.background is not None:
            counter = next(d for d in devices if d.kind == "counter")
            item_ids = {(item["document"]["snapshot"]["device"], item["document"]["snapshot"]["id"]): item["id"]
                        for item in document["items"] if item["kind"] == "measurement"}
            background_step = args.background - 1
            sample_step = next((i for i in reversed(range(len(steps))) if i != background_step), background_step)
            document["analysis"][counter.id] = dict(
                background=item_ids[counter.id, saved_steps[background_step][counter.id]],
                selected=item_ids[counter.id, saved_steps[sample_step][counter.id]], reference=None,
                roi=[0, counter.channels - 1], energy_axis=False, rate_axis=False)
        if calibration:
            identity = cache_calibration(document, calibration)
            for item in document["items"]:
                if (item["kind"] == "measurement" and calibration.device in item["document"]["devices"]
                        and all(calibration.applies_to(s["settings"]) for s in item["document"]["segments"])):
                    bind_calibration(document, item["id"], identity)
        save_package(args.package, document)
        print(f"saved {args.package}")


def _same_path(left, right):
    left, right = Path(left).resolve(), Path(right).resolve()
    return left == right or (left.exists() and right.exists() and left.samefile(right))


def _files(args):
    from .exchange import (batch_download, convert_archive, import_item, list_items, list_records, list_legacy_archives, load_item,
                           load_package, rename_record, save_item, save_package, _save_bytes)
    if args.operation == "convert-archive":
        if _same_path(args.source, args.output):
            raise ValueError("Conversion must not overwrite its input archive")
        save_package(args.output, convert_archive(args.source, args.archive))
        print(f"saved {args.output}")
        return
    raw = Path(args.source).read_bytes()
    try:
        document = load_package(raw) if raw.startswith((b"SQLite format 3\0", b"PK\x03\x04")) else load_item(raw)
    except ValueError:
        if args.operation != "inspect" or not raw.startswith(b"SQLite format 3\0"):
            raise
        print(json.dumps(dict(format="nuclemu.legacy-store/0", archives=list_legacy_archives(args.source)),
                         ensure_ascii=False, indent=2))
        return
    if args.operation == "inspect":
        print(json.dumps(dict(format=document["format"], experiment=document["definition"]["id"],
                              items=list_items(document), records=list_records(document), rounds=document.get("rounds", [])),
                         ensure_ascii=False, indent=2))
    elif args.operation == "rename":
        if document["format"] != "nuclemu.experiment/1":
            raise ValueError("Rename requires a portable experiment package")
        rename_record(document, args.item, args.title)
        save_package(args.output, document)
        print(f"saved {args.output}")
    elif args.operation == "batch-export":
        if _same_path(args.source, args.output):
            raise ValueError("Export must not overwrite its input package")
        choices = []
        for selector in args.item:
            identity, separator, format = selector.rpartition(":")
            if not separator or not identity or format not in ("csv", "json"):
                raise ValueError("Batch selection must be UUID:csv or UUID:json")
            choices.append(dict(id=identity, format=format))
        _, _, data = batch_download(document, choices)
        _save_bytes(args.output, data)
        print(f"saved {args.output}")
    elif args.operation == "export":
        if _same_path(args.source, args.output):
            raise ValueError("Item export must not overwrite its input package")
        save_item(args.output, document, args.item)
        print(f"saved {args.output}")
    else:
        if _same_path(args.source, args.output) and not _same_path(args.target, args.source):
            raise ValueError("Import must not overwrite its source file")
        target = load_package(args.target)
        identity = import_item(target, document, args.item)
        save_package(args.output, target)
        print(f"imported {identity}; saved {args.output}")


def main(argv=None):
    """Entry point shared by ``python -m nuclemu`` and the console script."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    command_parser = parser()
    args = command_parser.parse_args(argv)
    paths = args.root_paths + getattr(args, "paths", [])
    try:
        if args.command == "files":
            _files(args)
            return 0
        if args.command == "gui":
            from .web import launch
            launch(paths=paths)
            return 0
        if args.command == "serve":
            try:
                if args.gui:
                    from .desktop import launch
                    launch(paths=paths)
                else:
                    from .web import launch
                    launch(paths=paths, open_browser=False)
            except KeyboardInterrupt:
                pass
            return 0
        definitions = discover(paths)
        name = args.experiment
        if name is not None and name not in definitions:
            raise ValueError(f"Unknown experiment {name!r}; use list to discover experiments")
        if args.command == "run":
            _run(args, definitions[name])
        else:
            for experiment in ([definitions[name]] if name else definitions.values()):
                if args.command == "list":
                    _describe(experiment)
                else:
                    print(f"valid {experiment.id}: {len(experiment.parameters)} parameter(s), {len(experiment.devices)} device(s)")
        return 0
    except (ValueError, OSError, ImportError) as error:
        message = str(error)
        if args.command == "serve" and args.gui:
            message += "; for terminal-only service use nuclemu serve --no-gui"
        command_parser.error(message)


if __name__ == "__main__":
    raise SystemExit(main())
