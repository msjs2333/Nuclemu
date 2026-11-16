"""Console entry inside the macOS application bundle."""
import sys

if __name__ == '__main__':
    if sys.argv[1:] == ['--bundle-check']:
        import json
        import platform
        import sqlite3
        import tkinter
        from pathlib import Path
        import nuclemu
        print(json.dumps(dict(python=sys.version, architecture=platform.machine(),
            sqlite=sqlite3.sqlite_version, tcl=tkinter.Tcl().eval('info patchlevel'),
            tk=tkinter.TkVersion,
            resources_present=(Path(nuclemu.__file__).with_name('static') / 'index.html').is_file())))
    else:
        from nuclemu.cli import main
        raise SystemExit(main())
