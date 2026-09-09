# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for AI Job Finder.

Build with (from the project root, inside the activated venv):
    pyinstaller --noconfirm packaging/aijobfinder.spec

Produces a one-folder build at dist/AIJobFinder/AIJobFinder.exe. One-folder
(rather than one-file) is deliberate: startup is faster, and it makes it
obvious where the app's own DLLs/resources live vs. the user's data
directory (which is always %LOCALAPPDATA%\\AIJobFinder, never inside the
install folder).

This spec bundles the full dependency set including the Phase 4/5 ML/LLM
stack (sentence-transformers, torch, transformers, anthropic, openai,
voyageai). `torch` is given the explicit `collect_all()` treatment below
in addition to its own contrib-maintained hook, since its hook alone
left some binaries/hidden imports missing in testing here; `transformers`
is left on its hook alone (sufficient in testing). This makes the build
slower and `dist/` larger than the hooks alone would, but see the KNOWN
LIMITATION below for why exhaustive collection still isn't the whole
story for this dependency stack.

RESOLVED ISSUE (kept here for the next person who hits something
similar): loading the LOCAL embedding model (sentence-transformers, the
default/no-API-key path - section 28's Demo Mode) inside the FROZEN
`.exe` used to fail outright. Root cause, precisely diagnosed via
`AIJF_SELFTEST=1` (see `app/core/selftest.py`) with `console=True`
temporarily, and confirmed fixed by re-running that same self-test
against a real frozen build after each fix below:

  Importing `sentence_transformers` transitively imports `scipy.stats`
  and `sklearn` (via unused CrossEncoder/evaluation/"assisted
  generation" code this app never calls) and `torch._dynamo`/
  `torch._numpy` (via `transformers.modeling_utils.PreTrainedModel`
  itself - core, unavoidable infrastructure needed for ANY HuggingFace
  model, not just unused code paths). Both `scipy/stats/
  _distn_infrastructure.py` (~line 368) and `torch/_numpy/_ufuncs.py`
  (~line 233) use a `for x in [...]: ...; <use x after/via the loop>`
  idiom at module scope to dynamically build up their namespace via a
  bare, no-argument `dir()`/`vars()` call - and under PyInstaller's
  frozen module loader specifically (never when run from source -
  confirmed by manually exec()-ing the same scipy file into a fresh
  module namespace outside PyInstaller, which works fine), that
  no-arg call doesn't see the enclosing module's own names, the loop
  variable is never bound, and the next line that uses it raises
  `NameError`.

  The fix has two parts, in `app/ai/embeddings.py`, applied together
  every time the local embedding model loads:
    1. `_work_around_frozen_scipy_stats_bug()` - `scipy.stats`'s
       specific instance of the bug is inside a LIST COMPREHENSION,
       which empirically does NOT get fixed by patching the `dir()`
       builtin (see #2) - likely because Python 3.12's PEP 709
       comprehension inlining interacts with PyInstaller's frozen
       bytecode loading in a way that bypasses a runtime `builtins`
       patch for names resolved from inside a comprehension. Instead,
       this installs a `sys.meta_path` stub for the whole
       `scipy.stats`/`sklearn` package trees - safe because nothing
       reachable from THIS app's actual embedding usage needs them for
       real (only unused evaluation code does).
    2. `_patched_builtins_for_frozen_module_init` - `torch._numpy`'s
       instance is a plain module-level statement (not inside a
       comprehension), and DOES get fixed by temporarily replacing the
       no-arg `vars()`/`dir()` builtins with explicit
       `sys._getframe(1).f_globals`-based implementations for the
       duration of the `sentence_transformers` import. Unlike (1),
       `torch._dynamo` can't be safely blanket-stubbed (real
       transformers code calls into it during normal forward passes,
       not just at import time), so this actually makes the real
       module import successfully rather than avoiding needing it.
  Confirmed empirically that each fix is necessary for its respective
  module and insufficient alone for the other - see the docstrings on
  both for the specific negative-result tests that showed this.

Always test a freshly frozen build end-to-end (upload a resume, run a
scan, run AI matching, and specifically try the local embedding model)
before shipping - ML libraries are the most common source of "works from
source, breaks when frozen" issues, and a missing data file/incompatible
loop idiom usually only surfaces as a runtime error, not a build failure.
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# SPECPATH is injected by PyInstaller as the absolute directory containing
# this .spec file, regardless of the caller's current working directory -
# using it (rather than a bare relative path) means `pyinstaller
# packaging/aijobfinder.spec` works the same whether invoked from the
# project root (as documented in README.md) or from packaging/ itself.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hidden_imports = (
    collect_submodules("sqlalchemy.dialects.sqlite")
    + collect_submodules("app")
)
binaries = []
datas = []

# Packages with non-Python payloads PyInstaller's static analysis (or its
# contrib hook, for torch) can't fully discover on its own - see the
# module docstring above for why `torch` is here despite already having a
# hook, and why `transformers` currently isn't.
for package in ("sentence_transformers", "torch", "anthropic", "openai", "voyageai"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hidden_imports += pkg_hidden

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIJobFinder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AIJobFinder",
)
