from dataclasses import replace

import pytest
from types import SimpleNamespace

from impl.core.context.embedding import BailianEmbeddingProvider
from impl.core.context.errors import ContextConfigurationError, ContextValidationError
from impl.core import knowledge_base
from impl.core import attribute_environment
from impl.core.config_schema import ConfigError


class _SequenceEmbedder:
    id = "test-embedding"
    dimensions = 3

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get_embedding_and_usage(self, _text):
        self.calls += 1
        return next(self.responses)


class _BatchEmbedder:
    id = "test-embedding"
    dimensions = 3

    def __init__(self, vectors, usage=None):
        self.vectors = vectors
        self.usage = usage or {"request_id": "batch"}
        self.calls = 0

    def get_embeddings_and_usage(self, texts):
        self.calls += 1
        self.texts = list(texts)
        return self.vectors, self.usage


def test_bailian_embedding_returns_valid_vector_from_one_request():
    embedder = _SequenceEmbedder([([1.0, 2.0, 3.0], {"request_id": "first"})])
    provider = BailianEmbeddingProvider(embedder=embedder)

    assert provider.embed(["router config"]) == [[1.0, 2.0, 3.0]]
    assert embedder.calls == 1


def test_bailian_embedding_batches_multiple_texts_in_one_request():
    embedder = _BatchEmbedder([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]])
    provider = BailianEmbeddingProvider(embedder=embedder)

    assert provider.embed(["query", "material"]) == [
        [1.0, 2.0, 3.0],
        [3.0, 2.0, 1.0],
    ]
    assert embedder.calls == 1
    assert embedder.texts == ["query", "material"]


def test_bailian_embedding_rejects_mismatched_batch_without_retry():
    embedder = _BatchEmbedder([[1.0, 2.0, 3.0]])

    with pytest.raises(ContextValidationError, match="batch size 1 for 2 texts"):
        BailianEmbeddingProvider(embedder=embedder).embed(["query", "material"])
    assert embedder.calls == 1


def test_bailian_embedding_reports_invalid_dimension_without_retry():
    embedder = _SequenceEmbedder([([1.0], {"request_id": "first"})])

    with pytest.raises(ContextValidationError, match="dimension 1 does not match expected 3"):
        BailianEmbeddingProvider(embedder=embedder).embed(["router config"])
    assert embedder.calls == 1


def test_bailian_embedding_reports_configuration_failure():
    embedder = _SequenceEmbedder([( [], {"error": "missing_bailian_api_key"})])

    with pytest.raises(ContextConfigurationError, match="missing_bailian_api_key"):
        BailianEmbeddingProvider(embedder=embedder).embed(["router config"])
    assert embedder.calls == 1


def test_bailian_embedder_does_not_inherit_desktop_proxy_by_default(monkeypatch):
    captured = {}

    def call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            status_code=200,
            output={"embeddings": [{"text_index": 0, "embedding": [1.0]}]},
            usage=None,
        )

    monkeypatch.setattr(
        knowledge_base,
        "dashscope",
        SimpleNamespace(TextEmbedding=SimpleNamespace(call=call)),
    )

    embedder = knowledge_base.BailianEmbedder(api_key="test-key")
    vectors, _usage = embedder.get_embeddings_and_usage(["query"])

    assert vectors == [[1.0]]
    assert captured["session"].trust_env is False


def test_bailian_embedder_uses_runtime_config_for_environment_proxy(monkeypatch):
    embedding_config = knowledge_base.get_embedding_config()
    monkeypatch.setattr(
        knowledge_base,
        "get_embedding_config",
        lambda: replace(embedding_config, trust_env_proxy=True),
    )

    embedder = knowledge_base.BailianEmbedder(api_key="test-key")

    assert embedder._session.trust_env is True


def test_bailian_embedder_refuses_disabled_runtime(monkeypatch):
    embedding_config = knowledge_base.get_embedding_config()
    monkeypatch.setattr(
        knowledge_base,
        "get_embedding_config",
        lambda: replace(embedding_config, enabled=False),
    )

    with pytest.raises(ConfigError, match="disabled by RuntimeConfig"):
        knowledge_base.BailianEmbedder(api_key="test-key")


def test_attribute_context_refuses_disabled_embedding_before_initialization(monkeypatch):
    runtime = SimpleNamespace(
        embedding=SimpleNamespace(enabled=False),
        require=lambda _component: None,
    )
    monkeypatch.setattr(attribute_environment, "get_runtime_config", lambda: runtime)

    with pytest.raises(ConfigError, match="embedding.enabled=true"):
        attribute_environment._build_context_tools(object(), object())
