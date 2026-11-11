"""Command-line discovery and reproducible, timed laboratory acquisition."""

from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path
import sys

from .catalog import discover
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
    for name in ("gui", "list", "validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--path", action="append", default=[], dest="paths",
                             metavar="DIRECTORY", help="additional trusted experiment directory")
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
            command.add_argument("--device", metavar="KIND:ID", help="select one device by id, unique kind, or kind:id")
            command.add_argument("--roi", metavar="FIRST:LAST", help="inclusive spectrum channels")
            command.add_argument("--calibration", metavar="FILE", help="load a two-point energy calibration")
            command.add_argument("--background", type=int, metavar="SEGMENT",
                                 help="1-based background segment for counter net rates")
            command.add_argument("--output", action="append", default=[], metavar="FILE",
                                 help="export the measured product to .csv or .json (repeatable)")
    return root


def _describe(experiment):
    print(f"{experiment.id}: {experiment.title}")
    print(f"  {experiment.description}")
    for p in experiment.parameters:
        print(f"  parameter {p.key}: default={p.default:g}; range=[{p.minimum:g}, {p.maximum:g}]"
              f" {p.unit}; {'integer' if p.integer else 'number'}; {p.label}")
    for d in experiment.devices:
        print(f"  device {d.kind}:{d.id}: {d.channels} channel(s); {d.label}")
        if d.calibration_parameters:
            print(f"    calibration parameters: {', '.join(d.calibration_parameters)}")


def _run(args, experiment):
    if args.calibration:
        source = Path(args.calibration).resolve()
        for output in args.output:
            target = Path(output).resolve()
            if target == source or (target.exists() and target.samefile(source)):
                raise ValueError("Output must not overwrite the input calibration file")
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
    steps = [_step(step) for step in args.step] if args.step else [_step(str(args.duration))]
    if args.background is not None and not 1 <= args.background <= len(steps):
        raise ValueError("Background segment is outside the acquisition plan")
    session = Session(experiment, seed=args.seed)
    for setting in args.set:
        session.set(*_assignment(setting))
    view = MeasurementView(session)
    for duration, settings in steps:
        for key, value in settings:
            session.set(key, value)
        session.start(duration)
        session.advance(duration)
    product = view.product()
    print(f"{experiment.id}; seed={args.seed}; {len(product['segments'])} segment(s)")
    for index, segment in enumerate(product["segments"], 1):
        exposure = segment["end_s"] - segment["start_s"]
        settings = ", ".join(f"{key}={value:g}" for key, value in segment["settings"].items())
        print(f"segment {index}: {segment['start_s']:g}..{segment['end_s']:g} s; exposure={exposure:g} s; {settings}")
        for d in devices:
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


def main(argv=None):
    """Entry point shared by ``python -m nuclemu`` and the console script."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    command_parser = parser()
    args = command_parser.parse_args(argv)
    paths = args.root_paths + args.paths
    try:
        if args.command == "gui":
            from .gui import launch
            launch(paths=paths)
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
        command_parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
