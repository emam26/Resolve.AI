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
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        if max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be positive")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_new_tokens = max_new_tokens
        self._text_generator = text_generator
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._is_encoder_decoder: bool | None = None
        self._generation_lock = Lock()
        self._timed_out = False

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        """Return one parsed JSON object or raise for a safe server fallback."""

        rendered_prompt = self._render_prompt(prompt)
        output = self._run_with_timeout(rendered_prompt)
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
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        encoded = tokenizer(
            rendered_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=_MAX_INPUT_TOKENS,
        )
        encoded = {name: value.to(device) for name, value in encoded.items()}
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=self.max_new_tokens,
                pad_token_id=tokenizer.eos_token_id,
            )
        tokens = generated[0]
        if not is_encoder_decoder:
            tokens = tokens[encoded["input_ids"].shape[-1] :]
        return tokenizer.decode(tokens, skip_special_tokens=True)

    def _load_transformers_model(self) -> tuple[Any, Any, bool]:
        if self._model is not None and self._tokenizer is not None and self._is_encoder_decoder is not None:
            return self._model, self._tokenizer, self._is_encoder_decoder

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
        model_class = AutoModelForSeq2SeqLM if config.is_encoder_decoder else AutoModelForCausalLM
        model = model_class.from_pretrained(
            self.model_name,
            local_files_only=True,
            trust_remote_code=False,
        )
        model.to("cuda" if torch.cuda.is_available() else "cpu")
        model.eval()
        self._model = model
        self._tokenizer = tokenizer
        self._is_encoder_decoder = bool(config.is_encoder_decoder)
        return model, tokenizer, self._is_encoder_decoder

    @staticmethod
    def _parse_response(output: str) -> dict[str, object]:
        try:
            parsed = json.loads(output.strip())
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
