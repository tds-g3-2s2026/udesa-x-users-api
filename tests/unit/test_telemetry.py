import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from users_api.infrastructure.telemetry import export, instrument

CALLER_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
CALLER_TRACEPARENT = f"00-{CALLER_TRACE_ID}-00f067aa0ba902b7-01"


@pytest.fixture
def exporters():
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        logging.getLogger("users_api.test").info("inside the route", extra={"user_id": "42"})
        return {"ok": True}

    @app.get("/healthcheck")
    async def healthcheck():
        return {"status": "ok"}

    tracer_provider = instrument(app)
    logger_provider = export(tracer_provider, spans, logs)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    # The test client logs every call it makes, outside any request of the app.
    httpx_logger = logging.getLogger("httpx")
    previous_httpx_level = httpx_logger.level
    httpx_logger.setLevel(logging.WARNING)

    async def call(path: str, headers: dict[str, str] | None = None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path, headers=headers)
        tracer_provider.force_flush()
        return response

    def finished_logs():
        logger_provider.force_flush()
        return logs.get_finished_logs()

    yield call, spans, finished_logs

    root.setLevel(previous_level)
    httpx_logger.setLevel(previous_httpx_level)
    for handler in root.handlers[:]:
        if getattr(handler, "_logger_provider", None) is logger_provider:
            root.removeHandler(handler)
    logger_provider.shutdown()
    tracer_provider.shutdown()


def trace_ids(records) -> set[str]:
    return {format(r.log_record.trace_id, "032x") for r in records}


async def test_logs_carry_the_trace_id_of_the_caller(exporters):
    call, spans, finished_logs = exporters

    await call("/api/ping", headers={"traceparent": CALLER_TRACEPARENT})

    records = finished_logs()
    assert {r.log_record.body for r in records} >= {"inside the route", "GET /api/ping 200"}
    assert trace_ids(records) == {CALLER_TRACE_ID}
    assert {format(s.context.trace_id, "032x") for s in spans.get_finished_spans()} == {
        CALLER_TRACE_ID
    }


async def test_a_request_without_traceparent_starts_its_own_trace(exporters):
    call, spans, finished_logs = exporters

    await call("/api/ping")

    (trace_id,) = trace_ids(finished_logs())
    assert trace_id != f"{0:032x}"
    assert trace_id != CALLER_TRACE_ID


async def test_log_attributes_reach_the_exporter_as_fields(exporters):
    call, _, finished_logs = exporters

    await call("/api/ping")

    by_body = {r.log_record.body: r.log_record.attributes for r in finished_logs()}
    assert by_body["inside the route"]["user_id"] == "42"
    request = by_body["GET /api/ping 200"]
    assert request["http.response.status_code"] == 200
    assert request["url.path"] == "/api/ping"
    assert request["duration_ms"] >= 0


async def test_the_request_log_leaves_the_query_string_out(exporters):
    call, _, finished_logs = exporters

    await call("/api/ping?token=secret")

    exported = repr([(r.log_record.body, r.log_record.attributes) for r in finished_logs()])
    assert "secret" not in exported


async def test_probes_produce_no_span_and_no_request_log(exporters):
    call, spans, finished_logs = exporters

    await call("/healthcheck")

    assert spans.get_finished_spans() == ()
    assert finished_logs() == ()


async def test_the_sdk_own_logs_are_never_exported(exporters):
    # An export failure logged through the exporter that failed loops forever.
    _, _, finished_logs = exporters

    logging.getLogger("opentelemetry.exporter.otlp").warning("could not export")

    assert finished_logs() == ()
