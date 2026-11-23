"""Testable FastAPI routes for the deterministic M1 API slice."""

import os
from typing import Awaitable, Callable

from fastapi import Body, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.app.contracts import (
    AppendMessageRequest,
    AppendMessageResponse,
    ConversationSummary,
    CreateConversationRequest,
    CreateRefundRequest,
    DemoLoginRequest,
    DemoLoginResponse,
    ErrorResponse,
    OrderSummary,
    RefundListResponse,
    RefundSummary,
    SupportConversationSummary,
    SupportInboxResponse,
)
from backend.app.ai.answer import PolicyRetriever
from backend.app.ai.generation import PolicyAnswerProvider
from backend.app.ai.investigation import InvestigationModel
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.diagnostics import (
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from backend.app.services.in_memory import (
    ConversationStateConflict,
    ForbiddenOperation,
    IdempotencyConflict,
    InMemoryResolveService,
    RefundValidationError,
)
from backend.app.rag.pgvector_store import PgVectorPolicyRetriever
from backend.app.rag.semantic import SentenceTransformerEmbeddingProvider
from backend.app.commerce import CommerceRepository


UNAUTHENTICATED = {
    "code": "unauthenticated",
    "message": "Authentication is required.",
    "details": {},
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message, "details": {}})
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        return None
    return token


def _configured_policy_retriever(database_url: str) -> PolicyRetriever | None:
    """Opt into local semantic retrieval only for an explicitly configured PG app."""

    if os.getenv("RESOLVEAI_POLICY_RETRIEVAL", "lexical").casefold() != "semantic":
        return None
    if not database_url.startswith(("postgresql", "postgres")):
        return None
    provider = SentenceTransformerEmbeddingProvider(
        model_name=os.getenv(
            "RESOLVEAI_SENTENCE_TRANSFORMER_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        local_files_only=True,
    )
    return PgVectorPolicyRetriever(database_url, provider)


def _configured_commerce_repository() -> CommerceRepository | None:
    """Enable imported orders only through an explicit local database URL."""

    commerce_database_url = os.getenv("RESOLVEAI_COMMERCE_DATABASE_URL")
    if not commerce_database_url:
        return None
    return CommerceRepository(commerce_database_url)


def _configured_policy_response_provider() -> PolicyAnswerProvider | None:
    """Opt into a cached, local-only answer model through explicit config."""

    model_name = os.getenv("RESOLVEAI_LOCAL_POLICY_MODEL", "").strip()
    if not model_name:
        return None
    timeout_value = os.getenv(
        "RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS",
        "8",
    )
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ValueError("RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS must be numeric") from error
    return LocalTransformersPolicyAnswerProvider(
        model_name,
        timeout_seconds=timeout_seconds,
    )


class _RefundDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


def create_app(
    database_url: str | None = None,
    *,
    policy_retriever: PolicyRetriever | None = None,
    response_provider: PolicyAnswerProvider | None = None,
    investigation_model: InvestigationModel | None = None,
    commerce_repository: CommerceRepository | None = None,
) -> FastAPI:
    """Create an API application with configurable local conversation storage."""

    app = FastAPI()
    configured_origins = os.getenv(
        "RESOLVEAI_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    allowed_origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = new_correlation_id(request.headers.get("X-Request-ID"))
        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers["X-Request-ID"] = correlation_id
        return response

    @app.get("/healthz")
    async def healthcheck():
        """Process health without exposing configuration or dependency details."""

        return {"status": "ok"}

    configured_database_url = database_url or os.getenv(
        "RESOLVEAI_DATABASE_URL", "sqlite+pysqlite:///:memory:"
    )
    configured_policy_retriever = (
        policy_retriever
        if policy_retriever is not None
        else _configured_policy_retriever(configured_database_url)
    )
    configured_commerce_repository = (
        commerce_repository
        if commerce_repository is not None
        else _configured_commerce_repository()
    )
    configured_response_provider = (
        response_provider
        if response_provider is not None
        else _configured_policy_response_provider()
    )
    service = InMemoryResolveService(
        configured_database_url,
        policy_retriever=configured_policy_retriever,
        response_provider=configured_response_provider,
        investigation_model=investigation_model,
        commerce_repository=configured_commerce_repository,
    )
    app.state.service = service
    app.state.policy_retriever = configured_policy_retriever
    app.state.response_provider = configured_response_provider
    app.state.commerce_repository = configured_commerce_repository

    @app.get("/readyz")
    async def readinesscheck():
        """Report dependency readiness with a stable, non-sensitive response."""

        if service.database_ready():
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    router = APIRouter(prefix="/api/v1")

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        path = request.url.path
        if path.endswith("/auth/demo-login") and any(
            error.get("loc", ())[-1:] == ("demo_actor_id",) for error in errors
        ):
            return _error(
                422,
                "invalid_demo_actor",
                "The requested demo actor is not available.",
            )
        if path.endswith("/messages") and any(
            error.get("loc", ())[-1:] == ("content",)
            and error.get("type") in {"missing", "string_too_short", "string_type"}
            for error in errors
        ):
            return _error(422, "message_required", "A message is required.")
        return _error(422, "validation_error", "Request validation failed.")

    def current_actor(authorization: str | None):
        return service.actor_for_session(_bearer_token(authorization))

    @router.post("/auth/demo-login", response_model=DemoLoginResponse)
    async def demo_login(request: DemoLoginRequest):
        response = service.demo_login(request.demo_actor_id)
        if response is None:
            return _error(
                422,
                "invalid_demo_actor",
                "The requested demo actor is not available.",
            )
        return response

    @router.get("/me")
    async def get_me(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        return actor

    @router.get("/orders/{order_id}", response_model=OrderSummary)
    async def get_order(order_id: str, authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        order = service.order_for_actor(order_id, actor)
        if order is None:
            return _error(404, "order_not_found", "The requested order was not found.")
        return order

    @router.post("/conversations", response_model=ConversationSummary, status_code=201)
    async def create_conversation(
        request: CreateConversationRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            conversation = service.create_conversation(request, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        if conversation is None:
            return _error(404, "order_not_found", "The requested order was not found.")
        return conversation

    @router.post(
        "/conversations/{conversation_id}/messages",
        response_model=AppendMessageResponse,
        status_code=201,
    )
    async def append_message(
        conversation_id: str,
        request: AppendMessageRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if not request.content.strip():
            return _error(422, "message_required", "A message is required.")
        try:
            response = service.append_message(conversation_id, request.content, actor)
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        if response is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return response

    @router.post(
        "/conversations/{conversation_id}/handoff",
        response_model=ConversationSummary,
    )
    async def handoff_conversation(
        conversation_id: str, authorization: str | None = Header(default=None)
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            conversation = service.handoff(conversation_id, actor)
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        if conversation is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return conversation

    @router.get("/support/inbox", response_model=SupportInboxResponse)
    async def support_inbox(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            return service.support_inbox(actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))

    @router.post(
        "/support/conversations/{conversation_id}/claim",
        response_model=SupportConversationSummary,
    )
    async def claim_conversation(
        conversation_id: str, authorization: str | None = Header(default=None)
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            conversation = service.claim(conversation_id, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        if conversation is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return conversation

    @router.post(
        "/support/conversations/{conversation_id}/messages",
        response_model=AppendMessageResponse,
        status_code=201,
    )
    async def append_staff_message(
        conversation_id: str,
        request: AppendMessageRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if not request.content.strip():
            return _error(422, "message_required", "A message is required.")
        try:
            response = service.append_staff_message(conversation_id, request.content, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        if response is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return response

    @router.post(
        "/support/conversations/{conversation_id}/resolve",
        response_model=SupportConversationSummary,
    )
    async def resolve_conversation(
        conversation_id: str, authorization: str | None = Header(default=None)
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            conversation = service.resolve(conversation_id, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        if conversation is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return conversation

    @router.post(
        "/support/conversations/{conversation_id}/refunds",
        response_model=RefundSummary,
        status_code=201,
    )
    async def create_refund(
        conversation_id: str,
        request: CreateRefundRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            result = service.create_refund(conversation_id, request, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except ConversationStateConflict as exc:
            return _error(409, "conversation_state_conflict", str(exc))
        except IdempotencyConflict as exc:
            return _error(409, "idempotency_conflict", str(exc))
        except RefundValidationError as exc:
            return _error(422, "refund_validation_error", str(exc))
        if result is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation or linked order was not found.",
            )
        refund, created = result
        if not created:
            return JSONResponse(
                status_code=200,
                content=refund.model_dump(mode="json"),
            )
        return refund

    @router.get("/refunds", response_model=RefundListResponse)
    async def list_refunds(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            return service.list_refunds(actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))

    async def _decide_refund(
        refund_id: str,
        decision: str,
        body: _RefundDecisionRequest | None,
        authorization: str | None,
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            refund = service.decide_refund(
                refund_id,
                actor=actor,
                decision=decision,
                note=None if body is None else body.note,
            )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except ConversationStateConflict as exc:
            return _error(409, "refund_state_conflict", str(exc))
        except RefundValidationError as exc:
            return _error(422, "refund_validation_error", str(exc))
        if refund is None:
            return _error(404, "refund_not_found", "The requested refund was not found.")
        return refund

    @router.post("/refunds/{refund_id}/approve", response_model=RefundSummary)
    async def approve_refund(
        refund_id: str,
        body: _RefundDecisionRequest | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ):
        return await _decide_refund(refund_id, "approve", body, authorization)

    @router.post("/refunds/{refund_id}/reject", response_model=RefundSummary)
    async def reject_refund(
        refund_id: str,
        body: _RefundDecisionRequest | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ):
        return await _decide_refund(refund_id, "reject", body, authorization)

    @router.get("/conversations/{conversation_id}", response_model=ConversationSummary)
    async def get_conversation(
        conversation_id: str, authorization: str | None = Header(default=None)
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        conversation = service.conversation_for_actor(conversation_id, actor)
        if conversation is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return conversation

    app.include_router(router)
    return app
