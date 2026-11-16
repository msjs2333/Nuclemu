# Nuclemu

*A Virtual Nuclear Physics Lab*

[简体中文](README.zh-CN.md)

Nuclemu is a local nuclear physics simulator for undergraduate laboratories. Students operate sources, aluminium foils, detectors and instruments in a browser, save their readings, and use the recorded exposures and counts to analyse their own measurements. The workbench and experiment models run locally.

## Experiments you can use

| Experiment | What students measure | Student guide |
|---|---|---|
| Alpha energy loss in aluminium | Acquire a 1,024-channel spectrum, select a peak ROI, establish a two-point energy calibration, and follow the peak shift as foil thickness changes. | [Alpha energy loss](docs/student/alpha.md) |
| Beta absorption | Measure background and transmitted counts with separate A/B windows for virtual repeated observations. Export integer counts and actual exposures, then calculate net rates and uncertainties locally. | [Beta absorption](docs/student/beta.md) |

These are the two built-in courses. The [experiment catalogue](docs/design/experiments.md) and [delivery plan](docs/design/plan.md) describe ten further experiments.

The workbench interface and most experiment guides are currently in Chinese. This page and the installation guide are also available in English.

## Try the 0.0.1 prerelease

There is no formal public release yet. For prerelease testing, use the GitHub Actions builds below. These artifacts come from the final commit of the merged [PR #16](https://github.com/msjs2333/Nuclemu/pull/16).

Sign in to GitHub, open the matching build, and download the named ZIP from its **Artifacts** section. Extract the ZIP to find the installer or application image and its checksums. Artifacts have a retention period. See [GitHub's download instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).

| Your system | Build and artifact | Package to use |
|---|---|---|
| Windows x64 | [Windows build](https://github.com/msjs2333/Nuclemu/actions/runs/43709026349) · `Nuclemu-windows-x64` | `Nuclemu-0.0.1-windows-x64-setup.exe` |
| macOS · Intel | [macOS build](https://github.com/msjs2333/Nuclemu/actions/runs/43709026362) · `Nuclemu-macos-x86_64` | `Nuclemu-0.0.1-macos-x86_64.dmg` |
| macOS · Apple Silicon | [macOS build](https://github.com/msjs2333/Nuclemu/actions/runs/43709026362) · `Nuclemu-macos-arm64` | `Nuclemu-0.0.1-macos-arm64.dmg` |
| Linux · Debian 12 amd64 | [Linux build](https://github.com/msjs2333/Nuclemu/actions/runs/43709026386) · `Nuclemu-linux-amd64` | `nuclemu_0.0.1-1_amd64.deb` or `nuclemu-0.0.1-1-linux-amd64.tar.gz` |

The packages include Python and the workbench resources. Target machines need a suitable browser, and Linux also needs the listed system libraries. Windows packages have no publisher signature. macOS packages use ad-hoc signing without notarization. Read [installation and startup](docs/guides/installation.md) for installation steps, tested systems, remaining platform checks, upgrades and removal.

### First start

1. Install the package for your system. Open **Nuclemu** from the Start menu, Applications or the Linux application menu. For the Linux portable archive, run `./nuclemu-desktop` in the extracted application directory.
2. When the launcher shows **已就绪** (ready), choose **在浏览器中打开** (open in the default browser). Automatic browser opening is off by default. Keep the launcher open while working.
3. Choose alpha or beta from the catalogue. In the apparatus view, select the source and foil, switch on the detector output, then open the instrument and start measuring. Open **实验资料** (experiment materials) for the procedure and blank tables.
4. Use **保存** (save) on the instrument to keep readings in the current experiment. In **实验记录** (experiment records), download the selected readings or the whole `.nuclemu` file to take your work away.

See the [workbench guide](docs/student/gui.md) for acquisition, calibration, closing safely and reopening saved data.

### Run from source

From a source checkout, use Python 3.11 or later with Tk support for the desktop launcher:

```sh
python -m nuclemu serve --gui
```

For a terminal-only service, use `python -m nuclemu serve --no-gui` and open the printed local URL. The existing `python -m nuclemu gui` command starts a terminal-managed service and opens a browser. Stop terminal services with Ctrl+C after downloading your work. Interrupting the service does not save it for you.

## Command-line measurements

The CLI and workbench share the simulation clock, instrument models and measured counts. For example, list the courses, then measure 10 seconds of background and 20 seconds with the beta source behind four foils. The final option calculates the net rate using the first measurement as background.

```sh
python -m nuclemu list
python -m nuclemu run beta --device counter --enable-output beta_detector --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

The [CLI guide](docs/guides/cli.md) covers scripted measurements, trusted course directories, calibration and file import/export.

## Add a course

Course authors can add trusted Python modules through `--path`, reusing the existing apparatus and instrument interfaces. Start with the [course interfaces](docs/design/architecture.md) and [runnable course examples](examples/courses). For example, validate the example courses and open them in the workbench:

```sh
python -m nuclemu validate --path examples/courses
python -m nuclemu serve --gui --path examples/courses
```

Course modules execute Python code. Load only directories you trust. The [technical reference](docs/technical/README.md) describes the physics models, units, acquisition semantics and validation examples.

## Documentation

[Documentation index](docs/README.md)

| Reader or task | Entry points |
|---|---|
| Students | [Student handbook](docs/student/README.md) · [Alpha](docs/student/alpha.md) · [Beta](docs/student/beta.md) · [Workbench operations](docs/student/gui.md) |
| Teachers | [Teacher handbook](docs/teacher/README.md) · [Alpha](docs/teacher/alpha.md) · [Beta](docs/teacher/beta.md) |
| Course authors and maintainers | [Technical reference](docs/technical/README.md) · [Architecture and interfaces](docs/design/architecture.md) · [CLI](docs/guides/cli.md) |
| Scope and future experiments | [Delivery plan](docs/design/plan.md) · [Experiment catalogue](docs/design/experiments.md) |
| Artwork contributors | [Contribution guide](docs/art/art-contributing.md) · [Asset notes](docs/art/art-assets.md) (English) |

Nuclemu is licensed under the [GNU General Public License, version 3](LICENSE).
