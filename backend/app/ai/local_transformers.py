"""Local-only Transformers adapter for the optional policy-answer boundary.

The adapter is deliberately disabled until a local model name/path is supplied
by the server configuration.  It has no network path, no tools, and receives
only the already-authorized policy evidence assembled by the answer layer.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Lock
from typing import Any, Callable

from .generation import InvalidGeneratedAnswer, PolicyAnswerPrompt


DEFAULT_LOCAL_POLICY_TIMEOUT_SECONDS = 8.0
DEFAULT_LOCAL_POLICY_MAX_NEW_TOKENS = 256
_MAX_INPUT_TOKENS = 2048
_SUPPORTED_DTYPE_NAMES = frozenset({"auto", "bfloat16", "float16", "float32"})


class LocalTransformersPolicyAnswerProvider:
    """Generate one JSON policy-answer candidate from a cached local model.

    ``transformers`` is imported only when the provider is first used.  Both
    tokenizer and model loading are ``local_files_only`` so enabling the
    adapter never downloads weights.  The existing answer layer validates the
    returned JSON against the server-authorized evidence before it can reach a
    customer.
    """

    def __init__(
        self,
        model_name: str,
        *,
        timeout_seconds: float = DEFAULT_LOCAL_POLICY_TIMEOUT_SECONDS,
        max_new_tokens: int = DEFAULT_LOCAL_POLICY_MAX_NEW_TOKENS,
        text_generator: Callable[[str], str] | None = None,
        device: str | None = None,
        dtype: str = "auto",
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        if max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be positive")
        if device is not None and not device.strip():
            raise ValueError("device must not be empty")
        normalized_dtype = dtype.strip().casefold()
        if normalized_dtype not in _SUPPORTED_DTYPE_NAMES:
            raise ValueError(
                "dtype must be one of auto, bfloat16, float16, or float32"
            )
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_new_tokens = max_new_tokens
        self._text_generator = text_generator
        self.device = device.strip() if device is not None else None
        self.dtype = normalized_dtype
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._is_encoder_decoder: bool | None = None
        self._torch: Any | None = None
        self._runtime_device: str | None = None
        self._runtime_dtype: str | None = None
        self._generation_lock = Lock()
        self._timed_out = False
        self._generation_count = 0
        self._last_usage: dict[str, int | bool] | None = None

    @property
    def generation_count(self) -> int:
        """Number of provider calls started by this instance."""

        return self._generation_count

    @property
    def last_usage(self) -> dict[str, int | bool] | None:
        """Best-effort token accounting for the last completed generation."""

        return None if self._last_usage is None else dict(self._last_usage)

    @property
    def runtime_device(self) -> str | None:
        """Selected device after a real Transformers model has been loaded."""

        return self._runtime_device

    @property
    def runtime_dtype(self) -> str | None:
        """Selected weight dtype after a real Transformers model has been loaded."""

        return self._runtime_dtype

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        """Return one parsed JSON object or raise for a safe server fallback."""

        rendered_prompt = self._render_prompt(prompt)
        self._generation_count += 1
        self._last_usage = None
        output = self._run_with_timeout(rendered_prompt)
        if self._last_usage is None:
            # Custom test generators do not expose tokenizer counts.  Keep the
            # harness useful while marking this estimate explicitly.
            self._last_usage = {
                "input_tokens": len(rendered_prompt.split()),
                "output_tokens": len(output.split()),
                "estimated": True,
            }
        return self._parse_response(output)

    @staticmethod
    def _render_prompt(prompt: PolicyAnswerPrompt) -> str:
        payload = {
            "query": prompt.query,
            "evidence": [
                {
                    "citation_id": item.citation_id,
                    "policy_text": item.evidence.text,
                    "server_answer_text": item.answer_text,
                }
                for item in prompt.evidence
            ],
        }
        return (
            f"{prompt.system_instruction}\n\n"
            "Return exactly one JSON object with this schema and no surrounding text:\n"
            '{"answer":"exact sentence(s) from the allowed evidence","citation_ids":["evidence-1"]}\n\n'
            "UNTRUSTED_INPUT_JSON:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )

    def _run_with_timeout(self, rendered_prompt: str) -> str:
        # A model's native generation call cannot reliably be interrupted from
        # Python.  On the first timeout, keep this provider closed for the
        # process lifetime so repeated requests cannot accumulate work; the
        # answer layer falls back deterministically on every failure.
        with self._generation_lock:
            if self._timed_out:
                raise RuntimeError("local policy provider is unavailable after a timeout")
            generator = self._text_generator or self._generate_with_transformers
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolveai-local-llm")
            timed_out = False
            try:
                future = executor.submit(generator, rendered_prompt)
                return future.result(timeout=self.timeout_seconds)
            except FutureTimeoutError as error:
                timed_out = True
                self._timed_out = True
                future.cancel()
                raise TimeoutError("local policy provider timed out") from error
            finally:
                executor.shutdown(wait=not timed_out, cancel_futures=True)

    def _generate_with_transformers(self, rendered_prompt: str) -> str:
        model, tokenizer, is_encoder_decoder = self._load_transformers_model()
        torch = self._torch
        if torch is None:  # pragma: no cover - the loader always sets this
            raise RuntimeError("local Transformers runtime was not initialized")

        device = self._runtime_device or self._resolve_device(torch)
        encoded = self._encode_prompt(tokenizer, rendered_prompt)
        encoded = {name: value.to(device) for name, value in encoded.items()}
        with torch.inference_mode():
            generation_kwargs = {
                "do_sample": False,
                "max_new_tokens": self.max_new_tokens,
            }
            pad_token_id = getattr(tokenizer, "pad_token_id", None)
            if pad_token_id is None:
                pad_token_id = getattr(tokenizer, "eos_token_id", None)
            if pad_token_id is not None:
                generation_kwargs["pad_token_id"] = pad_token_id
            generated = model.generate(**encoded, **generation_kwargs)
        tokens = generated[0]
        if not is_encoder_decoder:
            tokens = tokens[encoded["input_ids"].shape[-1] :]
        self._last_usage = {
            "input_tokens": int(encoded["input_ids"].shape[-1]),
            "output_tokens": int(tokens.shape[-1]),
            "estimated": False,
        }
        return tokenizer.decode(tokens, skip_special_tokens=True)

    @staticmethod
    def _encode_prompt(tokenizer: Any, rendered_prompt: str) -> dict[str, Any]:
        """Encode an instruction prompt using a model's chat contract when available.

        Instruction checkpoints such as Gemma are materially more reliable when
        their tokenizer applies the model-specific conversation template.  The
        plain tokenizer path remains for older or non-chat checkpoints.
        """

        apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
        if callable(apply_chat_template):
            encoded = apply_chat_template(
                [{"role": "user", "content": rendered_prompt}],
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
                truncation=True,
                max_length=_MAX_INPUT_TOKENS,
            )
            if hasattr(encoded, "items"):
                return dict(encoded)
            return {"input_ids": encoded}

        encoded = tokenizer(
            rendered_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=_MAX_INPUT_TOKENS,
        )
        return dict(encoded)

    def _load_transformers_model(self) -> tuple[Any, Any, bool]:
        if self._model is not None and self._tokenizer is not None and self._is_encoder_decoder is not None:
            return self._model, self._tokenizer, self._is_encoder_decoder

        torch, AutoConfig, AutoTokenizer, AutoModelForCausalLM, AutoModelForSeq2SeqLM = (
            self._import_transformers_runtime()
        )
        device = self._resolve_device(torch)
        torch_dtype, dtype_name = self._resolve_dtype(torch, device)

        config = AutoConfig.from_pretrained(
            self.model_name,
            local_files_only=True,
            trust_remote_code=False,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            local_files_only=True,
            trust_remote_code=False,
        )
        # Gemma 3 text checkpoints are decoder-only and therefore use the
        # causal loader.  Keep the existing seq2seq branch for other cached
        # text-capable checkpoints without introducing another model stack.
        model_class = AutoModelForSeq2SeqLM if config.is_encoder_decoder else AutoModelForCausalLM
        model = model_class.from_pretrained(
            self.model_name,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch_dtype,
        )
        model.to(device)
        model.eval()
        self._torch = torch
        self._runtime_device = device
        self._runtime_dtype = dtype_name
        self._model = model
        self._tokenizer = tokenizer
        self._is_encoder_decoder = bool(config.is_encoder_decoder)
        return model, tokenizer, self._is_encoder_decoder

    def _import_transformers_runtime(self) -> tuple[Any, Any, Any, Any, Any]:
        try:
            import torch
            from transformers import (
                AutoConfig,
                AutoModelForCausalLM,
                AutoModelForSeq2SeqLM,
                AutoTokenizer,
            )
        except ImportError as error:
            raise RuntimeError("transformers and torch are required for local policy inference") from error
        return torch, AutoConfig, AutoTokenizer, AutoModelForCausalLM, AutoModelForSeq2SeqLM

    def _resolve_device(self, torch: Any) -> str:
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA device requested but CUDA is unavailable")
        return device

    def _resolve_dtype(self, torch: Any, device: str) -> tuple[Any, str]:
        dtype_name = self.dtype
        if dtype_name == "auto":
            if not device.startswith("cuda"):
                dtype_name = "float32"
            else:
                is_bf16_supported = getattr(torch.cuda, "is_bf16_supported", None)
                try:
                    supports_bf16 = bool(is_bf16_supported()) if callable(is_bf16_supported) else False
                except Exception:
                    supports_bf16 = False
                dtype_name = "bfloat16" if supports_bf16 else "float16"
        torch_dtype = getattr(torch, dtype_name, None)
        if torch_dtype is None:
            raise RuntimeError(f"the local torch runtime does not provide {dtype_name}")
        return torch_dtype, dtype_name

    @staticmethod
    def _parse_response(output: str) -> dict[str, object]:
        normalized = output.strip()
        # Small local instruction models commonly wrap an otherwise valid JSON
        # object in one markdown fence.  Remove only that exact outer fence;
        # arbitrary prose and multiple objects remain invalid.
        lines = normalized.splitlines()
        if (
            len(lines) >= 3
            and lines[0].strip().casefold() in {"```", "```json"}
            and lines[-1].strip() == "```"
        ):
            normalized = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(normalized)
        except (AttributeError, json.JSONDecodeError) as error:
            raise InvalidGeneratedAnswer("local model did not return a JSON object") from error
        if not isinstance(parsed, dict):
            raise InvalidGeneratedAnswer("local model did not return a JSON object")
        return parsed


__all__ = [
    "DEFAULT_LOCAL_POLICY_MAX_NEW_TOKENS",
    "DEFAULT_LOCAL_POLICY_TIMEOUT_SECONDS",
    "LocalTransformersPolicyAnswerProvider",
]
