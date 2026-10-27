from __future__ import annotations

import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import boto3
import uvicorn
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aws_inventory.config import SUPPORTED_SERVICES

from .bma import BmaError
from .config import AppSettings
from .reports import render_html, render_markdown
from .runners import LiveRunner, SampleRunner
from .store import MemoryStore, S3Store

STATIC = Path(__file__).with_name("static")


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: Annotated[str, Field(min_length=1, max_length=4000)]
    language: Literal["ko", "en"] = "ko"

    @field_validator("prompt")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Prompt must contain text.")
        return value.strip()


def create_app(settings=None, *, runner=None, store=None, aws_session=None):
    settings = settings or AppSettings.from_env()
    live = settings.inventory.mode == "live"
    aws = aws_session if aws_session is not None else (boto3.Session() if live else None)
    runner = runner or (LiveRunner(settings, aws) if live else SampleRunner(settings))
    store = store or (S3Store(settings, aws) if live else MemoryStore())
    app = FastAPI(title="AI-Powered AWS Operations Desk", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.url.path.startswith("/api/"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if settings.access_token and not hmac.compare_digest(token, settings.access_token):
                return JSONResponse({"error": "AuthenticationRequired"}, status_code=401)
            if request.method == "POST" and len(await request.body()) > 16_384:
                return JSONResponse({"error": "RequestTooLarge"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    def verify_account():
        if not live:
            return settings.inventory.expected_account_id
        try:
            identity = aws.client(
                "sts", region_name=settings.inventory.app_region,
                config=Config(connect_timeout=3, read_timeout=10,
                              retries={"mode": "standard", "total_max_attempts": 3}),
            ).get_caller_identity()
        except (BotoCoreError, ClientError):
            raise HTTPException(503, detail="AccountVerificationFailed") from None
        if identity["Account"] != settings.inventory.expected_account_id:
            raise HTTPException(409, detail="AccountMismatch") from None
        return identity["Account"]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/context")
    def context():
        return {
            "account_id": verify_account(), "app_region": settings.inventory.app_region,
            "target_region": settings.inventory.target_region, "mode": settings.inventory.mode,
            "account_source": "web_function_sts" if live else "synthetic_fixture",
            "runtime_account_verified": False,
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "supported_services": list(SUPPORTED_SERVICES),
            "lambda_scope": "event_functions_only",
            "max_resources": settings.inventory.max_resources,
            "max_metric_hours": settings.inventory.max_metric_hours,
            "model": settings.model if live else None,
        }

    @app.post("/api/chat")
    def chat(query: Query):
        verify_account()
        record = {
            "id": str(uuid.uuid4()), "prompt": query.prompt, "language": query.language, "mode": settings.inventory.mode,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        def emit(value):
            return "data: " + json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n\n"

        def stream():
            yield emit({"type": "started", **record})
            execution = runner.stream(query.prompt, language="en") if query.language == "en" else runner.stream(query.prompt)
            try:
                for event in execution:
                    if event["type"] == "result":
                        record.update({key: value for key, value in event.items() if key != "type"})
                        record["report_available"] = True
                        try:
                            store.put(record)
                        except (BotoCoreError, ClientError, ValueError):
                            record["report_available"] = False
                            record["errors"].append("ReportPersistenceFailed")
                            record["status"] = "partial"
                        yield emit({"type": "complete", **record})
                    else:
                        yield emit(event)
            except (BmaError, BotoCoreError, ClientError, ValueError) as error:
                code = error.code if isinstance(error, BmaError) else "AppExecutionError"
                yield emit({"type": "error", "code": code, "id": record["id"]})
            finally:
                execution.close()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.get("/api/runs/{run_id}/report.{format}")
    def report(run_id: str, format: str):
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError
        except ValueError:
            raise HTTPException(404) from None
        if format not in {"md", "html"}:
            raise HTTPException(404)
        try:
            record = store.get(run_id)
        except (BotoCoreError, ClientError, ValueError):
            raise HTTPException(503, detail="ReportReadFailed") from None
        if record is None:
            raise HTTPException(404)
        body = render_html(record) if format == "html" else render_markdown(record)
        return Response(
            body, media_type="text/html" if format == "html" else "text/markdown",
            headers={"Content-Disposition": f'attachment; filename="aws-report-{run_id}.{format}"'},
        )

    return app


def main():
    endpoint = os.getenv("AWS_LAMBDA_HTTP_ENDPOINT", "127.0.0.1:3000")
    parsed = urlparse(endpoint if "://" in endpoint else "http://" + endpoint)
    if not parsed.hostname or not parsed.port:
        raise ValueError("AWS_LAMBDA_HTTP_ENDPOINT must contain host and port.")
    uvicorn.run(create_app(), host=parsed.hostname, port=parsed.port, access_log=False)


if __name__ == "__main__":
    main()
