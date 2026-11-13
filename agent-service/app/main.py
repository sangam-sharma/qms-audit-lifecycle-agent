from pathlib import Path
import os
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import AuditOrchestrator, OrchestratorError
from app.domain.schemas import (
    AuditAnalysis, AuditListItem, ErrorResponse, TaskExecutionRequest, TaskExecutionResult,
    ToolExecutionContext,
)
from app.llm.openai_compatible import configured_explainer, configured_task_planner
from app.providers.base import (
    AuditNotFound, ProviderError, ProviderForbidden, ProviderNotFound, ProviderTimeout,
    ProviderUnauthorized,
)
from app.providers.django_api import DjangoAPIProvider
from app.providers.mock_qms import MockQMSProvider


_AUTO_EXPLAINER = object()
_DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/"
_DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _cors_origins() -> list[str]:
    configured = os.getenv("AGENT_CORS_ORIGINS", "")
    if not configured.strip():
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]


def _provider_http_error(exc: ProviderError) -> HTTPException:
    code_to_status = {
        "qms_unauthorized": 401,
        "qms_forbidden": 403,
        "audit_not_found": 404,
        "qms_not_found": 404,
        "qms_timeout": 504,
        "endpoint_not_allowed": 403,
    }
    status = code_to_status.get(exc.code, 502)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.public_message})


def _orchestrator_http_error(exc: OrchestratorError) -> HTTPException:
    status = {
        "invalid_task_request": 400,
        "audit_not_found": 404,
        "qms_unauthorized": 401,
        "qms_forbidden": 403,
        "qms_not_found": 404,
        "qms_timeout": 504,
    }.get(exc.code, 502)
    # Orchestrator errors have safe, fixed messages and never include request headers.
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


def create_app(provider=None, explainer=_AUTO_EXPLAINER, task_planner=_AUTO_EXPLAINER) -> FastAPI:
    data_provider = provider or MockQMSProvider()
    mode = "django" if provider is None and os.getenv("QMS_DATA_PROVIDER", "mock").lower() == "django" else "mock"
    if provider is None and os.getenv("QMS_DATA_PROVIDER", "mock").lower() not in {"mock", "django"}:
        raise ValueError("QMS_DATA_PROVIDER must be 'mock' or 'django'")
    if mode == "mock":
        data_provider = provider or MockQMSProvider()
    chosen_explainer = configured_explainer() if explainer is _AUTO_EXPLAINER else explainer
    chosen_task_planner = configured_task_planner() if task_planner is _AUTO_EXPLAINER else task_planner
    orchestrator = AuditOrchestrator(data_provider, chosen_explainer, task_planner=chosen_task_planner)
    app = FastAPI(
        title="QMS Audit Assistant",
        version="0.2.0",
        description="Read-only audit lifecycle analysis over mock or authenticated Django QMS data.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.provider = data_provider
    app.state.orchestrator = orchestrator
    app.state.provider_mode = mode
    app.state.qms_api_base_url = os.getenv("QMS_API_BASE_URL", _DEFAULT_BASE_URL)
    app.state.explainer = chosen_explainer
    app.state.task_planner = chosen_task_planner

    async def request_orchestrator(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        if request.app.state.provider_mode == "mock":
            yield request.app.state.orchestrator
            return
        if not authorization:
            raise HTTPException(status_code=401, detail={"code": "qms_unauthorized", "message": "A QMS bearer token is required."})
        scheme, separator, jwt = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not jwt.strip():
            raise HTTPException(status_code=401, detail={"code": "qms_unauthorized", "message": "A valid QMS bearer token is required."})
        django_provider = DjangoAPIProvider(request.app.state.qms_api_base_url, jwt.strip())
        try:
            try:
                identity = django_provider.validate_identity()
            except ProviderError as exc:
                raise _provider_http_error(exc) from exc
            context = ToolExecutionContext(
                request_id=str(uuid4()),
                principal_id=str(identity["id"]),
                system_id="django",
            )
            yield AuditOrchestrator(
                django_provider, request.app.state.explainer,
                task_planner=request.app.state.task_planner, tool_context=context,
            )
        finally:
            django_provider.close()

    @app.get("/api/health")
    def health(request: Request):
        return {"status": "ok", "data_source": request.app.state.provider_mode}

    @app.get("/api/audits", response_model=list[AuditListItem])
    def list_audits(orchestrator: AuditOrchestrator = Depends(request_orchestrator)):
        try:
            return [
                AuditListItem(
                    id=audit.id, code=audit.code, project_name=audit.project_name,
                    status=audit.status, planned_start_date=audit.planned_start_date,
                    planned_end_date=audit.planned_end_date,
                )
                for audit in orchestrator.list_audits()
            ]
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc

    @app.post(
        "/api/audits/{audit_id}/analysis", response_model=AuditAnalysis,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    def analyze_audit(
        audit_id: str,
        include_explanation: bool = Query(default=True),
        current: AuditOrchestrator = Depends(request_orchestrator),
    ):
        try:
            return current.analyze(audit_id, include_explanation)
        except OrchestratorError as exc:
            raise _orchestrator_http_error(exc) from exc

    @app.post(
        "/api/tasks/execute", response_model=TaskExecutionResult,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    def execute_task(
        body: TaskExecutionRequest,
        current: AuditOrchestrator = Depends(request_orchestrator),
    ):
        try:
            return current.execute_task(body.request_text, body.include_explanation)
        except OrchestratorError as exc:
            raise _orchestrator_http_error(exc) from exc

    @app.get("/", include_in_schema=False)
    def demo():
        return FileResponse(Path(__file__).resolve().parents[1] / "demo" / "index.html")

    return app


app = create_app()
