"""Deterministic AI-facing services for the offline M2 slice."""

from .answer import GroundedAnswer, PolicyRetriever, answer_from_published_policy

__all__ = ["GroundedAnswer", "PolicyRetriever", "answer_from_published_policy"]
