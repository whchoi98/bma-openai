"""Runtime authority, artifact persistence, and MCP schema regression tests."""
import asyncio
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError, ReadTimeoutError

try:
    from studio.document_tools import job as job_module
    from studio.document_tools import mcp_server
except ImportError:
    job_module = None
    mcp_server = None

JOB_ID = "11111111-1111-4111-8111-111111111111"
UPLOAD_ID = "22222222-2222-4222-8222-222222222222"
ACCOUNT = "123456789012"
BUCKET = "studio-unit-tests"
DATA = b"region,revenue\nEast,2\nEast,3\nWest,4\n"


def manifest(outputs=None):
    return {"id": JOB_ID, "account_id": ACCOUNT, "app_region": "us-east-1", "upload": {"id": UPLOAD_ID, "name": "revenue.csv", "size": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest()}, "notes": "Source notes", "prompt": "Create a revenue document", "outputs": outputs or ["pptx", "docx", "chart"], "style": "business", "language": "en"}


class FakeS3:
    def __init__(self, source_manifest=None):
        self.objects = {f"jobs/{JOB_ID}/input.json": json.dumps(source_manifest or manifest()).encode(), f"uploads/{UPLOAD_ID}/data": DATA}
        self.calls = []
        self.failure = None
        self.missing_code = "NoSuchKey"

    def _record(self, operation, args):
        self.calls.append((operation, args))
        if args.get("Bucket") != BUCKET or args.get("ExpectedBucketOwner") != ACCOUNT:
            raise AssertionError("Every object/list operation must bind bucket owner")
        if self.failure:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": self.failure}}, operation)

    def get_object(self, **kwargs):
        self._record("get_object", kwargs)
        if kwargs["Key"] not in self.objects:
            raise ClientError({"Error": {"Code": self.missing_code, "Message": "missing"}, "ResponseMetadata": {"HTTPStatusCode": 403 if self.missing_code == "AccessDenied" else 404}}, "GetObject")
        data = self.objects[kwargs["Key"]]
        return {"ContentLength": len(data), "Body": io.BytesIO(data)}

    def put_object(self, **kwargs):
        self._record("put_object", kwargs)
        value = kwargs["Body"]
        self.objects[kwargs["Key"]] = value if isinstance(value, bytes) else value.encode()
        return {"ETag": "test"}

    def list_objects_v2(self, **kwargs):
        self._record("list_objects_v2", kwargs)
        keys = sorted(key for key in self.objects if key.startswith(kwargs["Prefix"]))[:kwargs["MaxKeys"]]
        return {"Contents": [{"Key": key} for key in keys]}


class FakeSTS:
    def __init__(self, account=ACCOUNT):
        self.account = account
        self.calls = 0

    def get_caller_identity(self):
        self.calls += 1
        return {"Account": self.account, "Arn": f"arn:aws:sts::{self.account}:assumed-role/runtime/test", "UserId": "test"}


def fake_chart(spec, outdir, style="business", asset_id="chart_1"):
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for extension, mime in [("png", "image/png"), ("svg", "image/svg+xml")]:
        path = root / f"{asset_id}.{extension}"
        path.write_bytes(b"artifact")
        files.append({"path": str(path), "filename": path.name, "mime": mime})
    return {"id": asset_id, "kind": "chart", "title": spec["title"], "files": files, "spec": spec}


def fake_documents(blueprint, assets, outdir, style="business", formats=("pptx", "docx"), source_notes=()):
    root = Path(outdir)
    files = []
    for ext in [*formats, "html"]:
        name = "preview.html" if ext == "html" else f"documents.{ext}"
        path = root / name
        path.write_bytes(("document " + "|".join(source_notes)).encode())
        mime = {"html": "text/html", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[ext]
        files.append({"path": str(path), "filename": name, "mime": mime})
    return {"id": "documents", "kind": "document", "title": blueprint["title"], "files": files, "spec": blueprint}


class DocumentJobTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(job_module, "The fixed-authority document job adapter must exist")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.s3 = FakeS3()
        self.sts = FakeSTS()
        self.adapter = self.make_job()
        self.chart_patch = patch.object(job_module, "render_chart", side_effect=fake_chart)
        self.documents_patch = patch.object(job_module, "render_documents", side_effect=fake_documents)
        self.chart = self.chart_patch.start()
        self.documents = self.documents_patch.start()
        self.addCleanup(self.chart_patch.stop)
        self.addCleanup(self.documents_patch.stop)

    def make_job(self, **kwargs):
        args = {"bucket": BUCKET, "account_id": ACCOUNT, "region": "us-east-1", "s3_client": self.s3, "sts_client": self.sts, "workdir": self.directory.name}
        args.update(kwargs)
        return job_module.DocumentJob(JOB_ID, **args)

    def test_inspection_checks_identity_and_exposes_only_bounded_profile(self):
        result = self.adapter.inspect_inputs()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.sts.calls, 1)
        self.assertEqual(result["profile"]["sheets"][0]["row_count"], 3)
        self.assertNotIn("key", json.dumps(result))
        self.assertEqual(self.s3.calls[0][1]["Key"], f"jobs/{JOB_ID}/input.json")

    def test_wrong_identity_never_reads_s3(self):
        result = self.make_job(sts_client=FakeSTS("999999999999")).inspect_inputs()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "ACCOUNT_MISMATCH")
        self.assertEqual(self.s3.calls, [])

    def test_wrong_region_or_unsafe_job_id_is_rejected_before_io(self):
        with self.assertRaises(ValueError):
            self.make_job(region="eu-west-1")
        with self.assertRaises(ValueError):
            job_module.DocumentJob("../../other", bucket=BUCKET, account_id=ACCOUNT, s3_client=self.s3, sts_client=self.sts)
        self.assertEqual(self.s3.calls, [])

    def test_manifest_identity_and_upload_digest_are_verified(self):
        bad = manifest()
        bad["account_id"] = "999999999999"
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(bad).encode()
        self.assertEqual(self.adapter.inspect_inputs()["status"], "error")
        self.assertFalse(any(call[1].get("Key", "").startswith("uploads/") for call in self.s3.calls))
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(manifest()).encode()
        self.s3.objects[f"uploads/{UPLOAD_ID}/data"] = DATA + b"tampered"
        self.assertEqual(self.make_job().inspect_inputs()["error_code"], "INPUT_INTEGRITY_ERROR")

    def test_read_text_pages_preserve_file_and_note_tails(self):
        file_text = "가" * 29991 + "FILE_TAIL"
        notes = "나" * 19991 + "NOTE_TAIL"
        payload = file_text.encode()
        source = manifest()
        source["notes"] = notes
        source["upload"].update(name="long.txt", size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(source).encode()
        self.s3.objects[f"uploads/{UPLOAD_ID}/data"] = payload
        profile = self.adapter.inspect_inputs()["profile"]
        self.assertTrue(profile["text_truncated"])
        self.assertTrue(profile["notes_truncated"])
        pieces = []
        offset = 0
        while offset is not None:
            result = self.adapter.read_text(offset=offset, limit=8000)
            self.assertEqual(result["status"], "ok", result)
            page = result["profile"]["text_page"]
            self.assertLessEqual(len(page["text"]), 8000)
            pieces.append(page["text"])
            offset = page["next_offset"]
        expected = file_text + "\n\n" + notes
        self.assertEqual("".join(pieces), expected)
        self.assertEqual(page["total_characters"], len(expected))
        self.assertEqual(page["sources"][1]["start"], len(file_text) + 2)

    def test_read_text_supports_notes_only_and_rejects_unbounded_arguments(self):
        source = manifest()
        source["upload"] = None
        source["notes"] = "x" * 49990 + "FINAL_TAIL"
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(source).encode()
        result = self.adapter.read_text(offset=49990, limit=20)
        self.assertEqual(result["profile"]["text_page"]["text"], "FINAL_TAIL")
        self.assertIsNone(result["profile"]["text_page"]["next_offset"])
        for arguments in [{"offset": -1}, {"limit": 8001}, {"limit": 0}]:
            self.assertEqual(self.adapter.read_text(**arguments)["error_code"], "INVALID_ARGUMENTS")

    def test_read_table_has_bounded_pages_and_stable_columns(self):
        result = self.adapter.read_table("sheet_0", offset=1, limit=1)
        self.assertEqual(result["profile"]["table"]["rows"], [["East", 3]])
        self.assertEqual(result["profile"]["table"]["next_offset"], 2)
        for arguments in [("sheet_0", -1, 1), ("sheet_0", 0, 21), ("../x", 0, 1)]:
            self.assertEqual(self.adapter.read_table(*arguments)["status"], "error")

    def test_chart_uses_computed_values_and_writes_private_manifest(self):
        result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.chart.call_args.args[0]["values"], [5, 4])
        self.assertEqual([asset["id"] for asset in result["artifacts"]], ["chart_1_png", "chart_1_svg"])
        private = json.loads(self.s3.objects[f"jobs/{JOB_ID}/artifacts.json"])
        self.assertEqual(private["account_id"], ACCOUNT)
        self.assertEqual(private["render_assets"]["chart_1"]["spec"]["values"], [5, 4])
        self.assertTrue(all(entry["key"].startswith(f"jobs/{JOB_ID}/outputs/") for entry in private["artifacts"]))
        self.assertNotIn("key", result["artifacts"][0])

    def test_six_visual_assets_and_document_finality_are_enforced(self):
        for index in range(6):
            self.assertEqual(self.adapter.create_chart(f"C{index}", "sheet_0", "c0", "c1")["status"], "ok")
        self.assertEqual(self.adapter.create_chart("overflow", "sheet_0", "c0", "c1")["error_code"], "ASSET_LIMIT")
        result = self.adapter.create_documents("Report", sections=[{"heading": "Results", "asset_ids": ["chart_1"]}])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.adapter.create_documents("Again", sections=[])["error_code"], "DOCUMENT_ALREADY_CREATED")
        self.assertEqual(self.adapter.create_chart("Late", "sheet_0", "c0", "c1")["error_code"], "DOCUMENT_ALREADY_CREATED")

    def test_document_formats_and_source_notes_are_server_authoritative(self):
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(manifest(["docx"])).encode()
        result = self.adapter.create_documents("Report", sections=[{"heading": "Results", "paragraphs": ["Original data"]}])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.documents.call_args.kwargs["formats"], ("docx",))
        self.assertTrue(any("revenue.csv" in note for note in self.documents.call_args.kwargs["source_notes"]))
        self.assertEqual({entry["filename"] for entry in result["artifacts"]}, {"documents.docx", "preview.html"})

    def test_documents_reject_invented_asset_ids_before_renderer(self):
        result = self.adapter.create_documents("Report", sections=[{"heading": "Results", "asset_ids": ["not_real"]}])
        self.assertEqual(result["status"], "error")
        self.documents.assert_not_called()

    def test_missing_manifest_403_uses_exact_key_probe(self):
        self.s3.missing_code = "AccessDenied"
        self.assertEqual(self.adapter.inspect_inputs()["status"], "ok")
        probes = [args for op, args in self.s3.calls if op == "list_objects_v2"]
        self.assertEqual(probes[0]["Prefix"], f"jobs/{JOB_ID}/artifacts.json")
        self.assertEqual(probes[0]["MaxKeys"], 1)

    def test_restart_restores_checked_chart_files_and_specs(self):
        self.assertEqual(self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")["status"], "ok")
        with tempfile.TemporaryDirectory() as restored_dir:
            restored = self.make_job(workdir=restored_dir)
            result = restored.create_documents("Report", sections=[{"heading": "Revenue", "asset_ids": ["chart_1"]}])
            self.assertEqual(result["status"], "ok")
            asset = self.documents.call_args.args[1]["chart_1"]
            self.assertEqual(asset["spec"]["values"], [5, 4])
            self.assertEqual(Path(asset["files"][0]["path"]).read_bytes(), b"artifact")

    def test_tampered_recovery_artifact_is_rejected(self):
        self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.s3.objects[f"jobs/{JOB_ID}/outputs/chart_1.png"] = b"tampered"
        with tempfile.TemporaryDirectory() as restored_dir:
            result = self.make_job(workdir=restored_dir).inspect_inputs()
        self.assertEqual(result["error_code"], "ARTIFACT_INTEGRITY_ERROR")

    def test_output_path_and_size_are_checked_before_upload(self):
        def bad_chart(*args, **kwargs):
            result = fake_chart(*args, **kwargs)
            result["files"][0]["path"] = "/etc/passwd"
            return result
        self.chart.side_effect = bad_chart
        result = self.adapter.create_chart("Bad", "sheet_0", "c0", "c1")
        self.assertEqual(result["status"], "error")
        self.assertFalse(any(op == "put_object" and "/outputs/" in args["Key"] for op, args in self.s3.calls))
        self.chart.side_effect = fake_chart
        with patch.object(job_module, "MAX_ARTIFACT_BYTES", 2):
            result = self.adapter.create_chart("Large", "sheet_0", "c0", "c1")
        self.assertEqual(result["error_code"], "OUTPUT_LIMIT")

    def test_aws_failures_never_expose_raw_errors_or_paths(self):
        self.s3.failure = "secret credential /private/path arn:aws:iam::123456789012:role/secret"
        result = self.adapter.inspect_inputs()
        self.assertEqual(result["status"], "error")
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("/private", json.dumps(result))

    def test_optional_worker_manifest_metadata_is_validated(self):
        source = manifest()
        source.update(created_at="2026-10-27T10:00:00.000Z", input_hash="a" * 64, source_job_id="33333333-3333-4333-8333-333333333333")
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(source).encode()
        result = self.adapter.inspect_inputs()
        self.assertEqual(result["status"], "ok", result)
        for field, invalid in [("created_at", "tomorrow"), ("input_hash", "not-a-hash"), ("source_job_id", "../other")]:
            bad = dict(source, **{field: invalid})
            with self.subTest(field=field), self.assertRaises(ValueError):
                job_module.InputManifest.model_validate_json(json.dumps(bad))

    def test_no_numeric_data_has_an_actionable_safe_error_code(self):
        no_numbers = b"region,revenue\nEast,missing\n"
        source = manifest()
        source["upload"].update(size=len(no_numbers), sha256=hashlib.sha256(no_numbers).hexdigest())
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(source).encode()
        self.s3.objects[f"uploads/{UPLOAD_ID}/data"] = no_numbers
        result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.assertEqual(result["error_code"], "NO_NUMERIC_DATA")

    def test_incomplete_renderer_result_is_not_published(self):
        def incomplete(*args, **kwargs):
            result = fake_chart(*args, **kwargs)
            result["files"] = result["files"][:1]
            return result
        self.chart.side_effect = incomplete
        result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.assertEqual(result["status"], "error")
        self.assertFalse(any(op == "put_object" and "/outputs/" in args["Key"] for op, args in self.s3.calls))

    def test_wide_unicode_table_pages_stay_within_response_budget(self):
        csv_data = ((",".join(["가" * 1000] * 50)) + "\n" + (",".join(["나" * 2000] * 50))).encode()
        source = manifest()
        source["upload"]["size"] = len(csv_data)
        source["upload"]["sha256"] = hashlib.sha256(csv_data).hexdigest()
        self.s3.objects[f"jobs/{JOB_ID}/input.json"] = json.dumps(source).encode()
        self.s3.objects[f"uploads/{UPLOAD_ID}/data"] = csv_data
        result = self.adapter.read_table("sheet_0")
        self.assertEqual(result["status"], "ok", result)
        self.assertLessEqual(len(json.dumps(result["profile"], ensure_ascii=False).encode()), 64 * 1024)
        self.assertEqual(len(result["profile"]["table"]["rows"]), 1)
        self.assertEqual(len(self.adapter.source["sheets"][0]["rows"][0][0]), 2000)

    def test_chart_returns_document_asset_id_explicitly(self):
        result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.assertEqual(result["profile"]["created_asset"]["id"], "chart_1")

    def test_parallel_calls_preserve_all_assets_in_manifest(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.adapter.create_chart(f"Chart {i}", "sheet_0", "c0", "c1"), range(4)))
        self.assertTrue(all(result["status"] == "ok" for result in results))
        saved = json.loads(self.s3.objects[f"jobs/{JOB_ID}/artifacts.json"])
        self.assertEqual(len(saved["artifacts"]), 8)
        self.assertEqual(set(saved["render_assets"]), {"chart_1", "chart_2", "chart_3", "chart_4"})

    def test_combined_output_limit_applies_across_tools(self):
        self.assertEqual(self.adapter.create_chart("First", "sheet_0", "c0", "c1")["status"], "ok")
        with patch.object(job_module, "MAX_OUTPUT_BYTES", 25):
            result = self.adapter.create_chart("Too much", "sheet_0", "c0", "c1")
        self.assertEqual(result["error_code"], "OUTPUT_LIMIT")
        self.assertEqual(len(self.adapter.artifacts), 2)
        self.assertNotIn(f"jobs/{JOB_ID}/outputs/chart_2.png", self.s3.objects)

    def test_failed_upload_does_not_publish_partial_artifacts(self):
        original = self.s3.put_object
        def fail_svg(**kwargs):
            if kwargs["Key"].endswith(".svg"):
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "raw secret"}}, "PutObject")
            return original(**kwargs)
        with patch.object(self.s3, "put_object", side_effect=fail_svg):
            result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["artifacts"], [])
        self.assertNotIn(f"jobs/{JOB_ID}/artifacts.json", self.s3.objects)
        self.assertNotIn("raw secret", json.dumps(result))

    def test_committed_manifest_timeout_reconciles_before_next_operation(self):
        original = self.s3.put_object
        uncertain = True
        def commit_then_timeout(**kwargs):
            nonlocal uncertain
            result = original(**kwargs)
            if kwargs["Key"].endswith("artifacts.json") and uncertain:
                uncertain = False
                raise ReadTimeoutError(endpoint_url="https://private.invalid")
            return result
        with patch.object(self.s3, "put_object", side_effect=commit_then_timeout):
            first = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
            self.assertEqual(first["status"], "error")
            second = self.adapter.inspect_inputs()
        self.assertEqual(second["status"], "ok", second)
        self.assertEqual({entry["id"] for entry in second["artifacts"]}, {"chart_1_png", "chart_1_svg"})
        saved = json.loads(self.s3.objects[f"jobs/{JOB_ID}/artifacts.json"])
        self.assertEqual(len(saved["artifacts"]), 2)
        third = self.adapter.create_chart("Another", "sheet_0", "c0", "c1")
        self.assertEqual(third["profile"]["created_asset"]["id"], "chart_2")

    def test_unreconciled_manifest_timeout_cannot_publish_empty_state(self):
        original = self.s3.put_object
        def timeout_without_confirmation(**kwargs):
            if kwargs["Key"].endswith("artifacts.json"):
                raise ReadTimeoutError(endpoint_url="https://private.invalid")
            return original(**kwargs)
        with patch.object(self.s3, "put_object", side_effect=timeout_without_confirmation):
            self.assertEqual(self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")["status"], "error")
        count = len([op for op, _ in self.s3.calls if op == "put_object"])
        result = self.adapter.inspect_inputs()
        self.assertEqual(result["error_code"], "STATE_RECONCILIATION_REQUIRED")
        self.assertEqual(len([op for op, _ in self.s3.calls if op == "put_object"]), count)
        self.assertNotIn(f"jobs/{JOB_ID}/artifacts.json", self.s3.objects)

    def test_recovery_never_reads_a_manifest_supplied_foreign_key(self):
        self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
        saved = json.loads(self.s3.objects[f"jobs/{JOB_ID}/artifacts.json"])
        saved["artifacts"][0]["key"] = "jobs/foreign/outputs/private.png"
        self.s3.objects[f"jobs/{JOB_ID}/artifacts.json"] = json.dumps(saved).encode()
        start = len(self.s3.calls)
        result = self.make_job().inspect_inputs()
        self.assertEqual(result["status"], "error")
        self.assertFalse(any("foreign" in args.get("Key", "") for _, args in self.s3.calls[start:]))

    def test_real_renderer_outputs_survive_recovery_and_remain_editable(self):
        from studio.document_tools import render
        with patch.object(job_module, "render_chart", wraps=render.render_chart), patch.object(job_module, "render_documents", wraps=render.render_documents):
            result = self.adapter.create_chart("Revenue", "sheet_0", "c0", "c1")
            self.assertEqual(result["status"], "ok", result)
            with tempfile.TemporaryDirectory() as restored_dir:
                restored = self.make_job(workdir=restored_dir)
                result = restored.create_documents("Revenue report", sections=[{"heading": "Results", "asset_ids": ["chart_1"]}])
            self.assertEqual(result["status"], "ok", result)
        pptx = self.s3.objects[f"jobs/{JOB_ID}/outputs/documents.pptx"]
        with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
            self.assertIn("ppt/charts/chart1.xml", archive.namelist())
        self.assertTrue(self.s3.objects[f"jobs/{JOB_ID}/outputs/preview.html"].startswith(b"<!doctype html>"))

    def test_mcp_actual_call_validates_nested_diagrams_and_executes(self):
        server = mcp_server.build_server(self.adapter)
        result = asyncio.run(server.call_tool("inspect_inputs", {}))
        self.assertIsNotNone(result)
        args_model = server._tool_manager.get_tool("create_diagram").fn_metadata.arg_model
        with self.assertRaises(ValueError):
            args_model.model_validate({"title": "Flow", "nodes": [{"id": "a", "label": "A", "script": "bad"}]})

    def test_mcp_exposes_only_six_bounded_tools_and_rejects_extra_fields(self):
        self.assertIsNotNone(mcp_server)
        server = mcp_server.build_server(self.adapter)
        tools = asyncio.run(server.list_tools())
        self.assertEqual({tool.name for tool in tools}, {"inspect_inputs", "read_table", "read_text", "create_chart", "create_diagram", "create_documents"})
        for tool in tools:
            self.assertFalse(tool.inputSchema.get("additionalProperties", True))
        args_model = server._tool_manager.get_tool("create_chart").fn_metadata.arg_model
        with self.assertRaises(ValueError):
            args_model.model_validate({"title": "X", "sheet_id": "sheet_0", "x_column": "c0", "shell": "whoami"})
        text_model = server._tool_manager.get_tool("read_text").fn_metadata.arg_model
        with self.assertRaises(ValueError):
            text_model.model_validate({"limit": 8001})
        read_model = server._tool_manager.get_tool("read_table").fn_metadata.arg_model
        with self.assertRaises(ValueError):
            read_model.model_validate({"sheet_id": "sheet_0", "limit": 21})


if __name__ == "__main__":
    unittest.main()
