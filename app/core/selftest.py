"""A headless self-test for a frozen build (`AIJF_SELFTEST=1`).

ML packages (sentence-transformers/torch) are the most common source of
"works from source, breaks when frozen" issues (see the packaging spec
and README) - a missing bundled data file or DLL typically only surfaces
as a runtime error deep inside a library, not a PyInstaller build
failure. This lets a maintainer verify a freshly built `.exe` end-to-end
in seconds, without manually clicking through the GUI:

    AIJF_SELFTEST=1 dist\\AIJobFinder\\AIJobFinder.exe   (frozen build)
    $env:AIJF_SELFTEST=1; python main.py                 (from source)

Results are written to the log file (`<data dir>\\logs\\aijobfinder.log`)
via the `logging` module, NOT `print()`. This build's `AIJobFinder.exe`
is a windowed (`console=False`) executable - it has no attached console,
so `sys.stdout`/`sys.stderr` are not connected to anything a caller can
read, and `print()` is not reliably safe to call at all in that mode on
every PyInstaller/Python combination. The exit code (0 pass / 1 fail) is
the only thing safe to depend on from outside; the log file is where the
actual pass/fail detail per check lives.

Deliberately NOT a general-purpose CLI - just enough to catch the
packaging failure mode this project is most exposed to. Never invoked
during normal app usage.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def _report(ok: bool, label: str, detail: str = "") -> None:
    tag = "OK" if ok else "FAIL"
    logger.info("[%s] %s%s", tag, label, f": {detail}" if detail else "")


def run_selftest() -> int:
    try:
        from app.core.app_context import bootstrap

        context = bootstrap()
    except Exception:
        # Logging isn't configured yet if bootstrap() itself failed -
        # this is the one case with no log file to write to.
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).exception("Self-test: bootstrap failed")
        return 1

    from app import __version__

    logger.info("AI Job Finder self-test starting (version %s)...", __version__)
    _report(True, "Database/config bootstrap")

    passed = True

    try:
        from app.ai.embeddings import AIRuntimeConfig, get_embedding_backend

        ai_config = AIRuntimeConfig(
            local_only=True, embedding_provider="local", embedding_model=context.config.embedding_model,
            llm_provider="none", llm_model="", anthropic_api_key="", openai_api_key="", voyage_api_key="",
        )
        backend = get_embedding_backend(ai_config)
        vectors = backend.embed(["Principal Simulation Engineer with 15 years of CFD experience."])
        assert len(vectors) == 1 and vectors[0].shape[0] > 0
        _report(True, "Local embedding model loaded and encoded a test sentence", f"{vectors[0].shape[0]} dims")
    except Exception:
        logger.exception("Self-test: embedding backend failed")
        _report(False, "Embedding backend")
        passed = False

    try:
        import tempfile
        from pathlib import Path

        from app.resume.parser import parse_resume_file

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Jane Doe\nSenior Software Engineer\nPython, AWS")
            temp_path = Path(f.name)
        try:
            parsed = parse_resume_file(temp_path)
            assert "Jane Doe" in parsed.text
        finally:
            temp_path.unlink(missing_ok=True)
        _report(True, "Resume text extraction", "PyMuPDF/python-docx bundled correctly")
    except Exception:
        logger.exception("Self-test: resume parsing failed")
        _report(False, "Resume parsing")
        passed = False

    logger.info("Self-test %s.", "PASSED" if passed else "FAILED - see exceptions above")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run_selftest())
