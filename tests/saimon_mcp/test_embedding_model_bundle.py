"""Tests for the bundled local embedding model (SAIMON-EMBEDDING-MODEL-BUNDLE-1).

Pins the offline model-bundle path: ``embed_local`` loads a pre-downloaded
``nomic-embed-text-v1.5`` directory via fastembed's ``specific_model_path``
instead of downloading from HuggingFace at runtime. All network-free:
fastembed is mocked, never instantiated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class _RecordingEmbeddingModel:
    """Records the kwargs TextEmbedding was constructed with."""

    def __init__(self, *args, dims: int = 768, **kwargs):
        self._dims = dims
        self._kwargs = kwargs

    def embed(self, documents):
        return [[0.1] * self._dims for _ in documents]


def _install_fake_fastembed(monkeypatch: pytest.MonkeyPatch, model_cls) -> None:
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=model_cls))


class TestEmbeddingConfig:
    def test_reads_model_path_from_env(self, monkeypatch) -> None:
        from research_shared.embedding import EmbeddingConfig

        monkeypatch.setenv("SAIMON_EMBEDDING_MODEL_PATH", "/opt/saimon/models/nomic")
        assert EmbeddingConfig.from_env().model_path == "/opt/saimon/models/nomic"

    def test_model_path_defaults_to_empty(self, monkeypatch) -> None:
        from research_shared.embedding import EmbeddingConfig

        monkeypatch.delenv("SAIMON_EMBEDDING_MODEL_PATH", raising=False)
        assert EmbeddingConfig.from_env().model_path == ""


class TestBundledEmbedding:
    def test_embed_local_uses_specific_model_path_when_bundled(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        from research_shared.embedding import embed_local, reset_embedding_cache

        reset_embedding_cache()
        bundle_dir = tmp_path / "bundle"
        (bundle_dir / "onnx").mkdir(parents=True)
        (bundle_dir / "onnx" / "model.onnx").write_bytes(b"fake-onnx")
        (bundle_dir / "config.json").write_text("{}")

        captured: dict = {}

        class CapturingModel(_RecordingEmbeddingModel):
            def __init__(self, *args, **kwargs):
                captured["kwargs"] = kwargs
                super().__init__(*args, **kwargs)

        _install_fake_fastembed(monkeypatch, CapturingModel)

        result = embed_local("hello", model_path=str(bundle_dir))
        assert result is not None
        assert len(result) == 768
        assert captured["kwargs"].get("specific_model_path") == str(bundle_dir)

    def test_embed_local_fails_closed_when_bundled_path_missing(
        self, monkeypatch
    ) -> None:
        from research_shared.embedding import embed_local, reset_embedding_cache

        reset_embedding_cache()
        _install_fake_fastembed(monkeypatch, _RecordingEmbeddingModel)

        assert embed_local("hello", model_path="/does/not/exist") is None


class TestBundleScript:
    def test_allow_patterns_cover_fastembed_files(self) -> None:
        from scripts.bundle_embedding_model import ALLOW_PATTERNS

        assert "onnx/model.onnx" in ALLOW_PATTERNS
        assert "config.json" in ALLOW_PATTERNS
        assert "tokenizer.json" in ALLOW_PATTERNS
        assert "tokenizer_config.json" in ALLOW_PATTERNS

    def test_bundle_model_downloads_to_local_dir(self, monkeypatch, tmp_path) -> None:
        import huggingface_hub

        import scripts.bundle_embedding_model as bundle_mod

        captured: dict = {}

        def fake_snapshot_download(**kwargs):
            captured.update(kwargs)
            return "/tmp/ignored"

        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

        output = bundle_mod.bundle_model("nomic-ai/nomic-embed-text-v1.5", tmp_path / "out")
        assert output == tmp_path / "out"
        assert captured["repo_id"] == "nomic-ai/nomic-embed-text-v1.5"
        assert "onnx/model.onnx" in captured["allow_patterns"]


class TestDockerfileBundle:
    def test_dockerfile_bundles_model_and_sets_env(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        assert "SAIMON_EMBEDDING_MODEL_PATH" in dockerfile
        assert "HF_HUB_OFFLINE" in dockerfile
        assert "bundle_embedding_model.py" in dockerfile
