from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from backend.app.ai.answer import answer_from_published_policy
from backend.app.ai.generation import (
    AuthorizedPolicyEvidence,
    InvalidGeneratedAnswer,
    PolicyAnswerPrompt,
)
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.rag.models import PolicyEvidence


class _FakeTensor:
    shape = (1, 4)

    def __init__(self) -> None:
        self.devices: list[str] = []

    def to(self, device: str) -> "_FakeTensor":
        self.devices.append(device)
        return self

    def __getitem__(self, _index):
        return self


class _FakeTorch:
    float32 = object()
    float16 = object()
    bfloat16 = object()

    def __init__(self, *, cuda_available: bool, bfloat16_supported: bool = False) -> None:
        self.cuda = SimpleNamespace(
            is_available=lambda: cuda_available,
            is_bf16_supported=lambda: bfloat16_supported,
        )

    class _InferenceMode:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def inference_mode(self):
        return self._InferenceMode()


class _FakeModel:
    def __init__(self) -> None:
        self.devices: list[str] = []
        self.generate_kwargs: dict[str, object] | None = None

    def to(self, device: str) -> "_FakeModel":
        self.devices.append(device)
        return self

    def eval(self) -> "_FakeModel":
        return self

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return [_FakeTensor()]


class _FakeTokenizer:
    eos_token_id = 2
    pad_token_id = None

    def __init__(self) -> None:
        self.encoded = _FakeTensor()

    def __call__(self, rendered: str, **kwargs):
        del rendered, kwargs
        return {"input_ids": self.encoded}

    def decode(self, tokens, *, skip_special_tokens: bool) -> str:
        del tokens, skip_special_tokens
        return '{"answer":"If a shipment is delayed.","citation_ids":["evidence-1"]}'


def _fake_runtime(
    *, cuda_available: bool, bfloat16_supported: bool = False, encoder_decoder: bool = False
):
    fake_torch = _FakeTorch(
        cuda_available=cuda_available,
        bfloat16_supported=bfloat16_supported,
    )
    calls: dict[str, list[dict[str, object]]] = {
        "config": [],
        "tokenizer": [],
        "causal": [],
        "seq2seq": [],
    }
    fake_model = _FakeModel()
    fake_tokenizer = _FakeTokenizer()

    class FakeConfig:
        is_encoder_decoder = encoder_decoder

        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls["config"].append({"model_name": model_name, **kwargs})
            return FakeConfig()

    class FakeTokenizerLoader:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls["tokenizer"].append({"model_name": model_name, **kwargs})
            return fake_tokenizer

    class FakeCausalLoader:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls["causal"].append({"model_name": model_name, **kwargs})
            return fake_model

    class FakeSeq2SeqLoader:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls["seq2seq"].append({"model_name": model_name, **kwargs})
            return fake_model

    return (
        (fake_torch, FakeConfig, FakeTokenizerLoader, FakeCausalLoader, FakeSeq2SeqLoader),
        calls,
        fake_model,
        fake_tokenizer,
    )


def _prompt() -> PolicyAnswerPrompt:
    evidence = PolicyEvidence(
        document_id="delivery-policy",
        document_version="v2",
        section="Delayed shipments",
        release_id="release_2026_11_01",
        visibility="public",
        score=0.91,
        text="If a shipment is delayed, customers may contact support for an updated estimate.",
    )
    return PolicyAnswerPrompt(
        query="Where is my delayed order?",
        evidence=[
            AuthorizedPolicyEvidence(
                citation_id="evidence-1",
                evidence=evidence,
                answer_text="If a shipment is delayed, contact support for an updated estimate.",
            )
        ],
    )


def test_local_transformers_provider_uses_structured_local_output() -> None:
    seen: list[str] = []
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: (
            seen.append(rendered)
            or json.dumps(
                {
                    "answer": "If a shipment is delayed, contact support for an updated estimate.",
                    "citation_ids": ["evidence-1"],
                }
            )
        ),
    )

    response = provider.generate(_prompt())

    assert response["citation_ids"] == ["evidence-1"]
    assert provider.generation_count == 1
    assert provider.last_usage is not None
    assert provider.last_usage["estimated"] is True
    assert provider.last_usage["input_tokens"] > 0
    assert provider.last_usage["output_tokens"] > 0
    assert "Where is my delayed order?" in seen[0]
    assert "delivery-policy" not in seen[0]
    assert "server_answer_text" in seen[0]
    assert "Return exactly one JSON object" in seen[0]


def test_local_transformers_provider_accepts_one_json_markdown_fence() -> None:
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: (
            '```json\n{"answer":"If a shipment is delayed, contact support for an '
            'updated estimate.","citation_ids":["evidence-1"]}\n```'
        ),
    )

    response = provider.generate(_prompt())

    assert response["citation_ids"] == ["evidence-1"]


def test_local_transformers_provider_rejects_non_json_output() -> None:
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: "Here is your answer: not JSON",
    )

    with pytest.raises(InvalidGeneratedAnswer, match="JSON object"):
        provider.generate(_prompt())


def test_local_transformers_provider_integrates_through_grounding_boundary() -> None:
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: json.dumps(
            {
                "answer": "If a shipment is delayed, contact support for an updated estimate.",
                "citation_ids": ["evidence-1"],
            }
        ),
    )

    response = answer_from_published_policy("shipment delayed", response_provider=provider)

    assert response.grounded is True
    assert response.generation_mode == "model"
    assert response.citation_ids == ["evidence-1"]


def test_local_transformers_provider_closes_after_timeout() -> None:
    def slow_generator(rendered: str) -> str:
        del rendered
        time.sleep(0.05)
        return "{}"

    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        timeout_seconds=0.001,
        text_generator=slow_generator,
    )

    with pytest.raises(TimeoutError, match="timed out"):
        provider.generate(_prompt())
    with pytest.raises(RuntimeError, match="unavailable"):
        provider.generate(_prompt())


@pytest.mark.parametrize(
    ("cuda_available", "bfloat16_supported", "expected_device", "expected_dtype"),
    [
        (False, False, "cpu", "float32"),
        (True, True, "cuda", "bfloat16"),
        (True, False, "cuda", "float16"),
    ],
)
def test_cached_transformers_loading_selects_safe_device_and_dtype(
    cuda_available: bool,
    bfloat16_supported: bool,
    expected_device: str,
    expected_dtype: str,
) -> None:
    runtime, calls, model, _ = _fake_runtime(
        cuda_available=cuda_available,
        bfloat16_supported=bfloat16_supported,
    )
    provider = LocalTransformersPolicyAnswerProvider("gemma-3-4b-it")
    provider._import_transformers_runtime = lambda: runtime

    provider._load_transformers_model()

    assert calls["config"][0]["local_files_only"] is True
    assert calls["tokenizer"][0]["local_files_only"] is True
    assert calls["causal"][0]["local_files_only"] is True
    assert calls["causal"][0]["trust_remote_code"] is False
    assert calls["causal"][0]["torch_dtype"] is getattr(
        runtime[0], expected_dtype
    )
    assert calls["seq2seq"] == []
    assert model.devices == [expected_device]
    assert provider.runtime_device == expected_device
    assert provider.runtime_dtype == expected_dtype


def test_transformers_generation_uses_loaded_device_and_safe_padding() -> None:
    runtime, _, model, tokenizer = _fake_runtime(
        cuda_available=True,
        bfloat16_supported=True,
    )
    provider = LocalTransformersPolicyAnswerProvider(
        "gemma-3-4b-it",
        max_new_tokens=17,
    )
    provider._import_transformers_runtime = lambda: runtime

    output = provider._generate_with_transformers("prompt")

    assert json.loads(output)["citation_ids"] == ["evidence-1"]
    assert tokenizer.encoded.devices == ["cuda"]
    assert model.generate_kwargs == {
        "input_ids": tokenizer.encoded,
        "do_sample": False,
        "max_new_tokens": 17,
        "pad_token_id": tokenizer.eos_token_id,
    }


def test_transformers_generation_uses_model_chat_template_when_available() -> None:
    runtime, _, model, tokenizer = _fake_runtime(
        cuda_available=True,
        bfloat16_supported=True,
    )
    calls: list[dict[str, object]] = []

    def apply_chat_template(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return {"input_ids": tokenizer.encoded}

    tokenizer.apply_chat_template = apply_chat_template
    provider = LocalTransformersPolicyAnswerProvider("gemma-3-4b-it")
    provider._import_transformers_runtime = lambda: runtime

    provider._generate_with_transformers("prompt")

    assert calls[0]["messages"] == [{"role": "user", "content": "prompt"}]
    assert calls[0]["add_generation_prompt"] is True
    assert calls[0]["return_dict"] is True
    assert model.generate_kwargs is not None


def test_cached_model_load_is_local_only_and_preserves_loader_errors() -> None:
    runtime, calls, _, _ = _fake_runtime(cuda_available=False)

    class FailingCausalLoader:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls["causal"].append({"model_name": model_name, **kwargs})
            raise OSError("checkpoint is not available in the local cache")

    runtime = (*runtime[:3], FailingCausalLoader, runtime[4])
    provider = LocalTransformersPolicyAnswerProvider("gemma-3-4b-it")
    provider._import_transformers_runtime = lambda: runtime

    with pytest.raises(OSError, match="local cache"):
        provider._load_transformers_model()

    assert calls["causal"][0]["local_files_only"] is True


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("nan"), float("inf")])
def test_local_transformers_provider_rejects_invalid_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        LocalTransformersPolicyAnswerProvider(
            "local-model",
            timeout_seconds=timeout_seconds,
        )
