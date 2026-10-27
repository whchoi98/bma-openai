"""A fixed-job, fixed-account document runtime with a deliberately small API."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .input_data import MAX_TEXT_CHARACTERS, MAX_UPLOAD_BYTES, aggregate_chart, inspect_source, source_profile
from .render import render_chart, render_diagram, render_documents

REGION = "us-east-1"
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 30 * 1024 * 1024
MAX_VISUAL_ASSETS = 6
MAX_MANIFEST_BYTES = 3 * 1024 * 1024
MAX_INPUT_MANIFEST_BYTES = 256 * 1024
MAX_TABLE_RESPONSE_BYTES = 64 * 1024
MIME = {
    "png": "image/png", "svg": "image/svg+xml", "html": "text/html",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_FILE = re.compile(r"^[a-z][a-z0-9_-]{0,79}\.(png|svg|pptx|docx|html)$")
_ASSET = re.compile(r"^(chart|diagram)_[1-6]$")
_ARTIFACT = re.compile(r"^(?:chart_[1-6]|diagram_[1-6]|documents)_(?:png|svg|pptx|docx|html)$")
_HASH = re.compile(r"^[a-f0-9]{64}$")

Title = Annotated[str, Field(min_length=1, max_length=180)]
SheetId = Annotated[str, Field(pattern=r"^sheet_[0-4]$")]
ColumnId = Annotated[str, Field(pattern=r"^c(?:[0-9]|[1-4][0-9])$")]
NodeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyArgs(StrictModel):
    pass


class ReadTableArgs(StrictModel):
    sheet_id: SheetId
    offset: Annotated[int, Field(ge=0, le=10000)] = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 20


class ReadTextArgs(StrictModel):
    offset: Annotated[int, Field(ge=0, le=MAX_TEXT_CHARACTERS + 2)] = 0
    limit: Annotated[int, Field(ge=1, le=8000)] = 8000


class ChartArgs(StrictModel):
    title: Title
    sheet_id: SheetId
    x_column: ColumnId
    y_column: ColumnId | None = None
    aggregation: Literal["sum", "mean", "count", "none"] = "sum"
    chart_type: Literal["bar", "line", "pie", "scatter"] = "bar"
    group_by: Literal["value", "month", "year"] = "value"


class DiagramNode(StrictModel):
    id: NodeId
    label: Annotated[str, Field(min_length=1, max_length=160)]


class DiagramEdge(StrictModel):
    source: NodeId
    target: NodeId
    label: Annotated[str, Field(max_length=80)] = ""


class DiagramArgs(StrictModel):
    title: Title
    layout: Literal["flow", "hierarchy", "timeline"] = "flow"
    nodes: Annotated[list[DiagramNode], Field(min_length=1, max_length=20)]
    edges: Annotated[list[DiagramEdge], Field(max_length=30)] = Field(default_factory=list)


class DocumentSection(StrictModel):
    heading: Annotated[str, Field(min_length=1, max_length=160)]
    paragraphs: Annotated[list[Annotated[str, Field(max_length=600)]], Field(max_length=4)] = Field(default_factory=list)
    bullets: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=6)] = Field(default_factory=list)
    asset_ids: Annotated[list[NodeId], Field(max_length=2)] = Field(default_factory=list)


class DocumentArgs(StrictModel):
    title: Title
    subtitle: Annotated[str, Field(max_length=300)] = ""
    sections: Annotated[list[DocumentSection], Field(max_length=11)] = Field(default_factory=list)


class UploadManifest(StrictModel):
    id: str
    name: Annotated[str, Field(min_length=1, max_length=255)]
    size: Annotated[int, Field(ge=1, le=MAX_UPLOAD_BYTES)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        return _uuid(value)


class InputManifest(StrictModel):
    id: str
    account_id: Annotated[str, Field(pattern=r"^[0-9]{12}$")]
    app_region: Literal["us-east-1"]
    upload: UploadManifest | None = None
    notes: Annotated[str, Field(max_length=50000)] = ""
    prompt: Annotated[str, Field(min_length=1, max_length=4000)]
    outputs: Annotated[list[Literal["pptx", "docx", "chart", "diagram"]], Field(min_length=1, max_length=4)]
    style: Literal["business", "aws-desk", "presentation"]
    language: Literal["ko", "en"]
    created_at: datetime | None = None
    input_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    source_job_id: str | None = None

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Manifest creation time must include a timezone")
        return value

    @field_validator("source_job_id")
    @classmethod
    def valid_source_id(cls, value):
        return _uuid(value) if value is not None else None

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        return _uuid(value)

    @field_validator("outputs")
    @classmethod
    def unique_outputs(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Outputs must be unique")
        return value


class JobError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("Job/upload ID must be a UUID")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("Job/upload ID must be a canonical UUID")
    return value


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


class DocumentJob:
    """Own exactly one immutable input manifest and its bounded output prefix.

    All calls are serialized, including rendering and manifest publication. The
    worker must launch one runtime session for this job; cross-process writers
    are intentionally not supported.
    """

    def __init__(self, job_id, *, bucket, account_id, region=REGION, s3_client=None, sts_client=None, workdir=None):
        self.job_id = _uuid(job_id)
        if region != REGION:
            raise ValueError("Document Studio runs only in us-east-1")
        if not isinstance(account_id, str) or not re.fullmatch(r"[0-9]{12}", account_id):
            raise ValueError("A fixed expected AWS account is required")
        if not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("A fixed S3 bucket name is required")
        self.account_id, self.bucket, self.region = account_id, bucket, region
        config = Config(region_name=REGION, retries={"mode": "standard", "total_max_attempts": 3}, connect_timeout=3, read_timeout=15)
        self.s3 = s3_client if s3_client is not None else boto3.client("s3", region_name=REGION, config=config)
        self.sts = sts_client if sts_client is not None else boto3.client("sts", region_name=REGION, config=config)
        self._temporary = tempfile.TemporaryDirectory(prefix=f"studio-{self.job_id}-") if workdir is None else None
        self.root = Path(self._temporary.name if self._temporary else workdir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._loaded = False
        self._reconcile_required = False
        self.manifest = None
        self.source = None
        self.assets = {}
        self.artifacts = []
        self.warnings = []
        self._documents_created = False

    @classmethod
    def from_environment(cls, job_id):
        return cls(job_id, bucket=os.environ.get("STUDIO_BUCKET", ""), account_id=os.environ.get("EXPECTED_ACCOUNT_ID", ""), region=os.environ.get("APP_REGION", ""))

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()

    @property
    def _manifest_key(self):
        return f"jobs/{self.job_id}/artifacts.json"

    def _output_key(self, filename):
        if not isinstance(filename, str) or not _FILE.fullmatch(filename):
            raise JobError("INVALID_ARTIFACT")
        return f"jobs/{self.job_id}/outputs/{filename}"

    def _get(self, key, maximum, *, optional=False):
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key, ExpectedBucketOwner=self.account_id)
        except ClientError as exc:
            error = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if optional and (error in {"NoSuchKey", "NotFound", "404"} or status == 404):
                return None
            if optional and (error in {"AccessDenied", "403"} or status == 403):
                probe = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1, ExpectedBucketOwner=self.account_id)
                if not any(item.get("Key") == key for item in probe.get("Contents", [])):
                    return None
            raise
        body = response["Body"]
        try:
            if response.get("ContentLength", 0) > maximum:
                raise JobError("INPUT_LIMIT")
            payload = body.read(maximum + 1)
            if len(payload) > maximum:
                raise JobError("INPUT_LIMIT")
            return payload
        finally:
            body.close()

    def _put(self, key, payload, mime):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType=mime, ExpectedBucketOwner=self.account_id)

    def _ensure_loaded(self):
        if self._loaded:
            return
        identity = self.sts.get_caller_identity()
        if identity.get("Account") != self.account_id:
            raise JobError("ACCOUNT_MISMATCH")
        raw = self._get(f"jobs/{self.job_id}/input.json", MAX_INPUT_MANIFEST_BYTES)
        try:
            manifest = InputManifest.model_validate_json(raw)
        except ValidationError as exc:
            raise JobError("INVALID_INPUT_MANIFEST") from exc
        if manifest.id != self.job_id or manifest.account_id != self.account_id or manifest.app_region != self.region:
            raise JobError("INPUT_AUTHORITY_MISMATCH")
        data = None
        filename = None
        if manifest.upload:
            upload = manifest.upload
            data = self._get(f"uploads/{upload.id}/data", MAX_UPLOAD_BYTES)
            if len(data) != upload.size or hashlib.sha256(data).hexdigest() != upload.sha256:
                raise JobError("INPUT_INTEGRITY_ERROR")
            filename = upload.name
        try:
            source = inspect_source(data, filename, manifest.notes)
        except ValueError as exc:
            raise JobError("INVALID_INPUT") from exc
        self.manifest, self.source = manifest, source
        self.warnings = list(source["warnings"])
        self.artifacts = []
        self.assets = {}
        self._documents_created = False
        self._restore()
        self._reconcile_required = False
        self._loaded = True

    def _restore(self):
        payload = self._get(self._manifest_key, MAX_MANIFEST_BYTES, optional=True)
        if payload is None:
            if self._reconcile_required:
                raise JobError("STATE_RECONCILIATION_REQUIRED")
            return
        try:
            stored = json.loads(payload)
            if not isinstance(stored, dict) or stored.get("job_id") != self.job_id or stored.get("account_id") != self.account_id or stored.get("app_region") != self.region:
                raise JobError("ARTIFACT_AUTHORITY_MISMATCH")
            artifacts = stored.get("artifacts")
            render_assets = stored.get("render_assets", {})
            if not isinstance(artifacts, list) or len(artifacts) > 15 or not isinstance(render_assets, dict) or len(render_assets) > MAX_VISUAL_ASSETS:
                raise JobError("INVALID_ARTIFACT_MANIFEST")
            verified = []
            names = set()
            ids = set()
            total = 0
            for entry in artifacts:
                if not isinstance(entry, dict):
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                name, ident, size = entry.get("filename"), entry.get("id"), entry.get("size")
                key = self._output_key(name)
                if not isinstance(ident, str) or not _ARTIFACT.fullmatch(ident) or ident in ids or name in names:
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                if type(size) is not int or not 0 < size <= MAX_ARTIFACT_BYTES:
                    raise JobError("OUTPUT_LIMIT")
                digest = entry.get("sha256")
                if not isinstance(digest, str) or not _HASH.fullmatch(digest) or entry.get("key") != key:
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                if entry.get("mime") != MIME[name.rsplit(".", 1)[-1]] or entry.get("kind") not in {"chart", "diagram", "document"}:
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                if not isinstance(entry.get("title"), str) or len(entry["title"]) > 180:
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                names.add(name)
                ids.add(ident)
                total += size
                if total > MAX_OUTPUT_BYTES:
                    raise JobError("OUTPUT_LIMIT")
                data = self._get(key, MAX_ARTIFACT_BYTES)
                if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                    raise JobError("ARTIFACT_INTEGRITY_ERROR")
                path = self.root / name
                if path.is_symlink() or path.resolve().parent != self.root:
                    raise JobError("INVALID_ARTIFACT")
                path.write_bytes(data)
                verified.append({key: entry[key] for key in ("id", "filename", "mime", "kind", "title", "size", "sha256", "key")})
            restored = {}
            for asset_id, asset in render_assets.items():
                if not isinstance(asset_id, str) or not _ASSET.fullmatch(asset_id) or not isinstance(asset, dict):
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                if asset.get("id") != asset_id or asset.get("kind") != asset_id.split("_", 1)[0] or not isinstance(asset.get("spec"), dict):
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                files = asset.get("files")
                if not isinstance(files, list) or not 1 <= len(files) <= 2:
                    raise JobError("INVALID_ARTIFACT_MANIFEST")
                local_files = []
                for file in files:
                    name = file.get("filename")
                    match = next((entry for entry in verified if entry["filename"] == name and entry["id"].startswith(asset_id + "_")), None)
                    if match is None or file.get("mime") != match["mime"]:
                        raise JobError("INVALID_ARTIFACT_MANIFEST")
                    local_files.append({"filename": name, "mime": match["mime"], "path": str(self.root / name)})
                restored[asset_id] = {"id": asset_id, "kind": asset["kind"], "title": asset.get("title", ""), "spec": asset["spec"], "files": local_files}
            visual_ids = {entry["id"].rsplit("_", 1)[0] for entry in verified if entry["kind"] in {"chart", "diagram"}}
            if visual_ids != set(restored):
                raise JobError("RECOVERY_METADATA_MISSING")
            self.artifacts, self.assets = verified, restored
            self._documents_created = any(entry["kind"] == "document" for entry in verified)
            saved_warnings = stored.get("warnings", [])
            if isinstance(saved_warnings, list):
                self.warnings = list(dict.fromkeys(self.warnings + [warning for warning in saved_warnings[:100] if isinstance(warning, str) and len(warning) <= 1000]))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise JobError("INVALID_ARTIFACT_MANIFEST") from exc

    def _profile(self):
        profile = source_profile(self.source)
        profile["request"] = {"prompt": self.manifest.prompt, "outputs": list(self.manifest.outputs), "style": self.manifest.style, "language": self.manifest.language}
        return profile

    def _persist(self):
        render_assets = {
            asset_id: {"id": asset["id"], "kind": asset["kind"], "title": asset["title"], "spec": asset["spec"],
                       "files": [{"filename": file["filename"], "mime": file["mime"]} for file in asset["files"]]}
            for asset_id, asset in self.assets.items()
        }
        payload = _json_bytes({"account_id": self.account_id, "app_region": self.region, "job_id": self.job_id,
                               "artifacts": self.artifacts, "profile": self._profile(), "warnings": self.warnings,
                               "render_assets": render_assets, "updated_at": _now()})
        if len(payload) > MAX_MANIFEST_BYTES:
            raise JobError("OUTPUT_LIMIT")
        try:
            self._put(self._manifest_key, payload, "application/json")
        except (BotoCoreError, ClientError):
            # A timeout may arrive after S3 committed this exact state. Never
            # let the caller's rolled-back local snapshot become authoritative.
            # A subsequent call must recover a readable durable manifest first.
            self._loaded = False
            self._reconcile_required = True
            raise

    def _envelope(self, tool, *, profile=None, error=None):
        result = {"status": "error" if error else "ok", "tool": tool, "job_id": self.job_id,
                  "observed_at": _now(), "artifacts": [{field: entry[field] for field in ("id", "filename", "mime", "kind", "title", "size", "sha256")} for entry in self.artifacts],
                  "warnings": list(self.warnings)}
        if profile is not None:
            result["profile"] = profile
        if error:
            result["error_code"] = error
        return result

    def _run(self, tool, model, arguments, action):
        with self._lock:
            snapshot = None
            try:
                args = model.model_validate(arguments)
                self._ensure_loaded()
                snapshot = (list(self.artifacts), dict(self.assets), list(self.warnings), self._documents_created)
                profile = action(args)
                self._persist()
                return self._envelope(tool, profile=profile)
            except JobError as exc:
                code = exc.code
            except ValidationError:
                code = "INVALID_ARGUMENTS"
            except ValueError as exc:
                message = str(exc)
                code = "INVALID_REQUEST"
                if message.startswith("No usable numeric data"):
                    code = "NO_NUMERIC_DATA"
                elif message.startswith("No present values"):
                    code = "NO_VALUES_TO_COUNT"
                elif message.startswith(("Pie charts", "The plotted pie")):
                    code = "INVALID_PIE_DATA"
                elif message.startswith("Numeric aggregation overflowed"):
                    code = "NUMERIC_OVERFLOW"
            except (BotoCoreError, ClientError):
                code = "STORAGE_UNAVAILABLE"
            except Exception:
                code = "GENERATION_FAILED"
            if snapshot is not None:
                self.artifacts, self.assets, self.warnings, self._documents_created = snapshot
            return self._envelope(tool, error=code)

    def inspect_inputs(self):
        """Call first. Read untrusted source content and stable table column IDs."""
        return self._run("inspect_inputs", EmptyArgs, {}, lambda args: self._profile())

    def read_text(self, offset=0, limit=8000):
        """Page through exact file text, followed by notes, using character offsets."""
        def read(args):
            file_text, notes = self.source["text"], self.source["notes"]
            separator = "\n\n" if file_text and notes else ""
            text = file_text + separator + notes
            sources = []
            if file_text:
                sources.append({"kind": "file_text", "start": 0, "end": len(file_text)})
            if notes:
                start = len(file_text) + len(separator)
                sources.append({"kind": "notes", "start": start, "end": start + len(notes)})
            page = text[args.offset:args.offset + args.limit]
            next_offset = args.offset + len(page)
            return {"text_page": {"text": page, "offset": args.offset, "total_characters": len(text),
                                  "next_offset": next_offset if next_offset < len(text) else None,
                                  "sources": sources}}
        return self._run("read_text", ReadTextArgs, {"offset": offset, "limit": limit}, read)

    def read_table(self, sheet_id, offset=0, limit=20):
        def read(args):
            sheet = next((sheet for sheet in self.source["sheets"] if sheet["id"] == args.sheet_id), None)
            if sheet is None:
                raise JobError("UNKNOWN_SHEET")
            rows = []
            shortened = False
            columns = [{**column, "name": column["name"][:100]} for column in sheet["columns"]]
            table = {"id": sheet["id"], "name": sheet["name"], "columns": columns, "rows": rows,
                     "row_count": sheet["row_count"], "offset": args.offset, "next_offset": None}
            for row in sheet["rows"][args.offset:args.offset + args.limit]:
                limit = 1000
                bounded = [cell[:limit] if isinstance(cell, str) else cell for cell in row]
                table["rows"] = [*rows, bounded]
                # Account for JSON whitespace too, since a host may reserialize
                # this structured result with default separators.
                size = len(json.dumps({"table": table}, ensure_ascii=False).encode("utf-8"))
                if rows and size > MAX_TABLE_RESPONSE_BYTES - 32:
                    break
                while size > MAX_TABLE_RESPONSE_BYTES - 32 and limit > 32:
                    limit //= 2
                    bounded = [cell[:limit] if isinstance(cell, str) else cell for cell in row]
                    table["rows"] = [bounded]
                    size = len(json.dumps({"table": table}, ensure_ascii=False).encode("utf-8"))
                if size > MAX_TABLE_RESPONSE_BYTES - 32:
                    raise JobError("TABLE_RESPONSE_LIMIT")
                shortened |= bounded != row
                rows.append(bounded)
            if shortened or columns != sheet["columns"]:
                self.warnings = list(dict.fromkeys(self.warnings + ["Table text and labels may be shortened to fit the preview budget; original source values are unchanged."]))
            next_offset = args.offset + len(rows)
            table["rows"] = rows
            table["next_offset"] = next_offset if next_offset < sheet["row_count"] else None
            return {"table": table}
        return self._run("read_table", ReadTableArgs, {"sheet_id": sheet_id, "offset": offset, "limit": limit}, read)

    def _visual_id(self, kind):
        if self._documents_created:
            raise JobError("DOCUMENT_ALREADY_CREATED")
        if len(self.assets) >= MAX_VISUAL_ASSETS:
            raise JobError("ASSET_LIMIT")
        return next(f"{kind}_{number}" for number in range(1, MAX_VISUAL_ASSETS + 1) if f"{kind}_{number}" not in self.assets)

    def _store_result(self, result):
        asset_id, kind = result["id"], result["kind"]
        if not (asset_id == "documents" and kind == "document") and not (_ASSET.fullmatch(asset_id) and kind == asset_id.split("_", 1)[0]):
            raise JobError("INVALID_ARTIFACT")
        files = result.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 3:
            raise JobError("INVALID_ARTIFACT")
        expected_extensions = {"png", "svg"} if kind in {"chart", "diagram"} else {"html", *(fmt for fmt in ("pptx", "docx") if fmt in self.manifest.outputs)}
        extensions = [file.get("filename", "").rsplit(".", 1)[-1] for file in files]
        if set(extensions) != expected_extensions or len(extensions) != len(expected_extensions):
            raise JobError("INCOMPLETE_RENDER_OUTPUT")
        staged = []
        total = sum(entry["size"] for entry in self.artifacts)
        existing = {entry["id"] for entry in self.artifacts}
        for file in files:
            name = file["filename"]
            key = self._output_key(name)
            extension = name.rsplit(".", 1)[-1]
            identifier = f"{asset_id}_{extension}"
            expected_name = "preview.html" if asset_id == "documents" and extension == "html" else f"{asset_id}.{extension}"
            if name != expected_name:
                raise JobError("INVALID_ARTIFACT")
            path = Path(file["path"])
            if not path.is_absolute():
                path = self.root / path
            if path.is_symlink() or path.resolve().parent != self.root or path.name != name or not path.is_file():
                raise JobError("INVALID_ARTIFACT")
            if file["mime"] != MIME[extension] or identifier in existing:
                raise JobError("INVALID_ARTIFACT")
            if (kind in {"chart", "diagram"} and extension not in {"png", "svg"}) or (kind == "document" and extension not in {"pptx", "docx", "html"}):
                raise JobError("INVALID_ARTIFACT")
            if kind == "document" and extension != "html" and extension not in self.manifest.outputs:
                raise JobError("OUTPUT_NOT_REQUESTED")
            size = path.stat().st_size
            total += size
            if not 0 < size <= MAX_ARTIFACT_BYTES or total > MAX_OUTPUT_BYTES:
                raise JobError("OUTPUT_LIMIT")
            with path.open("rb") as handle:
                data = handle.read(MAX_ARTIFACT_BYTES + 1)
            if len(data) != size:
                raise JobError("INVALID_ARTIFACT")
            entry = {"id": identifier, "filename": name, "mime": MIME[extension], "kind": kind,
                     "title": result["title"], "size": size, "sha256": hashlib.sha256(data).hexdigest(), "key": key}
            staged.append((entry, data))
            existing.add(identifier)
        for entry, data in staged:
            self._put(entry["key"], data, entry["mime"])
        self.artifacts = [*self.artifacts, *(entry for entry, _ in staged)]
        if kind == "document":
            self._documents_created = True
        else:
            self.assets = {**self.assets, asset_id: result}
        warnings = result.get("spec", {}).get("warnings", [])
        self.warnings = list(dict.fromkeys(self.warnings + [item for item in warnings if isinstance(item, str)]))

    def create_chart(self, title, sheet_id, x_column, y_column=None, aggregation="sum", chart_type="bar", group_by="value"):
        def create(args):
            asset_id = self._visual_id("chart")
            spec = aggregate_chart(self.source, args.sheet_id, args.x_column, args.y_column, args.aggregation, args.chart_type, args.group_by)
            spec["title"] = args.title
            self._store_result(render_chart(spec, self.root, style=self.manifest.style, asset_id=asset_id))
            return {"created_asset": {"id": asset_id, "kind": "chart", "title": args.title}}
        arguments = dict(title=title, sheet_id=sheet_id, x_column=x_column, y_column=y_column, aggregation=aggregation, chart_type=chart_type, group_by=group_by)
        return self._run("create_chart", ChartArgs, arguments, create)

    def create_diagram(self, title, nodes, edges=None, layout="flow"):
        def create(args):
            asset_id = self._visual_id("diagram")
            self._store_result(render_diagram(args.model_dump(), self.root, style=self.manifest.style, asset_id=asset_id))
            return {"created_asset": {"id": asset_id, "kind": "diagram", "title": args.title}}
        return self._run("create_diagram", DiagramArgs, dict(title=title, nodes=nodes, edges=[] if edges is None else edges, layout=layout), create)

    def _source_notes(self):
        notes = []
        if self.source["filename"]:
            notes.append(f"Source file: {self.source['filename']}")
        if self.source["notes"]:
            notes.append("Source: user-provided notes.")
        for asset in self.assets.values():
            source = asset.get("spec", {}).get("source")
            if isinstance(source, dict):
                x = source.get("x_column", {})
                y = source.get("y_column") or {}
                note = f"{asset['title']}: {source.get('file') or 'input'}, {source.get('sheet', '')}; {x.get('name', '')} / {y.get('name', 'row count')}; {source.get('aggregation', '')}."
                notes.append(note[:600])
        return notes[:16]

    def create_documents(self, title, subtitle="", sections=None):
        def create(args):
            if self._documents_created:
                raise JobError("DOCUMENT_ALREADY_CREATED")
            formats = tuple(fmt for fmt in ("pptx", "docx") if fmt in self.manifest.outputs)
            if not formats:
                raise JobError("OUTPUT_NOT_REQUESTED")
            referenced = {asset_id for section in args.sections for asset_id in section.asset_ids}
            if not referenced <= set(self.assets):
                raise JobError("UNKNOWN_ASSET")
            self._store_result(render_documents(args.model_dump(), self.assets, self.root, style=self.manifest.style, formats=formats, source_notes=self._source_notes()))
            return None
        return self._run("create_documents", DocumentArgs, dict(title=title, subtitle=subtitle, sections=[] if sections is None else sections), create)
