import logging

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from users_api.infrastructure.telemetry import (
    HTTP_DURATION_BUCKETS,
    SERVICE_INSTANCE_ID,
    create_meter_provider,
    export,
    instrument,
)

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


@pytest.fixture
def metrics():
    reader = InMemoryMetricReader()
    provider = create_meter_provider(reader)
    spans = InMemorySpanExporter()
    app = FastAPI()

    @app.get("/api/widgets/{widget_id}")
    async def widget(widget_id: str):
        if widget_id == "unavailable":
            raise HTTPException(status_code=503)
        return {"ok": True}

    @app.get("/api/crash")
    async def crash():
        raise RuntimeError("dependency failed")

    @app.get("/healthcheck")
    @app.get("/livez")
    async def probe():
        return {"status": "ok"}

    tracer_provider = instrument(app, provider)
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))

    async def call(path: str, traceparent: str = CALLER_TRACEPARENT):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            return await client.get(path, headers={"traceparent": traceparent})

    yield call, reader, spans

    provider.shutdown()
    tracer_provider.shutdown()


def exported_metrics(reader):
    data = reader.get_metrics_data()
    return (
        [
            metric
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        ]
        if data is not None
        else []
    )


async def test_http_metrics_use_seconds_template_routes_and_bounded_attributes(metrics):
    call, reader, _ = metrics

    await call("/api/widgets/private-id?token=secret")
    await call("/api/widgets/another-id")

    (metric,) = exported_metrics(reader)
    assert metric.name == "http.server.request.duration"
    assert metric.unit == "s"
    (point,) = metric.data.data_points
    assert point.attributes == {
        "http.request.method": "GET",
        "http.route": "/api/widgets/{widget_id}",
        "http.response.status_code": 200,
    }
    assert point.count == 2
    assert point.sum >= 0
    assert point.explicit_bounds == HTTP_DURATION_BUCKETS
    assert "secret" not in repr(point)
    assert "private-id" not in repr(point)


async def test_http_metrics_keep_error_responses_separate(metrics):
    call, reader, _ = metrics

    response = await call("/api/widgets/unavailable")

    assert response.status_code == 503
    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    assert point.attributes["http.response.status_code"] == 503
    assert point.count == 1


async def test_unhandled_failures_are_recorded_as_server_errors(metrics):
    call, reader, _ = metrics

    response = await call("/api/crash")

    assert response.status_code == 500
    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    assert point.attributes["http.response.status_code"] == 500
    assert point.count == 1


async def test_probe_paths_are_excluded_from_metrics_even_with_query_strings(metrics):
    call, reader, spans = metrics

    for path in ("/healthcheck", "/livez", "/healthcheck?token=secret", "/livez?probe=1"):
        await call(path)

    assert exported_metrics(reader) == []
    assert spans.get_finished_spans() == ()


@pytest.mark.parametrize("resource", ["healthcheck", "livez"])
async def test_nested_resource_names_are_not_excluded_as_probe_paths(metrics, resource):
    call, reader, spans = metrics

    response = await call(f"/api/widgets/{resource}?token=secret")

    assert response.status_code == 200
    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    assert point.attributes["http.route"] == "/api/widgets/{widget_id}"
    assert point.count == 1
    assert len(spans.get_finished_spans()) == 1


async def test_exemplars_reference_the_request_span_without_trace_labels(metrics):
    call, reader, spans = metrics

    await call("/api/widgets/42")

    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    (exemplar,) = point.exemplars
    (span,) = spans.get_finished_spans()
    assert exemplar.trace_id == int(CALLER_TRACE_ID, 16)
    assert exemplar.span_id == span.context.span_id
    assert "trace_id" not in point.attributes
    assert "span_id" not in point.attributes


async def test_unsampled_requests_are_measured_without_exemplars(metrics):
    call, reader, _ = metrics

    await call("/api/widgets/42", traceparent=f"00-{CALLER_TRACE_ID}-00f067aa0ba902b7-00")

    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    assert point.count == 1
    assert point.exemplars == []


async def test_unknown_paths_do_not_create_metric_series_from_the_url(metrics):
    call, reader, _ = metrics

    await call("/unknown-secret-path?token=private-token")

    (metric,) = exported_metrics(reader)
    (point,) = metric.data.data_points
    assert point.attributes["http.response.status_code"] == 404
    assert "http.route" not in point.attributes
    assert "unknown-secret-path" not in repr(point)
    assert "private-token" not in repr(point)


def test_metrics_and_traces_share_the_process_identity():
    reader = InMemoryMetricReader()
    provider = create_meter_provider(reader)
    spans = InMemorySpanExporter()
    app = FastAPI()
    tracer_provider = instrument(app, provider)
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    try:
        provider.get_meter("test").create_histogram(
            "http.server.request.duration", unit="s"
        ).record(1)
        with tracer_provider.get_tracer("test").start_as_current_span("request"):
            pass
        (resource,) = reader.get_metrics_data().resource_metrics
        (span,) = spans.get_finished_spans()
        assert resource.resource.attributes["service.instance.id"] == SERVICE_INSTANCE_ID
        assert resource.resource == span.resource
    finally:
        provider.shutdown()
        tracer_provider.shutdown()
