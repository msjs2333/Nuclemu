"""Legacy shared-gate protocol fixtures using the public course models."""

from dataclasses import replace
from nuclemu.catalog import discover


def legacy_course(name):
    base = discover()[name]
    device = base.devices[0]
    output = device.input

    def model(settings, start, end, rng):
        return {device.id: base.model(settings, start, end, rng)[output]}

    return replace(base, id=f"legacy_{name}", title=f"Legacy protocol {name}",
                   devices=(replace(device, input=None),), model=model,
                   outputs=(), components=(), connections=())
