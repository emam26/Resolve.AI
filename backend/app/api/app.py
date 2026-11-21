"""Testable FastAPI routes for the deterministic M1 API slice."""

import os

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from backend.app.contracts import (
    AppendMessageRequest,
    AppendMessageResponse,
    ConversationSummary,
    CreateConversationRequest,
    DemoLoginRequest,
    DemoLoginResponse,
    ErrorResponse,
    OrderSummary,
)
from backend.app.services import InMemoryResolveService


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


def create_app() -> FastAPI:
    """Create an isolated API application with a fresh synthetic data store."""

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
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )
    service = InMemoryResolveService()
    app.state.service = service
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
        conversation = service.create_conversation(request, actor)
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
        response = service.append_message(conversation_id, request.content, actor)
        if response is None:
            return _error(
                404,
                "conversation_not_found",
                "The requested conversation was not found.",
            )
        return response

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
