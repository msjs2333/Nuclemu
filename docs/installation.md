# Install and start Nuclemu

[简体中文](installation.zh-CN.md)

Version 0.0.1 desktop packages are being prepared in [draft PR #16](https://github.com/msjs2333/Nuclemu/pull/16). Use the package and validation notes supplied together for your operating system and architecture. This page describes candidate builds; a formal release has not yet been published.

The desktop package includes the runtime, experiments and workbench resources. You need a desktop browser; Python and Node.js are not required on the target machine. Once installed, the workbench runs locally without an internet connection.

## Windows

The installer candidate is `Nuclemu-0.0.1-windows-x64-setup.exe`. It has no publisher signature. Run it and choose the installation scope: the current user by default, or all users with administrator permission. Open **Nuclemu** from the Start menu. Its CLI is `nuclemu.exe` in the installation directory.

To upgrade, save your experiment, close the launcher and terminal services, then run the new installer in the existing installation scope. To uninstall, use Nuclemu's entry in Windows' installed-apps settings. If prompted to close Nuclemu, finish saving and close it before retrying; the installer does not stop an active experiment for you.

The Windows x64 directory sample has been tested on Windows 11, including an offline Windows Sandbox. For this sample, extract the entire directory and open `Nuclemu-Desktop.exe`. Keep `nuclemu.exe` and `_internal` beside it. See the [Windows package notes](../packaging/windows/README.md).

The same final installer passed Windows 11 Sandbox checks for both current-user installation under a standard account and all-user installation under an administrator account. Windows 10 and older Windows versions remain unverified; Windows 7 SP1 is a compatibility target, not a verified minimum.

## macOS

The candidate filenames are `Nuclemu-0.0.1-macos-x86_64.dmg` for Intel and `Nuclemu-0.0.1-macos-arm64.dmg` for Apple Silicon. Open the matching DMG, drag `Nuclemu.app` to Applications, then start it from Applications. Close the launcher before replacing the app with an upgrade. To uninstall, remove `Nuclemu.app` from Applications; keep your experiment files.

The app's command-line companion is:

```sh
/Applications/Nuclemu.app/Contents/MacOS/nuclemu-cli serve --no-gui
```

The Intel candidate passed native runner checks on macOS 15.7.9, and arm64 on macOS 15.8.2: mounting and copying the app, using the CLI and experiment files, replacing an earlier package revision, and removing the app while retaining user data. These are tested environments, not minimum supported versions. The candidates use an ad-hoc signature and have no Developer ID signature or notarization. First launch of a downloaded app (including Gatekeeper), Finder startup and system save dialogs still need desktop verification. The smoke check made no downloads but did not disable the runner's network. See the [delivery record](desktop-release-delivery.md) for the full validation scope.

## Linux

The candidate targets Debian 12, amd64, with glibc 2.36. Its package names are `nuclemu_0.0.1-1_amd64.deb` and `nuclemu-0.0.1-1-linux-amd64.tar.gz`. The portable CLI passed a non-root check in a minimal, offline container without system Python or Node.js. A separate offline Debian container with a test driver was used to replace Debian package revision 0 with revision 1, start the menu entry under Xvfb, check that removal retained preferences and experiment files, and reopen the Windows sample experiments after relocating the portable directory. These checks cover Debian 12 amd64; other distributions remain unverified. See the [delivery record](desktop-release-delivery.md).

For the `.deb`, install or upgrade from the directory containing the file:

```sh
sudo dpkg -i ./nuclemu_0.0.1-1_amd64.deb
```

Open Nuclemu from the application menu, or use `nuclemu-desktop`. The installed package was also checked in a virtual X11 container with Xvfb and Openbox: starting from the desktop menu automatically opened the workbench in the default Firefox ESR 153.7.0. Physical desktop and Wayland sessions remain unverified. The terminal command is `nuclemu`; for example, `nuclemu serve --no-gui`. The application runtime is installed under `/opt/nuclemu`. Remove the package after closing Nuclemu:

```sh
sudo dpkg -r nuclemu
```

For the tar archive, extract the whole archive into a folder you can write to. In its `nuclemu-0.0.1` directory, run `./nuclemu-desktop` or `./nuclemu serve --no-gui`; keep `_internal` alongside these entries. No administrator account is needed for this directory package. To upgrade, extract to a new folder; to remove it, close the services and remove that application folder.

Both formats require these system libraries: `libc6 >= 2.36`, `libx11-6`, `libxext6`, `libxft2`, `libxrender1`, `libfontconfig1`, `libfreetype6`, `libexpat1` and `zlib1g`. Desktop use needs X11 or XWayland, fonts and a browser; `xdg-utils` and Chinese fonts are recommended. For offline deployment, have an administrator prepare these components first. The package includes Python and Tk, but not glibc. See the [Linux package notes](../packaging/linux/README.md).

## Open the workbench

Start Nuclemu from its desktop entry. When the launcher shows “已就绪” (ready), choose “在浏览器中打开” (open in browser). Keep the launcher open while you work. Closing a browser tab leaves the local service and experiment running; use the launcher to return.

The launcher starts with an automatically assigned port and automatic browser opening turned off. In “设置” (settings), you can choose a fixed port or enable automatic browser opening. Saved settings apply on the next start or retry; the current experiment keeps its address. If a port is occupied, choose another port and retry. You can copy the displayed local address into a browser when needed.

Choose a course in the catalogue, set the source and foil in the apparatus view, switch on the detector output, then open the instrument. Procedures and blank data tables are under “实验资料” (experiment materials). See the [workbench guide](gui.md).

## Save your work and close

Use the instrument's “保存” (save) button to keep the readings you need in the current experiment. Download selected records or the whole `.nuclemu` experiment from “实验记录” (experiment records).

Closing the launcher with an active experiment offers save and close, discard and close, or cancel. Save and close opens a system file dialog and writes the whole experiment before stopping the service. Cancelling the file dialog or a failed write keeps the experiment available for another attempt.

The whole experiment includes settings, round information and readings you explicitly saved. For example, if you saved readings at 3 s and continued to 5 s, closing with save keeps the 3 s readings. To keep the later readings, cancel closing, save them on the instrument, then close again. Reopen the `.nuclemu` file from the catalogue to check your saved data.

## Upgrade and remove

Before upgrading or uninstalling, save the readings you want, write the whole experiment to a folder you manage, and close the launcher. Also stop any terminal service with Ctrl+C.

Keep your `.nuclemu`, CSV and JSON files outside the application directory. Launcher preferences are stored per user in `~/.nuclemu/launcher.json`; on Windows, `~` is your user profile folder. The local workbench storage is under `~/.nuclemu/workbench/`. These internal files do not replace exported experiment files.

Candidate packaging keeps user preferences, local workbench storage and separately saved experiments when the program is removed. Installation, upgrade and removal checks are recorded per platform. For the directory sample, extract an upgrade to a separate folder, start it and reopen a saved experiment before retiring the old directory.

## Command line and source checkout

The package's CLI and desktop launcher share the same experiments and file formats. In the Windows directory sample, use `nuclemu.exe` from the extracted folder:

```powershell
.\nuclemu.exe serve --gui
.\nuclemu.exe serve --no-gui
```

`serve --gui` opens or recalls the desktop launcher. `serve --no-gui` runs a separate foreground service and prints its local URL without opening a browser; Ctrl+C stops it. Download your data first: interrupting the terminal service does not save the experiment for you. Choose exactly one of these two modes.

For a source checkout, use Python 3.11 or later from the repository root:

```sh
python -m nuclemu serve --gui
```

The desktop mode needs Python with Tk support. For a terminal-only service, use `python -m nuclemu serve --no-gui`. The existing `python -m nuclemu gui` command also remains available and opens a browser from a terminal-managed service. See the [CLI guide](cli.md) for scripted measurements.
