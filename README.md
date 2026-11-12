# Nuclemu

*A Virtual Nuclear Physics Lab*

[Simplified Chinese](README.zh-CN.md)

Nuclemu is a local nuclear physics simulator for undergraduate laboratories. The development version includes alpha energy loss and beta absorption. Students can vary an aluminium foil's thickness and measure either the shift in an alpha spectrum or the change in the beta counter's net rate.

## Getting started

From the repository directory, use Python 3.11 or later to open the local workbench in your browser:

```sh
python -m nuclemu gui
```

Select an experiment from the catalogue. In the apparatus view, choose the source and foil, switch on the detector output, then open the instrument. Save the readings you want to keep from the instrument panel. The interface and models run locally.

For a scripted measurement, list the experiments, then acquire 10 seconds of background counts and 20 seconds with the source present behind four foils. The last option uses the first measurement to calculate the background-subtracted rate.

```sh
python -m nuclemu list
python -m nuclemu run beta --device counter --enable-output beta_detector --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

The workbench and CLI share the same simulation clock, instrument models and measured counts. Experiment authors can add trusted Python modules to the catalogue. The delivery plan describes ten further experiments.

## Documentation

The guides and design documents are in Chinese.

| Document | Contents |
|---|---|
| [Workbench](docs/gui.md) · [Command line](docs/cli.md) | Acquisition, calibration, background subtraction and export |
| Student handbook · [Alpha energy loss](docs/alpha.md) · [Beta absorption](docs/beta.md) | Experimental procedure, observed quantities and interpretation |
| Teacher handbook · [Alpha energy loss](docs/teacher/alpha.md) · [Beta absorption](docs/teacher/beta.md) | Worked measurements, calibration and counting uncertainty |
| Technical reference · [Alpha spectroscopy](docs/technical/alpha.md) · [Beta counting](docs/technical/beta.md) | Instrument settings, model limits and reproducible measurements |
| [Delivery plan](docs/plan.md) | Scope, delivery sequence and acceptance criteria |
| [Architecture and interfaces](docs/architecture.md) | Experiment modules, simulation time, instrument panels and measurement data |
| [Experiment catalogue](docs/experiments.md) | Physics questions, measurement designs and requirements for all 12 experiments |

Nuclemu is licensed under the [GNU General Public License, version 3](LICENSE).
