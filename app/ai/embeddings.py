"""Layer 2 (semantic similarity) - pluggable embedding providers.

Section 8 requires the embedding provider to be swappable (local
sentence-transformers, OpenAI, or another compatible provider) and
section 18 requires embeddings to be cached locally (packed into
`JobEmbedding.vector` as raw float32 bytes) so they are never
recomputed for an unchanged job.

Providers degrade gracefully: if a remote provider's package/API key
isn't available, `get_embedding_provider` falls back to the local
model rather than crashing the whole matching pipeline - consistent
with the "local-first" and "never silently fail (but never crash
either)" principles in sections 18/23.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.core.constants import EmbeddingProvider

logger = logging.getLogger(__name__)

_scipy_stats_workaround_applied = False


def _work_around_frozen_scipy_stats_bug() -> None:
    """A one-time, defensive workaround for a real PyInstaller-frozen-build
    bug: `scipy/stats/_distn_infrastructure.py` ends with

        for obj in [s for s in dir() if s.startswith('_doc_')]:
            exec('del ' + obj)
        del obj

    Under PyInstaller's frozen module loader specifically (never when run
    from source - confirmed by manually `exec()`-ing the same file into a
    fresh module namespace outside PyInstaller, which works fine), that
    `dir()` call returns nothing, the loop body never runs, and the final
    `del obj` raises `NameError: name 'obj' is not defined`, which aborts
    the import of `scipy.stats` entirely.

    `sentence-transformers` doesn't need `scipy.stats` (or `sklearn`,
    which itself imports `scipy.stats`) for anything WE use - both only
    get pulled in transitively by `sentence_transformers`' package
    `__init__.py` unconditionally importing `CrossEncoder`, whose
    unused *evaluation* classes do things like `from scipy.stats import
    pearsonr, spearmanr` and `from sklearn.metrics import roc_curve`
    directly, and unused "assisted generation" code in `transformers`
    does likewise. We never call any of that code path - only
    `SentenceTransformer(...).encode(...)`.

    The fix: if a real `scipy.stats` (or `sklearn`, which re-triggers
    the same underlying bug) import hits exactly this NameError, install
    a `sys.meta_path` import hook that transparently answers that
    package and EVERY submodule under it with an inert stub, rather than
    a fixed stub for one or two specific modules/attributes. Different
    submodules of the unused evaluation/generation code reach into
    different, unpredictable corners of `scipy.stats`/`sklearn` at
    import time (not call time) - `sklearn.metrics.roc_curve`,
    `sklearn.metrics.average_precision_score`, the whole
    `sklearn.metrics.pairwise` submodule, `scipy.stats.pearsonr`, and
    potentially others - so a hook that covers each whole package tree
    is the only approach that doesn't turn into an endless
    one-name-at-a-time chase. This never runs (and can never mask a real
    problem) when scipy loads normally, e.g. when running from source -
    and the rest of `scipy` (`scipy.sparse`, `scipy.linalg`, ...), which
    loads fine even when frozen, is untouched."""
    global _scipy_stats_workaround_applied
    if _scipy_stats_workaround_applied:
        return
    _scipy_stats_workaround_applied = True

    import sys

    if "scipy.stats" not in sys.modules:
        try:
            import scipy.stats  # noqa: F401
        except NameError:
            logger.warning(
                "Working around a known PyInstaller+scipy.stats packaging bug "
                "by stubbing out scipy.stats and sklearn (unused by this app's embedding path)."
            )
            finder = _StubModuleTreeFinder(("scipy.stats", "sklearn"))
            sys.meta_path.insert(0, finder)
            sys.modules.pop("scipy.stats", None)  # evict the partially-executed, now-broken real module

    _work_around_frozen_torch_dynamo_bug()


def _work_around_frozen_torch_dynamo_bug() -> None:
    """`torch._numpy._ufuncs.py` hits the same underlying bug as
    `_work_around_frozen_scipy_stats_bug` (a `for x in [...]: ...
    vars()[x] = ...` module-init idiom breaking under PyInstaller's
    frozen loader - see that function's docstring), reachable via
    `transformers.integrations.flex_attention`'s
    `@torch.compiler.disable(recursive=False)` applied to a class at
    import time - `torch.compiler.disable()`'s own implementation does
    `import torch._dynamo` unconditionally, which pulls in the broken
    `torch._numpy`.

    This function patches `torch.compiler.disable` to a
    behaviorally-correct, `torch._dynamo`-free replacement (safe because
    this app never calls `torch.compile()`, so "disable compilation for
    this function" and "return the function unchanged" are equivalent
    for us) - BUT note this alone turned out to be insufficient in
    testing: `transformers.modeling_utils.PreTrainedModel` (the base
    class needed for ANY HuggingFace model, hit regardless of the above)
    separately does `@torch._dynamo.allow_in_graph` directly on itself,
    so `torch._dynamo`/`torch._numpy` end up needing to import
    successfully either way - `_patched_builtins_for_frozen_module_init`
    (used by the caller alongside this function) is what actually makes
    that import succeed. This function is kept anyway since it's cheap,
    correct, and removes one unnecessary `torch._dynamo` import trigger
    - but the real fix for `torch._numpy` lives in the other function.

    Must run BEFORE `sentence_transformers`/`transformers` are imported,
    so this explicitly imports plain `torch` itself first - which loads
    fine; only `torch._dynamo`/`torch._numpy` are broken when frozen."""
    import torch.compiler

    if getattr(torch.compiler.disable, "__aijobfinder_patched__", False):
        return

    def _disable_without_dynamo(fn=None, recursive=True):
        if fn is None:
            return lambda f: f
        return fn

    _disable_without_dynamo.__aijobfinder_patched__ = True
    torch.compiler.disable = _disable_without_dynamo


class _patched_builtins_for_frozen_module_init:
    """A context manager that, ONLY while active, replaces the built-in
    no-argument `vars()`/`dir()` with explicit-frame-globals
    implementations - this is the actual root-cause fix for
    `torch/_numpy/_ufuncs.py`'s `for name in _binary: ...
    vars()[name] = ...` idiom breaking under PyInstaller's frozen loader
    (see `_work_around_frozen_torch_dynamo_bug`'s docstring) - confirmed
    by testing: WITHOUT this context manager, `SentenceTransformer(...)`
    fails to import in a frozen build; WITH it (and the scipy.stats/
    sklearn stub still in place), it imports and encodes successfully.

    This does NOT, on its own, fix `scipy/stats/_distn_infrastructure.py`'s
    superficially-similar `for obj in [s for s in dir() if ...]: ...; del
    obj` idiom - confirmed by testing: with ONLY this context manager
    active (the scipy.stats stub disabled), scipy.stats still raises the
    same `NameError`. The difference is almost certainly that scipy's
    `dir()` call sits inside a LIST COMPREHENSION (which, even after
    Python 3.12's PEP 709 comprehension inlining, still resolves builtin
    names differently enough under PyInstaller's frozen bytecode loading
    that patching the `builtins` module doesn't reach it) while torch's
    `vars()` call is a plain module-level statement. So both fixes stay
    - the scipy.stats/sklearn stub for the comprehension case, this
    context manager for the plain-statement case.

    Deliberately scoped to a `with` block around the exact import
    statement that can trigger the bug, restoring the real builtins
    immediately after (success or failure) - not installed for the
    process's whole lifetime, so it can't affect anything else that
    happens to call `vars()`/`dir()` with no arguments at runtime."""

    def __enter__(self):
        import builtins
        import sys

        self._real_vars = builtins.vars
        self._real_dir = builtins.dir

        def _frame_globals_vars(*args, **kwargs):
            if args or kwargs:
                return self._real_vars(*args, **kwargs)
            return sys._getframe(1).f_globals

        def _frame_globals_dir(*args, **kwargs):
            if args or kwargs:
                return self._real_dir(*args, **kwargs)
            return sorted(sys._getframe(1).f_globals.keys())

        builtins.vars = _frame_globals_vars
        builtins.dir = _frame_globals_dir
        return self

    def __exit__(self, *exc_info):
        import builtins

        builtins.vars = self._real_vars
        builtins.dir = self._real_dir
        return False


def _stub_attr_getattr(attr_name: str):
    if attr_name.startswith("__") and attr_name.endswith("__"):
        raise AttributeError(attr_name)  # keep dunder protocol lookups honest
    return lambda *args, **kwargs: (_ for _ in ()).throw(
        NotImplementedError(f"{attr_name} is stubbed out (unused) - see app.ai.embeddings")
    )


class _StubModuleTreeFinder:
    """A `sys.meta_path` finder/loader that answers an import of any of
    `roots` (e.g. `"scipy.stats"`) or any dotted name under one of them
    with an inert stub package - see
    `_work_around_frozen_scipy_stats_bug`'s docstring for why a single
    fixed stub module isn't enough here."""

    def __init__(self, roots: tuple[str, ...]):
        self._roots = roots

    def _matches(self, fullname: str) -> bool:
        return any(fullname == root or fullname.startswith(root + ".") for root in self._roots)

    def find_spec(self, fullname, path, target=None):
        import importlib.machinery

        if not self._matches(fullname):
            return None
        return importlib.machinery.ModuleSpec(fullname, self, is_package=True)

    def create_module(self, spec):
        import types

        module = types.ModuleType(spec.name)
        module.__getattr__ = _stub_attr_getattr  # PEP 562 - answers `from scipy.stats import <anything>`
        return module

    def exec_module(self, module):
        module.__path__ = []  # marks it as a package so `<root>.<anything>.<anything>` keeps resolving here


class EmbeddingBackend(Protocol):
    provider_name: str
    model_name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


# Raw cosine similarity is NOT a 0-100 "percent match" and must never be
# blended into the score as if it were. Measured against this app's own
# profile/job text with all-MiniLM-L6-v2 (see the calibration harness
# described below), realistic pairs land in a narrow band:
#
#     near-identical ML role vs ML profile ... 73
#     genuinely strong match, different wording 44-47
#     unrelated technical role (iOS vs ML) ... 17
#     completely unrelated (pastry chef) ..... 14
#
# Two arbitrary English documents share enough embedding space to score
# ~15 even when totally unrelated, and nothing realistic ever approaches
# 100. Feeding the raw number in made a 44 (an excellent match) look like
# "44% good" and dragged strong candidates below the email threshold, so
# no email was ever sent. These bounds rescale the *useful* band onto
# 0-100; they're model-specific, so changing the embedding model should
# mean re-measuring them.
SIMILARITY_FLOOR = 15.0   # at/below this, treat as no semantic signal
SIMILARITY_CEILING = 75.0  # at/above this, treat as a maximal match


def calibrate_similarity(raw_similarity: float) -> float:
    """Rescales a raw cosine similarity onto an interpretable 0-100 scale.

    See `SIMILARITY_FLOOR`/`SIMILARITY_CEILING` above for the measured
    reasoning. Clamped at both ends, so a freak value can never push a
    component score outside 0-100."""
    span = SIMILARITY_CEILING - SIMILARITY_FLOOR
    scaled = (raw_similarity - SIMILARITY_FLOOR) / span * 100.0
    return round(max(0.0, min(100.0, scaled)), 1)


def pack_vector(vector: np.ndarray) -> bytes:
    arr = np.asarray(vector, dtype=np.float32)
    return arr.tobytes()


def unpack_vector(data: bytes) -> np.ndarray:
    count = len(data) // struct.calcsize("f")
    return np.frombuffer(data, dtype=np.float32, count=count).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Returns a similarity in [0, 100], where 0 means "completely
    unrelated" rather than "opposite" - text embeddings are almost never
    truly anti-correlated, so rescaling raw cosine (roughly [0, 1] in
    practice for sentence embeddings) directly onto a 0-100 match scale
    is more meaningful than a signed [-100, 100] range."""
    if a.size == 0 or b.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    raw = float(np.dot(a, b) / denom)
    return max(0.0, min(1.0, raw)) * 100.0


_LOCAL_MODEL_CACHE: dict[str, object] = {}


class LocalEmbeddingBackend:
    """sentence-transformers, run entirely on-device. No API key, no
    network call, no data ever leaves the machine - the default and the
    only backend available in local-only mode."""

    provider_name = EmbeddingProvider.LOCAL.value

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name or "all-MiniLM-L6-v2"
        self._model = None

    def _get_model(self):
        if self.model_name in _LOCAL_MODEL_CACHE:
            return _LOCAL_MODEL_CACHE[self.model_name]
        _work_around_frozen_scipy_stats_bug()
        with _patched_builtins_for_frozen_module_init():
            from sentence_transformers import SentenceTransformer

        logger.info("Loading local embedding model %r (first use may take a while)...", self.model_name)
        model = SentenceTransformer(self.model_name)
        _LOCAL_MODEL_CACHE[self.model_name] = model
        return model

    @property
    def dimensions(self) -> int:
        return int(self._get_model().get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(list(texts), convert_to_numpy=True, show_progress_bar=False)
        return [np.asarray(v, dtype=np.float32) for v in vectors]


class OpenAIEmbeddingBackend:
    provider_name = EmbeddingProvider.OPENAI.value

    def __init__(self, api_key: str, model_name: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.model_name = model_name or "text-embedding-3-small"
        self.dimensions = 1536 if "small" in self.model_name else 3072

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.embeddings.create(model=self.model_name, input=list(texts))
        return [np.asarray(item.embedding, dtype=np.float32) for item in response.data]


class VoyageEmbeddingBackend:
    """Anthropic has no first-party embeddings API; Voyage AI is their
    recommended embeddings partner (see app.core.constants.EmbeddingProvider)."""

    provider_name = EmbeddingProvider.VOYAGE.value

    def __init__(self, api_key: str, model_name: str = "voyage-3-lite"):
        self.api_key = api_key
        self.model_name = model_name or "voyage-3-lite"
        self.dimensions = 512

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        import voyageai

        client = voyageai.Client(api_key=self.api_key)
        result = client.embed(list(texts), model=self.model_name, input_type="document")
        return [np.asarray(v, dtype=np.float32) for v in result.embeddings]


@dataclass
class AIRuntimeConfig:
    """Effective AI configuration for one matching run - resolved once
    per run from Settings (user overrides) falling back to `.env`
    (section 20), so the ranker/LLM analyzer never read `os.environ` or
    the database directly."""

    local_only: bool
    embedding_provider: str
    embedding_model: str
    llm_provider: str
    llm_model: str
    anthropic_api_key: str
    openai_api_key: str
    voyage_api_key: str
    gemini_api_key: str = ""
    local_llm_base_url: str = ""

    def has_usable_llm(self) -> bool:
        # A local LLM (Ollama/LM Studio/etc. on this machine) is exempt
        # from the `local_only` gate deliberately, not by oversight:
        # `local_only`'s whole promise is "nothing leaves this computer",
        # and a call to localhost keeps that promise exactly - unlike
        # Anthropic/OpenAI, there's no external API to disable it against.
        if self.llm_provider == "local":
            return bool(self.local_llm_base_url and self.llm_model)
        if self.local_only:
            return False
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        return False

    def uses_local_embeddings(self) -> bool:
        """Whether embeddings will actually run on the free local model -
        i.e. whether an embedding pass costs money. Mirrors the same
        fallback logic `get_embedding_backend` applies (a remote provider
        with no API key silently degrades to local), so callers deciding
        how many jobs to embed reach the same conclusion the backend
        will."""
        if self.local_only:
            return True
        if self.embedding_provider == EmbeddingProvider.OPENAI.value:
            return not self.openai_api_key
        if self.embedding_provider == EmbeddingProvider.VOYAGE.value:
            return not self.voyage_api_key
        return True


def resolve_ai_config(session, context) -> AIRuntimeConfig:
    """Settings-table overrides take priority over `.env`/AppConfig,
    mirroring the precedence already implemented in the AI Settings UI
    page (`app/ui/pages/ai_settings.py`)."""
    cfg = context.config
    repo = context.settings_repo
    prefix = "ai."
    return AIRuntimeConfig(
        local_only=repo.get_bool(session, prefix + "local_only", False),
        embedding_provider=repo.get(session, prefix + "embedding_provider", cfg.embedding_provider.value),
        embedding_model=repo.get(session, prefix + "embedding_model", cfg.embedding_model) or cfg.embedding_model,
        llm_provider=repo.get(session, prefix + "llm_provider", cfg.llm_provider.value),
        llm_model=repo.get(session, prefix + "llm_model", cfg.llm_model) or cfg.llm_model,
        anthropic_api_key=repo.get(session, prefix + "anthropic_api_key", cfg.anthropic_api_key),
        openai_api_key=repo.get(session, prefix + "openai_api_key", cfg.openai_api_key),
        voyage_api_key=repo.get(session, prefix + "voyage_api_key", cfg.voyage_api_key),
        gemini_api_key=repo.get(session, prefix + "gemini_api_key", cfg.gemini_api_key),
        local_llm_base_url=repo.get(session, prefix + "local_llm_base_url", cfg.local_llm_base_url),
    )


def get_embedding_backend(ai_config: AIRuntimeConfig) -> EmbeddingBackend:
    """Never raises - always returns a usable backend. Falls back to the
    local model if the configured remote provider is unusable (missing
    key, missing package, forced local-only mode)."""
    provider = EmbeddingProvider.LOCAL.value if ai_config.local_only else ai_config.embedding_provider

    if provider == EmbeddingProvider.OPENAI.value and ai_config.openai_api_key:
        try:
            return OpenAIEmbeddingBackend(ai_config.openai_api_key, ai_config.embedding_model)
        except Exception:
            logger.exception("OpenAI embedding backend unavailable; falling back to local model.")
    elif provider == EmbeddingProvider.VOYAGE.value and ai_config.voyage_api_key:
        try:
            return VoyageEmbeddingBackend(ai_config.voyage_api_key, ai_config.embedding_model)
        except Exception:
            logger.exception("Voyage embedding backend unavailable; falling back to local model.")

    model_name = ai_config.embedding_model
    if model_name in ("text-embedding-3-small", "text-embedding-3-large", "voyage-3-lite", "voyage-3"):
        model_name = "all-MiniLM-L6-v2"  # a remote-only model name leaking into local fallback
    return LocalEmbeddingBackend(model_name)
