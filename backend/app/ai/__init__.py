"""Deterministic AI-facing services for the offline M2 slice."""

from .answer import GroundedAnswer, PolicyRetriever, answer_from_published_policy
from .generation import (
    AuthorizedPolicyEvidence,
    GeneratedPolicyAnswer,
    InvalidGeneratedAnswer,
    PolicyAnswerPrompt,
    PolicyAnswerProvider,
    PromptContextMetadata,
    UntrustedCustomerMemory,
    build_policy_answer_prompt,
)
from .local_transformers import LocalTransformersPolicyAnswerProvider
from .provider_adapters import (
    CloudflareWorkersAIPolicyAnswerProvider,
    GeminiPolicyAnswerProvider,
    ModelScopePolicyAnswerProvider,
    OpenAICompatiblePolicyAnswerProvider,
    ProviderConfigurationError,
    ProviderRequestError,
    RoutedPolicyAnswerProvider,
    build_provider_adapter,
)

__all__ = [
    "AuthorizedPolicyEvidence",
    "GeneratedPolicyAnswer",
    "GroundedAnswer",
    "InvalidGeneratedAnswer",
    "PolicyAnswerPrompt",
    "PolicyAnswerProvider",
    "PromptContextMetadata",
    "UntrustedCustomerMemory",
    "build_policy_answer_prompt",
    "PolicyRetriever",
    "LocalTransformersPolicyAnswerProvider",
    "CloudflareWorkersAIPolicyAnswerProvider",
    "GeminiPolicyAnswerProvider",
    "ModelScopePolicyAnswerProvider",
    "OpenAICompatiblePolicyAnswerProvider",
    "ProviderConfigurationError",
    "ProviderRequestError",
    "RoutedPolicyAnswerProvider",
    "answer_from_published_policy",
    "build_provider_adapter",
]
