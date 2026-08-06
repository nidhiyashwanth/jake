from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from uuid import uuid4

from app.api.routes import router
from app.api.review_routes import router as review_router
from app.api.workflow_routes import router as workflow_router
from app.api.runtime_routes import router as runtime_router
from app.api.connector_routes import router as connector_router
from app.api.compliance_routes import router as compliance_router
from app.api.confidence_routes import router as confidence_router
from app.api.evaluation_routes import router as evaluation_router
from app.api.value_routes import router as value_router
from app.api.governance_routes import router as governance_router
from app.config import get_settings
from app.errors import DomainError, domain_error_handler
from app.services.observability import capture_exception


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or f"http-{uuid4().hex}"
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
    except Exception as error:
        capture_exception(error, correlation_id=correlation_id)
        raise
    if "X-Correlation-ID" not in response.headers:
        response.headers["X-Correlation-ID"] = correlation_id
    return response


app.add_exception_handler(DomainError, domain_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = "; ".join(
        f"{'/'.join(str(part) for part in error.get('loc', []))}: {error.get('msg', 'invalid value')}"
        for error in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": details or "The request is invalid"}},
    )


app.include_router(router)
app.include_router(review_router)
app.include_router(workflow_router)
app.include_router(runtime_router)
app.include_router(connector_router)
app.include_router(compliance_router)
app.include_router(confidence_router)
app.include_router(evaluation_router)
app.include_router(value_router)
app.include_router(governance_router)
