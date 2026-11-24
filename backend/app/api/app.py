"""Testable FastAPI routes for the deterministic M1 API slice."""

from datetime import datetime, timedelta, timezone
from contextvars import ContextVar
import hmac
import secrets
from typing import Awaitable, Callable, Literal

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from backend.app.contracts import (
    AppendMessageRequest,
    AppendMessageResponse,
    ActorSummary,
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
from backend.app.config import (
    ResolveAISettings,
    get_settings,
    validate_trusted_origins,
)
from backend.app.ai.answer import PolicyRetriever
from backend.app.ai.generation import PolicyAnswerProvider
from backend.app.ai.investigation import InvestigationModel
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.ai.model_control import (
    AdaptiveModelRouter,
    ModelRegistry,
    QuotaLedger,
    QuotaUnavailable,
    QuotaScopeConfig,
)
from backend.app.ai.provider_adapters import (
    ProviderConfigurationError,
    RoutedPolicyAnswerProvider,
    build_provider_adapter,
)
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
    PolicyConflict,
    PolicyValidationError,
    RefundValidationError,
)
from backend.app.services.auth import (
    AdmissionLimiter,
    AuthConfigurationError,
    AuthStateUnavailable,
    AuthSessionStore,
    client_ip,
    is_postgresql_url,
    load_provisioned_accounts,
    parse_trusted_proxy_networks,
)
from backend.app.db.policies import PolicyIndexUpdateError, PolicyIndexUpdater
from backend.app.db.conversations import SUPPORTED_ALEMBIC_HEAD
from backend.app.services.policy_management import PolicyManagementService
from backend.app.api.staff_models import (
    CreatePolicyRequest,
    EditPolicyRequest,
    OperationsSummaryResponse,
    PolicyAuditListResponse,
    PolicyAuditResponse,
    PolicyDocumentResponse,
    PolicyListResponse,
    PolicySectionResponse,
    PolicyValidationResponse,
    PolicyVersionResponse,
    PolicyVersionsResponse,
    RollbackPolicyRequest,
    WorkspaceSettingsResponse,
    WorkspaceTeamResponse,
)
from backend.app.rag.corpus import get_policy_corpus
from backend.app.rag.pgvector_store import ManagedPolicyIndexUpdater, PgVectorPolicyRetriever
from backend.app.rag.semantic import SentenceTransformerEmbeddingProvider
from backend.app.commerce import CommerceRepository


UNAUTHENTICATED = {
    "code": "unauthenticated",
    "message": "Authentication is required.",
    "details": {},
}
_request_context: ContextVar[Request | None] = ContextVar("resolveai_request", default=None)


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


def _configured_policy_components(
    database_url: str,
    settings: ResolveAISettings | None = None,
) -> tuple[PolicyRetriever, PolicyIndexUpdater] | None:
    """Configure one shared local embedding provider for retrieval and indexing."""

    settings = settings or get_settings()
    if settings.policy_retrieval.casefold() != "semantic":
        return None
    if not database_url.startswith(("postgresql", "postgres")):
        return None
    provider = SentenceTransformerEmbeddingProvider(
        model_name=settings.sentence_transformer_model,
        local_files_only=True,
    )
    return (
        PgVectorPolicyRetriever(database_url, provider),
        ManagedPolicyIndexUpdater(database_url, provider),
    )


def _configured_policy_retriever(database_url: str) -> PolicyRetriever | None:
    """Opt into local semantic retrieval only for an explicitly configured PG app."""

    components = _configured_policy_components(database_url)
    return components[0] if components is not None else None


def _configured_commerce_repository(
    settings: ResolveAISettings | None = None,
) -> CommerceRepository | None:
    """Enable imported orders only through an explicit local database URL."""

    commerce_database_url = (settings or get_settings()).commerce_database_url
    if not commerce_database_url:
        return None
    return CommerceRepository(commerce_database_url)


def _configured_policy_response_provider() -> PolicyAnswerProvider | None:
    """Select an explicitly configured local or qualified external provider."""

    settings = get_settings()
    model_name = settings.local_policy_model.strip()
    if not model_name:
        return _configured_external_policy_response_provider(settings)
    return LocalTransformersPolicyAnswerProvider(
        model_name,
        timeout_seconds=settings.local_policy_timeout_seconds,
        max_new_tokens=settings.local_policy_max_new_tokens,
    )


def _configured_external_policy_response_provider(
    settings: ResolveAISettings,
) -> PolicyAnswerProvider | None:
    """Build the external data plane only from active, persisted model gates.

    This function is deliberately fail-closed.  It does not discover, qualify,
    activate, or call a provider; all of those operations must be completed by
    explicit control-plane workflows before an adapter can be routed.
    """

    if (
        not settings.external_inference_enabled
        or settings.zero_cost_mode
        or settings.evaluation_enabled
        or settings.provider_request_quota <= 0
        or settings.provider_token_quota <= 0
    ):
        return None
    database_url = settings.database_url
    if not database_url or not database_url.startswith(("postgresql", "postgres")):
        return None
    try:
        registry = ModelRegistry(database_url, initialize_schema=False)
        quota = QuotaLedger(database_url)
        models = registry.list()
        if not models:
            return None
        reset_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.provider_quota_window_seconds
        )
        scopes: dict[str, QuotaScopeConfig] = {}
        for model in models:
            for scope_key, provider in (
                (model.quota_scope, model.provider),
                (f"account:{model.provider}", model.provider),
            ):
                candidate = QuotaScopeConfig(
                    scope_key=scope_key,
                    provider=provider,
                    request_limit=settings.provider_request_quota,
                    token_limit=settings.provider_token_quota,
                    concurrency_limit=settings.provider_max_concurrency,
                    window_seconds=settings.provider_quota_window_seconds,
                    reset_at=reset_at,
                )
                previous = scopes.get(scope_key)
                if previous is not None and previous.provider != candidate.provider:
                    raise ValueError("one quota scope cannot represent multiple providers")
                scopes[scope_key] = candidate
        quota.ensure_scopes(*scopes.values())
        adapters = {}
        for model in registry.list():
            try:
                adapters[model.model_key] = build_provider_adapter(
                    model.provider,
                    model.model_id,
                    settings,
                    modelscope_base_url=settings.modelscope_base_url,
                )
            except ProviderConfigurationError:
                continue
        if not adapters:
            return None
        return RoutedPolicyAnswerProvider(
            AdaptiveModelRouter(registry, quota, account_scope_prefix="account:"),
            adapters,
            estimated_tokens=min(settings.local_policy_max_new_tokens, 256),
            deadline_ms=settings.provider_timeout_seconds * 1000,
        )
    except (QuotaUnavailable, SQLAlchemyError, OSError, ValueError):
        # Startup and local deterministic operation must not depend on a live
        # provider or an unavailable optional registry database.
        return None


def _policy_response(record) -> PolicySectionResponse:
    return PolicySectionResponse(
        document_id=record.document_id,
        document_version=record.document_version,
        section=record.section,
        release_id=record.release_id,
        status=record.status,
        visibility=record.visibility,
        text=record.text,
    )


def _managed_policy_status(state: str) -> str:
    """Keep the legacy catalog's lowercase status while exposing canonical state."""

    return {
        "DRAFT": "draft",
        "INDEXING": "indexing",
        "READY_FOR_TEST": "testable",
        "PUBLISHED": "published",
        "FAILED": "failed",
    }.get(state, state.casefold())


def _managed_policy_version_response(record) -> PolicyVersionResponse:
    from backend.app.api.staff_models import PolicySectionInput

    return PolicyVersionResponse(
        version_id=record.version_id,
        document_id=record.document_id,
        title=record.title,
        document_version=record.document_version,
        release_id=record.release_id,
        state=record.state,
        status=_managed_policy_status(record.state),
        visibility=record.visibility,
        revision=record.revision,
        is_active=record.is_active,
        failure_reason=record.failure_reason,
        index_state=record.index_state,
        created_at=record.created_at,
        updated_at=record.updated_at,
        effective_from=record.effective_from,
        effective_to=record.effective_to,
        sections=[PolicySectionInput(section=item.section, text=item.text) for item in record.sections],
    )


def _managed_policy_sections(record) -> list[PolicySectionResponse]:
    return [
        PolicySectionResponse(
            document_id=record.document_id,
            document_version=record.document_version,
            section=item.section,
            release_id=record.release_id,
            status=_managed_policy_status(record.state),
            visibility=record.visibility,
            text=item.text,
            version_id=record.version_id,
            title=record.title,
            state=record.state,
            revision=record.revision,
            is_active=record.is_active,
            failure_reason=record.failure_reason,
            updated_at=record.updated_at,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
        )
        for item in record.sections
    ]


def _matching_policy_records(
    *,
    query: str | None,
    status: str | None,
    visibility: str | None,
):
    normalized_query = (query or "").strip().casefold()
    query_terms = normalized_query.split()
    records = []
    for record in get_policy_corpus():
        if status is not None and record.status != status:
            continue
        if visibility is not None and record.visibility != visibility:
            continue
        searchable = " ".join(
            (
                record.document_id,
                record.document_version,
                record.section,
                record.release_id,
                record.text,
            )
        ).casefold()
        if query_terms and not all(term in searchable for term in query_terms):
            continue
        records.append(record)
    return sorted(
        records,
        key=lambda record: (
            record.document_id,
            record.document_version,
            record.section,
        ),
    )


class _RefundDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class _PolicyRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)


class _ProductionLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class _ProductionLoginResponse(BaseModel):
    actor: ActorSummary
    # This is a CSRF nonce, not an authentication credential.  Returning it
    # allows a separately hosted frontend to submit the header even though the
    # API-domain CSRF cookie is intentionally host-only.
    csrf_token: str


def create_app(
    database_url: str | None = None,
    *,
    policy_retriever: PolicyRetriever | None = None,
    response_provider: PolicyAnswerProvider | None = None,
    investigation_model: InvestigationModel | None = None,
    commerce_repository: CommerceRepository | None = None,
    policy_index_updater: PolicyIndexUpdater | None = None,
    settings: ResolveAISettings | None = None,
) -> FastAPI:
    """Create an API application with configurable local conversation storage."""

    settings = settings or get_settings()
    production_environment = settings.environment.casefold() == "production"
    configured_origins = settings.cors_origins
    validate_trusted_origins(configured_origins, environment=settings.environment)
    allowed_origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    app = FastAPI(
        docs_url=None if production_environment else "/docs",
        redoc_url=None if production_environment else "/redoc",
        openapi_url=None if production_environment else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
            "X-CSRF-Token",
        ],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = new_correlation_id(request.headers.get("X-Request-ID"))
        token = set_correlation_id(correlation_id)
        request_token = _request_context.set(request)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
            _request_context.reset(request_token)
        response.headers["X-Request-ID"] = correlation_id
        return response

    @app.get("/healthz")
    async def healthcheck():
        """Process health without exposing configuration or dependency details."""

        return {"status": "ok"}

    configured_database_url = database_url or settings.database_url or "sqlite+pysqlite:///:memory:"
    if production_environment:
        if settings.demo_auth_enabled:
            raise ValueError(
                "production requires RESOLVEAI_DEMO_AUTH_ENABLED=false; "
                "demo authentication is synthetic-only"
            )
        if not settings.production_auth_enabled:
            raise ValueError("production requires RESOLVEAI_PRODUCTION_AUTH_ENABLED=true")
        if settings.supported_alembic_head != SUPPORTED_ALEMBIC_HEAD:
            raise ValueError("RESOLVEAI_SUPPORTED_ALEMBIC_HEAD must match the code-supported head")
        if not is_postgresql_url(configured_database_url):
            raise ValueError("production requires the application database to use PostgreSQL")
    configured_policy_retriever = policy_retriever
    configured_policy_index_updater = policy_index_updater
    if configured_policy_retriever is None and configured_policy_index_updater is None:
        configured_components = _configured_policy_components(configured_database_url, settings)
        if configured_components is not None:
            configured_policy_retriever, configured_policy_index_updater = configured_components
    elif configured_policy_retriever is None:
        configured_policy_retriever = _configured_policy_retriever(configured_database_url)
    configured_commerce_repository = (
        commerce_repository
        if commerce_repository is not None
        else _configured_commerce_repository(settings)
    )
    if production_environment and configured_commerce_repository is None:
        raise ValueError(
            "production requires RESOLVEAI_COMMERCE_DATABASE_URL; "
            "synthetic order fixtures are local-only"
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
        policy_index_updater=configured_policy_index_updater,
        session_ttl_seconds=settings.demo_session_ttl_seconds,
        expected_alembic_head=settings.supported_alembic_head,
    )
    production_auth: AuthSessionStore | None = None
    if settings.production_auth_enabled:
        try:
            provisioned_accounts = load_provisioned_accounts(
                None
                if settings.production_auth_users_json is None
                else settings.production_auth_users_json.get_secret_value()
            )
            if not provisioned_accounts:
                raise AuthConfigurationError(
                    "production authentication requires at least one provisioned account"
                )
            production_auth = AuthSessionStore(
                provisioned_accounts,
                secret_key=(
                    ""
                    if settings.auth_secret_key is None
                    else settings.auth_secret_key.get_secret_value()
                ),
                ttl_seconds=settings.production_session_ttl_seconds,
                database_url=configured_database_url,
            )
        except AuthConfigurationError:
            # A production configuration error must fail startup rather than
            # silently falling back to synthetic authentication.
            raise
    # Durable admission state is a production-auth boundary.  Synthetic demo
    # logins intentionally remain per-process so a persistent PostgreSQL test
    # database cannot consume the local demo window across independent test
    # applications or leak admission state between synthetic runs.
    durable_auth_database_url = (
        configured_database_url
        if production_auth is not None and is_postgresql_url(configured_database_url)
        else None
    )
    login_limiter = AdmissionLimiter(
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
        database_url=durable_auth_database_url,
    )
    request_limiter = AdmissionLimiter(
        limit=settings.request_rate_limit,
        window_seconds=settings.request_rate_window_seconds,
        database_url=durable_auth_database_url,
    )
    trusted_proxy_networks = parse_trusted_proxy_networks(settings.trusted_proxy_ips)
    policy_management = PolicyManagementService(repository=service.policy_repository)
    app.state.service = service
    app.state.policy_retriever = configured_policy_retriever
    app.state.response_provider = configured_response_provider
    app.state.commerce_repository = configured_commerce_repository
    app.state.production_auth = production_auth

    def _request_ip(request: Request) -> str:
        return client_ip(
            remote=None if request.client is None else request.client.host,
            forwarded_for=request.headers.get("X-Forwarded-For"),
            trusted_networks=trusted_proxy_networks,
        )

    def _production_token(request: Request) -> str | None:
        return _bearer_token(request.headers.get("Authorization")) or request.cookies.get(
            settings.auth_cookie_name
        )

    def _actor_for_request(request: Request) -> ActorSummary | None:
        token = _production_token(request)
        if production_auth is not None:
            try:
                actor = production_auth.actor_for_session(token)
            except AuthStateUnavailable:
                # Readiness and every protected path fail closed while managed
                # auth schema is unavailable or has not reached its head.
                return None
            if actor is not None:
                return actor
        return service.actor_for_session(_bearer_token(request.headers.get("Authorization")))

    def _rate_limit_response(retry_after: int) -> JSONResponse:
        response = _error(429, "rate_limited", "Too many requests. Please retry later.")
        response.headers["Retry-After"] = str(max(1, retry_after))
        return response

    def _check_login_admission(request: Request | None, username: str) -> JSONResponse | None:
        if request is None:
            return _error(500, "authentication_unavailable", "Authentication is unavailable.")
        try:
            result = login_limiter.check(
                (
                    f"ip:{_request_ip(request)}",
                    f"username:{username.strip().casefold()[:128]}",
                )
            )
        except AuthStateUnavailable:
            return _error(
                503,
                "authentication_unavailable",
                "Authentication is unavailable.",
            )
        return None if result.allowed else _rate_limit_response(result.retry_after_seconds)

    @app.middleware("http")
    async def admission_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and path not in {"/api/v1/auth/demo-login", "/api/v1/auth/login"}
        ):
            actor = _actor_for_request(request)
            keys = [f"ip:{_request_ip(request)}"]
            if actor is not None:
                keys.append(f"actor:{actor.actor_id}")
            try:
                result = request_limiter.check(keys)
            except AuthStateUnavailable:
                return _error(
                    503,
                    "request_admission_unavailable",
                    "Request admission is unavailable.",
                )
            if not result.allowed:
                return _rate_limit_response(result.retry_after_seconds)
        return await call_next(request)

    @app.middleware("http")
    async def csrf_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cookie_token = request.cookies.get(settings.auth_cookie_name)
        if (
            production_auth is not None
            and cookie_token
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path not in {"/api/v1/auth/login", "/api/v1/auth/demo-login"}
            and (
                not request.cookies.get(settings.csrf_cookie_name)
                or not request.headers.get("X-CSRF-Token")
                or not hmac.compare_digest(
                    request.cookies.get(settings.csrf_cookie_name, "").encode("utf-8"),
                    request.headers.get("X-CSRF-Token", "").encode("utf-8"),
                )
            )
        ):
            return _error(403, "csrf_required", "A CSRF token is required.")
        return await call_next(request)

    @app.middleware("http")
    async def sanitized_error_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Keep unexpected route and middleware failures out of API responses."""

        try:
            return await call_next(request)
        except Exception:
            return _error(500, "internal_error", "An internal server error occurred.")

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
        # Authentication takes precedence over body validation on the
        # protected knowledge-management surface.  This preserves the API's
        # 401 contract even when an unauthenticated caller sends malformed
        # mutation input, without revealing policy details.
        if path.startswith("/api/v1/knowledge/policies") and _bearer_token(
            request.headers.get("Authorization")
        ) is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
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
        request = _request_context.get()
        if production_auth is not None and request is not None:
            token = _bearer_token(authorization) or request.cookies.get(settings.auth_cookie_name)
            try:
                actor = production_auth.actor_for_session(token)
            except AuthStateUnavailable:
                return None
            if actor is not None:
                return actor
        return service.actor_for_session(_bearer_token(authorization))

    def _set_auth_cookies(response: Response, token: str) -> str:
        secure = settings.environment.casefold() not in {"local", "development", "test"}
        same_site = "none" if secure else "lax"
        csrf_token = secrets.token_urlsafe(24)
        response.set_cookie(
            settings.auth_cookie_name,
            token,
            max_age=settings.production_session_ttl_seconds,
            httponly=True,
            secure=secure,
            samesite=same_site,
            path="/",
        )
        response.set_cookie(
            settings.csrf_cookie_name,
            csrf_token,
            max_age=settings.production_session_ttl_seconds,
            httponly=False,
            secure=secure,
            samesite=same_site,
            path="/",
        )
        return csrf_token

    def _clear_auth_cookies(response: Response) -> None:
        response.delete_cookie(settings.auth_cookie_name, path="/")
        response.delete_cookie(settings.csrf_cookie_name, path="/")

    @router.post("/auth/demo-login", response_model=DemoLoginResponse)
    async def demo_login(request: DemoLoginRequest):
        if not settings.demo_auth_enabled:
            return _error(404, "not_found", "The requested resource was not found.")
        admission = _check_login_admission(_request_context.get(), request.demo_actor_id)
        if admission is not None:
            return admission
        response = service.demo_login(request.demo_actor_id)
        if response is None:
            return _error(
                422,
                "invalid_demo_actor",
                "The requested demo actor is not available.",
            )
        return response

    @router.post("/auth/login", response_model=_ProductionLoginResponse)
    async def production_login(
        request: _ProductionLoginRequest,
        response: Response,
    ):
        if production_auth is None:
            return _error(404, "not_found", "The requested resource was not found.")
        http_request = _request_context.get()
        if http_request is None:
            return _error(500, "authentication_unavailable", "Authentication is unavailable.")
        admission = _check_login_admission(http_request, request.username)
        if admission is not None:
            return admission
        try:
            credentials = production_auth.login(request.username, request.password)
        except AuthStateUnavailable:
            return _error(
                503,
                "authentication_unavailable",
                "Authentication is unavailable.",
            )
        if credentials is None:
            return _error(401, "invalid_credentials", "Invalid username or password.")
        token, actor = credentials
        csrf_token = _set_auth_cookies(response, token)
        return _ProductionLoginResponse(actor=actor, csrf_token=csrf_token)

    @router.post("/auth/logout", status_code=204)
    async def logout(
        response: Response,
        authorization: str | None = Header(default=None),
    ):
        request = _request_context.get()
        production_token = (
            _bearer_token(authorization)
            or (None if request is None else request.cookies.get(settings.auth_cookie_name))
        )
        try:
            production_logged_out = (
                production_auth is not None and production_auth.revoke(production_token)
            )
        except AuthStateUnavailable:
            return _error(
                503,
                "authentication_unavailable",
                "Authentication is unavailable.",
            )
        demo_logged_out = service.logout(_bearer_token(authorization))
        if not production_logged_out and not demo_logged_out:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        _clear_auth_cookies(response)
        response.status_code = 204
        return response

    @router.get("/me")
    async def get_me(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        return actor

    @router.get("/ops/summary", response_model=OperationsSummaryResponse)
    async def operations_summary(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            return service.operations_summary(actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))

    @router.get("/knowledge/policies", response_model=PolicyListResponse)
    async def list_knowledge_policies(
        q: str | None = Query(default=None, max_length=200),
        status: str | None = Query(default=None, max_length=32),
        visibility: Literal["public", "internal"] | None = None,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if actor.role not in {"support_agent", "refund_approver", "merchant_admin"}:
            return _error(403, "forbidden", "knowledge access requires a staff role")
        records = _matching_policy_records(
            query=q,
            status=status if status in {"draft", "unpublished", "published"} else None,
            visibility=visibility,
        )
        managed = service.policy_repository.list(
            query=q,
            state={
                "draft": "DRAFT",
                "indexing": "INDEXING",
                "testable": "READY_FOR_TEST",
                "ready_for_test": "READY_FOR_TEST",
                "published": "PUBLISHED",
                "failed": "FAILED",
            }.get((status or "").casefold()),
            visibility=visibility,
        )
        if status == "unpublished":
            managed = [item for item in managed if not item.is_active and item.state != "PUBLISHED"]
        managed_keys = {(item.document_id, item.document_version) for item in managed}
        records = [
            _policy_response(record)
            for record in records
            if (record.document_id, record.document_version) not in managed_keys
        ]
        for item in managed:
            records.extend(_managed_policy_sections(item))
        return PolicyListResponse(
            policies=records
        )

    @router.get(
        "/knowledge/policies/{document_id}",
        response_model=PolicyDocumentResponse,
    )
    async def get_knowledge_policy(
        document_id: str,
        version: str | None = Query(default=None, min_length=1, max_length=64),
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if actor.role not in {"support_agent", "refund_approver", "merchant_admin"}:
            return _error(403, "forbidden", "knowledge access requires a staff role")
        records = [
            record
            for record in get_policy_corpus()
            if record.document_id == document_id
            and (version is None or record.document_version == version)
        ]
        managed = service.policy_repository.list(document_id=document_id)
        if version is not None:
            managed = [item for item in managed if item.document_version == version]
        if managed:
            managed_keys = {(item.document_version, section.section) for item in managed for section in item.sections}
            records = [record for record in records if (record.document_version, record.section) not in managed_keys]
        managed_sections = [section for item in managed for section in _managed_policy_sections(item)]
        if not records and not managed_sections:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        records.sort(key=lambda record: (record.document_version, record.section))
        return PolicyDocumentResponse(
            document_id=document_id,
            policies=[_policy_response(record) for record in records] + managed_sections,
        )

    @app.post(
        "/api/v1/knowledge/policies",
        response_model=PolicyVersionResponse,
        status_code=201,
    )
    async def create_knowledge_policy(
        request: CreatePolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            if request.release_id is not None:
                record = policy_management.create_draft(
                    actor,
                    document_id=request.document_id,
                    document_version=request.document_version,
                    release_id=request.release_id,
                    title=request.title,
                    visibility=request.visibility,
                    sections=request.sections,
                )
            else:
                record = service.create_policy(
                    actor=actor,
                    document_id=request.document_id,
                    title=request.title or request.document_id,
                    document_version=request.document_version,
                    visibility=request.visibility,
                    sections=[item.model_dump() for item in request.sections],
                )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except PermissionError as exc:
            return _error(403, "forbidden", str(exc))
        except PolicyConflict as exc:
            return _error(409, "policy_conflict", str(exc))
        except PolicyValidationError as exc:
            return _error(422, "policy_validation_error", str(exc))
        return _managed_policy_version_response(record)

    @app.patch(
        "/api/v1/knowledge/policies/{version_id}",
        response_model=PolicyVersionResponse,
    )
    async def edit_knowledge_policy(
        version_id: str,
        request: EditPolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            record = service.edit_policy(
                version_id,
                actor=actor,
                expected_revision=request.expected_revision,
                title=request.title,
                release_id=request.release_id,
                visibility=request.visibility,
                sections=None if request.sections is None else [item.model_dump() for item in request.sections],
            )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return _error(409, "policy_conflict", str(exc))
        except PolicyValidationError as exc:
            return _error(422, "policy_validation_error", str(exc))
        return _managed_policy_version_response(record)

    @app.post(
        "/api/v1/knowledge/policies/{version_id}/validate",
        response_model=PolicyValidationResponse,
    )
    async def validate_knowledge_policy(
        version_id: str,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            record, errors = service.validate_policy(version_id, actor=actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        return PolicyValidationResponse(valid=not errors, errors=errors, state=record.state, revision=record.revision)

    @app.post(
        "/api/v1/knowledge/policies/{version_id}/index",
        response_model=PolicyVersionResponse,
        status_code=200,
    )
    async def index_knowledge_policy(
        version_id: str,
        body: _PolicyRevisionRequest | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            record = service.index_policy(
                version_id,
                actor=actor,
                expected_revision=None if body is None else body.expected_revision,
            )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return _error(409, "policy_conflict", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @app.post(
        "/api/v1/knowledge/policies/{version_id}/publish",
        response_model=PolicyVersionResponse,
    )
    async def publish_knowledge_policy(
        version_id: str,
        body: _PolicyRevisionRequest | None = Body(default=None),
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            record = service.publish_policy(
                version_id,
                actor=actor,
                expected_revision=None if body is None else body.expected_revision,
                idempotency_key=idempotency_key,
            )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return _error(409, "policy_conflict", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @app.get(
        "/api/v1/knowledge/policies/{document_id}/versions",
        response_model=PolicyVersionsResponse,
    )
    async def list_policy_versions(
        document_id: str,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            versions = service.policy_versions(document_id, actor=actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        return PolicyVersionsResponse(versions=[_managed_policy_version_response(item) for item in versions])

    @app.post(
        "/api/v1/knowledge/policies/{document_id}/rollback",
        response_model=PolicyVersionResponse,
    )
    async def rollback_knowledge_policy(
        document_id: str,
        request: RollbackPolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            target_version = request.target_version or request.document_version
            if target_version is None:
                return _error(422, "validation_error", "document_version is required")
            record = service.rollback_policy(
                document_id,
                target_version,
                actor=actor,
                expected_revision=request.expected_revision,
            )
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return _error(409, "policy_conflict", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @app.get(
        "/api/v1/knowledge/audit",
        response_model=PolicyAuditListResponse,
    )
    async def list_policy_audit(
        document_id: str | None = Query(default=None, max_length=128),
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            events = service.policy_audit(actor=actor, document_id=document_id)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        return PolicyAuditListResponse(events=[PolicyAuditResponse(**event.__dict__) for event in events])

    @app.get(
        "/api/v1/knowledge/policies/{version_id}/audit",
        response_model=PolicyAuditListResponse,
    )
    async def list_policy_version_audit(
        version_id: str,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            events = service.policy_audit(actor=actor, version_id=version_id)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        return PolicyAuditListResponse(events=[PolicyAuditResponse(**event.__dict__) for event in events])

    @router.put("/knowledge/policies/{document_id}/{document_version}", response_model=PolicyVersionResponse)
    async def update_policy_document_version(
        document_id: str,
        document_version: str,
        request: EditPolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if request.release_id is None or request.visibility is None or request.sections is None:
            return _error(422, "validation_error", "release_id, visibility, and sections are required")
        try:
            record = policy_management.edit_draft(
                actor,
                document_id=document_id,
                document_version=document_version,
                expected_revision=request.expected_revision,
                release_id=request.release_id,
                visibility=request.visibility,
                sections=request.sections,
            )
        except PermissionError as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return JSONResponse(status_code=409, content={"error": {"code": "revision_conflict", "message": str(exc), "details": {"current_revision": exc.current_revision, "current_state": exc.current_state}}})
        except PolicyValidationError as exc:
            return _error(422, "policy_validation_error", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @router.post("/knowledge/policies/{document_id}/{document_version}/publish", response_model=PolicyVersionResponse)
    async def publish_policy_document_version(
        document_id: str,
        document_version: str,
        request: EditPolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            record = policy_management.publish(actor, document_id=document_id, document_version=document_version, expected_revision=request.expected_revision)
        except PermissionError as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return JSONResponse(status_code=409, content={"error": {"code": "revision_conflict", "message": str(exc), "details": {"current_revision": exc.current_revision, "current_state": exc.current_state}}})
        except PolicyValidationError as exc:
            return _error(422, "policy_validation_error", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @router.post("/knowledge/policies/{document_id}/{document_version}/rollback", response_model=PolicyVersionResponse)
    async def rollback_policy_document_version(
        document_id: str,
        document_version: str,
        request: RollbackPolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        target_version = request.target_version or request.document_version
        if target_version is None or request.expected_revision is None:
            return _error(422, "validation_error", "target_version and expected_revision are required")
        try:
            record = policy_management.rollback(actor, document_id=document_id, document_version=document_version, target_version=target_version, expected_revision=request.expected_revision)
        except PermissionError as exc:
            return _error(403, "forbidden", str(exc))
        except KeyError:
            return _error(404, "policy_not_found", "The requested policy was not found.")
        except PolicyConflict as exc:
            return JSONResponse(status_code=409, content={"error": {"code": "revision_conflict", "message": str(exc), "details": {"current_revision": exc.current_revision, "current_state": exc.current_state}}})
        except PolicyValidationError as exc:
            return _error(422, "policy_validation_error", str(exc))
        except PolicyIndexUpdateError as exc:
            return _error(503, "policy_index_unavailable", str(exc))
        return _managed_policy_version_response(record)

    @router.get("/knowledge/policies/{document_id}/{document_version}/audit", response_model=PolicyAuditListResponse)
    async def get_policy_document_audit(
        document_id: str,
        document_version: str,
        authorization: str | None = Header(default=None),
    ):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            events = policy_management.audit(actor, document_id=document_id, document_version=document_version)
        except PermissionError as exc:
            return _error(403, "forbidden", str(exc))
        return PolicyAuditListResponse(events=[PolicyAuditResponse(**event.__dict__) for event in events])

    @router.get("/workspace/policy-audit", response_model=PolicyAuditListResponse)
    async def workspace_policy_audit(limit: int = Query(default=50, ge=1, le=100), authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if actor.role != "merchant_admin":
            return _error(403, "forbidden", "policy audit requires merchant_admin")
        events = service.policy_repository.recent_audits(limit=limit)
        return PolicyAuditListResponse(events=[PolicyAuditResponse(**event.__dict__) for event in events])

    @router.get("/workspace/team", response_model=WorkspaceTeamResponse)
    async def workspace_team(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            return WorkspaceTeamResponse(team=service.workspace_team(actor))
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))

    @router.get("/workspace/settings", response_model=WorkspaceSettingsResponse)
    async def workspace_settings(authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        if actor.role != "merchant_admin":
            return _error(403, "forbidden", "workspace settings require merchant_admin")
        return WorkspaceSettingsResponse(
            merchant_name="ResolveAI Demo Merchant",
            policy_source="POLICY_CORPUS",
            policy_retrieval_mode=(
                "semantic" if configured_policy_retriever is not None else "lexical"
            ),
            response_generation_mode=(
                "model" if configured_response_provider is not None else "deterministic"
            ),
            database_ready=service.database_ready(),
            commerce_database_configured=configured_commerce_repository is not None,
        )

    @router.get("/support/conversations/{conversation_id}/order", response_model=OrderSummary)
    async def support_case_order(conversation_id: str, authorization: str | None = Header(default=None)):
        actor = current_actor(authorization)
        if actor is None:
            return _error(401, UNAUTHENTICATED["code"], UNAUTHENTICATED["message"])
        try:
            order = service.order_for_support_case(conversation_id, actor)
        except ForbiddenOperation as exc:
            return _error(403, "forbidden", str(exc))
        if order is None:
            return _error(404, "order_not_found", "The requested order was not found.")
        return order

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
