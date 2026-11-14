# Windows installer resources

The installer uses [Inno Setup 6.7.4](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_4).
The compiler is a build tool and is not installed on student machines. Its generated
Setup and Uninstall programs retain their built-in copyright and website notices.
The unmodified [Inno Setup license](Inno-Setup-LICENSE.txt) is also installed under
`licenses/Inno Setup`.

`ChineseSimplified.isl` is the unmodified Simplified Chinese translation from the
[same official source tag](https://github.com/jrsoftware/issrc/blob/is-6_7_4/Files/Languages/Unofficial/ChineseSimplified.isl).
It retains its maintainer, source links and translator notice. The source tree's
[license](https://github.com/jrsoftware/issrc/blob/is-6_7_4/license.txt) permits use
and redistribution subject to retaining its notices and conditions; that license
is reproduced in this directory. This translation is user contributed, as marked
by its upstream location, rather than bundled with the compiler's default languages.

The offline application directory carries its own Nuclemu, Python and PyInstaller
notices under `_internal/licenses` and the notices supplied with Tcl/Tk and other
runtime resources. Those files are copied unchanged by the installer.
