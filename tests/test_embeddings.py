"""Tests for the embedding provider abstraction (section 8 Layer 2 /
section 18): vector packing round-trip, cosine similarity, and provider
fallback logic - never loads a real model or calls a real API."""

from __future__ import annotations

import numpy as np
import pytest

from app.ai.embeddings import (
    AIRuntimeConfig,
    LocalEmbeddingBackend,
    OpenAIEmbeddingBackend,
    VoyageEmbeddingBackend,
    _StubModuleTreeFinder,
    _work_around_frozen_scipy_stats_bug,
    cosine_similarity,
    get_embedding_backend,
    pack_vector,
    unpack_vector,
)


def _config(**overrides) -> AIRuntimeConfig:
    base = dict(
        local_only=False, embedding_provider="local", embedding_model="all-MiniLM-L6-v2",
        llm_provider="none", llm_model="", anthropic_api_key="", openai_api_key="", voyage_api_key="",
    )
    base.update(overrides)
    return AIRuntimeConfig(**base)


def test_pack_unpack_round_trip():
    vector = np.array([0.1, -0.5, 3.25, 0.0], dtype=np.float32)
    restored = unpack_vector(pack_vector(vector))
    assert np.allclose(vector, restored)


def test_calibration_maps_the_measured_useful_band_onto_0_100():
    """Raw cosine from all-MiniLM-L6-v2 on real profile/job text lands in
    a narrow band (~15 for totally unrelated, ~73 for a near-perfect
    match) - see the constants' docstring. Feeding the raw value into the
    score made an excellent match look mediocre, so the band is
    rescaled."""
    from app.ai.embeddings import calibrate_similarity

    assert calibrate_similarity(14.4) == 0.0    # measured: "pastry chef" vs ML profile
    assert calibrate_similarity(17.4) < 10      # measured: unrelated iOS role
    assert 45 < calibrate_similarity(44.4) < 60  # measured: genuinely strong match
    assert calibrate_similarity(72.9) > 90      # measured: near-identical role


def test_calibration_is_clamped_at_both_ends():
    from app.ai.embeddings import calibrate_similarity

    assert calibrate_similarity(-20.0) == 0.0
    assert calibrate_similarity(0.0) == 0.0
    assert calibrate_similarity(100.0) == 100.0
    assert calibrate_similarity(250.0) == 100.0


def test_calibration_is_monotonic():
    """A better raw similarity must never produce a worse calibrated one."""
    from app.ai.embeddings import calibrate_similarity

    values = [calibrate_similarity(v) for v in range(0, 101, 5)]
    assert values == sorted(values)


def test_cosine_similarity_identical_vectors_is_max():
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(v, v) == pytest.approx(100.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_empty_vector_is_zero_not_error():
    assert cosine_similarity(np.array([]), np.array([1.0])) == 0.0


def test_cosine_similarity_zero_vector_is_zero_not_nan():
    a = np.array([0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == 0.0


def test_get_backend_uses_local_by_default():
    backend = get_embedding_backend(_config())
    assert isinstance(backend, LocalEmbeddingBackend)


def test_get_backend_forces_local_when_local_only_even_if_openai_configured():
    backend = get_embedding_backend(
        _config(local_only=True, embedding_provider="openai", openai_api_key="sk-test")
    )
    assert isinstance(backend, LocalEmbeddingBackend)


def test_get_backend_uses_openai_when_configured():
    backend = get_embedding_backend(
        _config(embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="sk-test")
    )
    assert isinstance(backend, OpenAIEmbeddingBackend)


def test_get_backend_falls_back_to_local_without_api_key():
    backend = get_embedding_backend(_config(embedding_provider="openai", openai_api_key=""))
    assert isinstance(backend, LocalEmbeddingBackend)


def test_get_backend_uses_voyage_when_configured():
    backend = get_embedding_backend(_config(embedding_provider="voyage", voyage_api_key="pa-test"))
    assert isinstance(backend, VoyageEmbeddingBackend)


def test_scipy_stats_workaround_is_a_noop_when_scipy_stats_imports_cleanly(monkeypatch):
    """This app's normal (non-frozen) environment has a working
    scipy.stats/sklearn, so the workaround must never install a stub
    there - it's gated on a real, specific NameError that only happens
    under PyInstaller (see the function's docstring)."""
    import app.ai.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "_scipy_stats_workaround_applied", False)
    _work_around_frozen_scipy_stats_bug()

    import scipy.stats

    assert scipy.stats.__spec__.loader is not None  # a real module, not our stub
    # The real, non-stubbed function actually does real work rather than
    # our stub's "always raise NotImplementedError".
    r, p = scipy.stats.pearsonr([1, 2, 3], [1, 2, 3])
    assert r == pytest.approx(1.0)


def test_torch_compiler_disable_patch_is_behaviorally_correct(monkeypatch):
    """`_work_around_frozen_torch_dynamo_bug` replaces `torch.compiler.
    disable` with a version that never imports `torch._dynamo` - verify
    it's still semantically equivalent for our (never-compiled) usage:
    used as a plain decorator, used as `@disable(recursive=False)`, and
    called directly, it must always yield the original function back,
    still callable with its original behavior."""
    import app.ai.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "_scipy_stats_workaround_applied", False)
    _work_around_frozen_scipy_stats_bug()

    import torch

    assert getattr(torch.compiler.disable, "__aijobfinder_patched__", False) is True

    def _example(x):
        return x + 1

    # `@torch.compiler.disable` (bare, no call)
    wrapped = torch.compiler.disable(_example)
    assert wrapped(41) == 42

    # `@torch.compiler.disable(recursive=False)` (called with kwargs first)
    decorator = torch.compiler.disable(recursive=False)
    wrapped2 = decorator(_example)
    assert wrapped2(41) == 42

    # Applying it to a class (as flex_attention.py does) must not raise.
    @torch.compiler.disable(recursive=False)
    class Wrapped:
        pass

    assert Wrapped is not None


def test_stub_finder_answers_arbitrary_submodule_imports():
    """Directly exercises the `sys.meta_path` stub mechanism the
    workaround installs, independent of whether the real trigger
    condition (a PyInstaller-only NameError) can be reproduced in this
    test environment. This is the key property the fix needs: different
    unused sentence-transformers/transformers code paths reach into
    different, unpredictable `scipy.stats`/`sklearn` submodules at
    import time."""
    finder = _StubModuleTreeFinder(("scipy.stats", "sklearn"))
    for name in (
        "sklearn", "sklearn.metrics", "sklearn.metrics.pairwise", "sklearn.utils.validation",
        "scipy.stats", "scipy.stats.distributions",
    ):
        spec = finder.find_spec(name, None)
        assert spec is not None and spec.name == name
        # Deliberately NOT registered in sys.modules here - this test only
        # verifies the finder/loader's own behavior in isolation, and
        # mutating the real sys.modules would leak a fake "sklearn" into
        # every other test in the process (including the "imports
        # cleanly" test above, which needs the real one).
        module = finder.create_module(spec)
        finder.exec_module(module)

        with pytest.raises(NotImplementedError):
            module.anything_at_all()
        with pytest.raises(AttributeError):
            module.__nonexistent_dunder_hook__  # dunder lookups stay honest, not stubbed

    assert finder.find_spec("numpy", None) is None  # only intercepts the given roots
    assert finder.find_spec("scipy.sparse", None) is None  # not "scipy" itself, only "scipy.stats"


def test_get_backend_local_fallback_never_reuses_a_remote_model_name():
    """A remote-only model name (e.g. left over from switching providers)
    must never leak into the local fallback - sentence-transformers would
    fail trying to download a nonexistent Hugging Face repo named
    "text-embedding-3-small"."""
    backend = get_embedding_backend(
        _config(embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="")
    )
    assert isinstance(backend, LocalEmbeddingBackend)
    assert backend.model_name == "all-MiniLM-L6-v2"
