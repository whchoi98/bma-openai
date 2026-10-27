import json
import threading
from collections import OrderedDict

from botocore.config import Config
from botocore.exceptions import ClientError


class MemoryStore:
    """Local sample only; keep at most 20 completed queries."""

    def __init__(self):
        self.records = OrderedDict()
        self.lock = threading.Lock()

    def put(self, record):
        with self.lock:
            self.records[record["id"]] = json.loads(json.dumps(record))
            while len(self.records) > 20:
                self.records.popitem(last=False)

    def get(self, run_id):
        with self.lock:
            record = self.records.get(run_id)
            return json.loads(json.dumps(record)) if record else None


class S3Store:
    """App state belongs in APP_REGION, independently of the resource query Region."""

    def __init__(self, settings, aws_session):
        self.bucket = settings.state_bucket
        self.client = aws_session.client(
            "s3", region_name=settings.inventory.app_region,
            config=Config(connect_timeout=3, read_timeout=10,
                          retries={"mode": "standard", "total_max_attempts": 3}),
        )

    def put(self, record):
        body = json.dumps(record, ensure_ascii=False, allow_nan=False).encode()
        if len(body) > 4_000_000:
            raise ValueError("Report exceeds the app storage limit.")
        self.client.put_object(
            Bucket=self.bucket, Key=f"runs/{record['id']}.json", Body=body,
            ContentType="application/json", ServerSideEncryption="AES256",
        )

    def get(self, run_id):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=f"runs/{run_id}.json")
        except ClientError as error:
            if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                return None
            raise
        with response["Body"] as body:
            raw = body.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("Stored report exceeds the app limit.")
        return json.loads(raw)
