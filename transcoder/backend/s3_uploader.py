import os
import glob
import time
import logging
import threading
import boto3
from botocore.exceptions import ClientError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class S3UploadHandler(FileSystemEventHandler):
    def __init__(self, s3_client, bucket: str, s3_prefix: str, local_root: str):
        self.s3_client = s3_client
        self.bucket = bucket
        self.s3_prefix = s3_prefix
        self.local_root = local_root
        self.uploaded = set()
        self._lock = threading.Lock()
        self.active = True

    def _should_upload(self, path: str) -> bool:
        if not self.active:
            return False
        if path.endswith(".tmp") or ".tmp." in path:
            return False
        return path.endswith((".ts", ".m3u8", ".mp4", ".m4s", ".vtt", ".fmp4"))

    def _upload(self, local_path: str, retries: int = 3, delay: float = 1.0) -> bool:
        if not self.active:
            return False
        for attempt in range(retries):
            try:
                if not os.path.exists(local_path):
                    time.sleep(delay)
                    continue
                rel = os.path.relpath(local_path, self.local_root)
                s3_key = f"{self.s3_prefix}/{rel}".replace("\\", "/")
                self.s3_client.upload_file(local_path, self.bucket, s3_key)
                with self._lock:
                    self.uploaded.add(local_path)
                logging.debug(f"S3 upload: s3://{self.bucket}/{s3_key}")
                return True
            except Exception as e:
                if attempt == retries - 1:
                    logging.error(f"S3 upload failed for {local_path}: {e}")
                else:
                    time.sleep(delay)
        return False

    def on_created(self, event):
        if not event.is_directory and self._should_upload(event.src_path):
            if event.src_path.endswith(".ts"):
                self._upload(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._should_upload(event.src_path):
            if event.src_path.endswith(".m3u8"):
                time.sleep(0.5)
                self._upload(event.src_path, retries=5, delay=0.5)

    def on_moved(self, event):
        if not event.is_directory and self._should_upload(event.dest_path):
            time.sleep(0.2)
            self._upload(event.dest_path)

    def stop(self):
        self.active = False


class PeriodicUploader:
    """Scans directory every N seconds and uploads new files."""

    def __init__(self, handler: S3UploadHandler, interval: float = 2.0):
        self.handler = handler
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                for pattern in ["**/*.ts", "**/*.m3u8", "**/*.vtt", "**/*.mp4"]:
                    for fp in glob.glob(os.path.join(self.handler.local_root, pattern), recursive=True):
                        if self.handler._should_upload(fp) and fp not in self.handler.uploaded:
                            self.handler._upload(fp)
            except Exception as e:
                logging.error(f"Periodic uploader error: {e}")
            self._stop_event.wait(timeout=self.interval)


def build_s3_client(access_key: str = None, secret_key: str = None, region: str = "us-east-1"):
    if access_key and secret_key:
        return boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
    return boto3.client("s3", region_name=region)


def upload_directory_to_s3(local_dir: str, bucket: str, s3_prefix: str, s3_client=None) -> int:
    """Bulk upload entire directory to S3. Returns count of uploaded files."""
    if s3_client is None:
        s3_client = boto3.client("s3")

    count = 0
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            if not filename.endswith((".ts", ".m3u8", ".mp4", ".m4s", ".vtt")):
                continue
            local_path = os.path.join(root, filename)
            rel = os.path.relpath(local_path, local_dir)
            s3_key = f"{s3_prefix}/{rel}".replace("\\", "/")
            try:
                s3_client.upload_file(local_path, bucket, s3_key)
                count += 1
                logging.info(f"Uploaded: s3://{bucket}/{s3_key}")
            except Exception as e:
                logging.error(f"Failed to upload {local_path}: {e}")

    return count


def start_live_upload_watcher(local_dir: str, bucket: str, s3_prefix: str, s3_client=None):
    """Start watchdog observer + periodic uploader for live streaming."""
    if s3_client is None:
        s3_client = boto3.client("s3")

    handler = S3UploadHandler(s3_client, bucket, s3_prefix, local_dir)
    observer = Observer()
    observer.schedule(handler, local_dir, recursive=True)
    observer.start()

    periodic = PeriodicUploader(handler)
    periodic.start()

    return observer, handler, periodic
