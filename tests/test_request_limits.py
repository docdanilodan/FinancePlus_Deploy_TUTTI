"""Body-limit, spool lifecycle and concurrency checks without network services."""
import asyncio
import hashlib
import tempfile

import pytest

import request_limits
from request_limits import RequestBodyLimitMiddleware


def request_scope(path="/app/carica-documenti", *, content_length=None):
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {"type": "http", "method": "POST", "path": path, "headers": headers, "asgi": {"version": "3.0"}}


def body_receiver(chunks):
    messages = iter({"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
                    for index, chunk in enumerate(chunks))

    async def receive():
        return next(messages, {"type": "http.disconnect"})

    return receive


async def respond(send, status=204):
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def track_spools(monkeypatch):
    opened = []
    original = tempfile.SpooledTemporaryFile

    def factory(*args, **kwargs):
        spool = original(*args, **kwargs)
        opened.append(spool)
        return spool

    monkeypatch.setattr(request_limits.tempfile, "SpooledTemporaryFile", factory)
    return opened


@pytest.mark.parametrize("many_chunks", [False, True])
def test_upload_spools_before_large_write_and_replays_bounded_chunks(monkeypatch, many_chunks):
    spools = track_spools(monkeypatch)
    payload = b"synthetic-document-bytes\n" * 50000
    chunks = [payload[index:index + 7000] for index in range(0, len(payload), 7000)] if many_chunks else [payload]
    observed = []

    async def downstream(scope, receive, send):
        assert spools[0]._rolled is True
        digest = hashlib.sha256()
        while True:
            message = await receive()
            assert message["type"] == "http.request"
            assert len(message["body"]) <= 64 * 1024
            digest.update(message["body"])
            if not message["more_body"]:
                break
        observed.append(digest.digest())
        await respond(send)

    async def scenario():
        events = []

        async def send(event):
            events.append(event)

        middleware = RequestBodyLimitMiddleware(downstream)
        await middleware(request_scope(), body_receiver(chunks), send)
        assert middleware.active_uploads == 0
        assert events[0]["status"] == 204

    asyncio.run(scenario())
    assert observed == [hashlib.sha256(payload).digest()]
    assert len(spools) == 1 and spools[0].closed


@pytest.mark.parametrize("length,status", [(16 * 1024 * 1024 + 64 * 1024 + 1, 413), ("invalid", 400)])
def test_invalid_or_oversized_length_rejects_before_receive_or_downstream(length, status):
    async def forbidden(*args):
        raise AssertionError("A rejected header must not read or invoke business actions")

    async def scenario():
        events = []

        async def send(event):
            events.append(event)

        middleware = RequestBodyLimitMiddleware(forbidden)
        await middleware(request_scope(content_length=length), forbidden, send)
        assert middleware.active_uploads == 0
        assert events[0]["status"] == status

    asyncio.run(scenario())


def test_actual_stream_size_cannot_bypass_header_and_closes_spool(monkeypatch):
    spools = track_spools(monkeypatch)

    async def forbidden(*args):
        raise AssertionError("Oversized body reached business actions")

    async def scenario():
        events = []

        async def send(event):
            events.append(event)

        middleware = RequestBodyLimitMiddleware(forbidden)
        await middleware(request_scope("/login", content_length=1), body_receiver([b"a" * 65536, b"x"]), send)
        assert events[0]["status"] == 413

    asyncio.run(scenario())
    assert len(spools) == 1 and spools[0].closed


def test_four_upload_slots_are_held_until_downstream_response_finishes(monkeypatch):
    spools = track_spools(monkeypatch)

    async def scenario():
        release = asyncio.Event()
        all_entered = asyncio.Event()
        entered = 0

        async def downstream(scope, receive, send):
            nonlocal entered
            assert (await receive())["body"] == b"synthetic"
            entered += 1
            if entered == 4:
                all_entered.set()
            await release.wait()
            await respond(send)

        middleware = RequestBodyLimitMiddleware(downstream)

        async def invoke():
            events = []

            async def send(event):
                events.append(event)

            await middleware(request_scope(), body_receiver([b"synthetic"]), send)
            return events

        tasks = [asyncio.create_task(invoke()) for _ in range(4)]
        await asyncio.wait_for(all_entered.wait(), 3)
        assert middleware.active_uploads == 4
        rejected = await invoke()
        assert rejected[0]["status"] == 429
        assert dict(rejected[0]["headers"])[b"retry-after"] == b"3"
        assert len(spools) == 4
        assert not any(spool.closed for spool in spools)
        release.set()
        completed = await asyncio.gather(*tasks)
        assert all(events[0]["status"] == 204 for events in completed)
        assert middleware.active_uploads == 0
        assert (await invoke())[0]["status"] == 204
        assert middleware.active_uploads == 0

    asyncio.run(scenario())
    assert all(spool.closed for spool in spools)


@pytest.mark.parametrize("ending", ["disconnect", "timeout", "exception", "cancel"])
def test_aborted_upload_releases_slot_and_temporary_file(monkeypatch, ending):
    spools = track_spools(monkeypatch)

    async def scenario():
        entered = asyncio.Event()
        hold = asyncio.Event()
        events = []

        async def send(event):
            events.append(event)

        async def receive():
            if ending == "disconnect":
                return {"type": "http.disconnect"}
            await hold.wait()

        async def downstream(scope, replay, send):
            assert ending in {"exception", "cancel"}
            if ending == "exception":
                raise RuntimeError("Synthetic downstream failure")
            entered.set()
            await hold.wait()

        middleware = RequestBodyLimitMiddleware(downstream, idle_timeout=0.02, upload_timeout=0.1)
        receiver = body_receiver([b"synthetic"]) if ending in {"exception", "cancel"} else receive
        task = asyncio.create_task(middleware(request_scope(), receiver, send))
        if ending == "cancel":
            await asyncio.wait_for(entered.wait(), 3)
            assert middleware.active_uploads == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif ending == "exception":
            with pytest.raises(RuntimeError, match="Synthetic downstream failure"):
                await task
        else:
            await task
        assert middleware.active_uploads == 0
        if ending == "timeout":
            assert events[0]["status"] == 408

    asyncio.run(scenario())
    assert len(spools) == 1 and spools[0].closed
