"""Bound body size and concurrent uploads before parsing or business actions.

Bodies are spooled to a temporary file above 256 KiB and replayed in 64 KiB
chunks. All file I/O runs in a worker thread. At most four uploads may occupy
the receive/parse/transfer path until the downstream response has completed.
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_uploads=4, spool_max_bytes=256 * 1024, idle_timeout=30, upload_timeout=120, form_timeout=30):
        if not 1 <= max_uploads <= 4 or spool_max_bytes < 1 or min(idle_timeout, upload_timeout, form_timeout) <= 0:
            raise ValueError("Invalid request limits")
        self.app = app
        self.max_uploads = max_uploads
        self.spool_max_bytes = spool_max_bytes
        self.idle_timeout = idle_timeout
        self.upload_timeout = upload_timeout
        self.form_timeout = form_timeout
        self._uploads = 0
        self._lock = threading.Lock()

    @property
    def active_uploads(self):
        with self._lock:
            return self._uploads

    def _acquire_upload(self):
        with self._lock:
            if self._uploads >= self.max_uploads:
                return False
            self._uploads += 1
            return True

    def _release_upload(self):
        with self._lock:
            self._uploads -= 1

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        upload = scope.get("path") == "/app/carica-documenti"
        limit = 16 * 1024 * 1024 + 64 * 1024 if upload else 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await PlainTextResponse("Lunghezza richiesta non valida.", status_code=400)(scope, receive, send)
        if content_length > limit or content_length < 0:
            return await PlainTextResponse("Richiesta troppo grande. Nessun dato è stato inviato al MASTER.", status_code=413)(scope, receive, send)
        acquired = upload and self._acquire_upload()
        if upload and not acquired:
            return await PlainTextResponse("Caricamenti momentaneamente occupati. Attendi e riprova.", status_code=429, headers={"Retry-After": "3"})(scope, receive, send)

        spool = None
        try:
            spool = tempfile.SpooledTemporaryFile(max_size=self.spool_max_bytes, mode="w+b")
            deadline = time.monotonic() + (self.upload_timeout if upload else self.form_timeout)
            total = 0
            while True:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    return await PlainTextResponse("Caricamento interrotto per tempo scaduto. Riprova.", status_code=408)(scope, receive, send)
                try:
                    message = await asyncio.wait_for(receive(), timeout=min(self.idle_timeout, remaining_time))
                except (asyncio.TimeoutError, TimeoutError):
                    return await PlainTextResponse("Caricamento interrotto per tempo scaduto. Riprova.", status_code=408)(scope, receive, send)
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                total += len(body)
                if total > limit:
                    return await PlainTextResponse("Richiesta troppo grande. Nessun dato è stato inviato al MASTER.", status_code=413)(scope, receive, send)
                if body:
                    # Roll over before writing a large incoming chunk, so the
                    # in-memory BytesIO never temporarily grows to the body size.
                    if total > self.spool_max_bytes and not getattr(spool, "_rolled", False):
                        await run_in_threadpool(spool.rollover)
                    await run_in_threadpool(spool.write, body)
                more = message.get("more_body", False)
                del body, message
                if not more:
                    break
            await run_in_threadpool(spool.seek, 0)
            remaining = total
            exhausted = False

            async def replay():
                nonlocal remaining, exhausted
                if exhausted:
                    return await receive()
                body = await run_in_threadpool(spool.read, min(64 * 1024, remaining))
                remaining -= len(body)
                exhausted = remaining == 0
                return {"type": "http.request", "body": body, "more_body": not exhausted}

            return await self.app(scope, replay, send)
        finally:
            try:
                if spool is not None:
                    with anyio.CancelScope(shield=True):
                        await run_in_threadpool(spool.close)
            finally:
                if acquired:
                    self._release_upload()
