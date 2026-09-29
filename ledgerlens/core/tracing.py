"""OpenTelemetry setup. With no backend configured there is no provider, so every span is a no-op.

Spans use OpenInference conventions, so Phoenix (and other LLM trace viewers that read them)
render prompts, token counts, retrieved documents and sessions natively.
"""

import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from ledgerlens.core.config import Settings

log = logging.getLogger(__name__)

NEATLOGS_ENDPOINT = "ingest.neatlogs.com:443"


def setup_tracing(settings: Settings) -> TracerProvider | None:
    """Install the global tracer provider with one exporter per configured backend."""
    exporters = []
    if settings.phoenix_url:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporters.append(OTLPSpanExporter(endpoint=f"{settings.phoenix_url.rstrip('/')}/v1/traces"))
    if settings.neatlogs_api_key:
        # Neatlogs' documented OTLP path: gRPC, project key in the x-api-key header.
        # Untested here (no account); needs `uv sync --extra neatlogs`.
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )
        except ImportError:
            log.warning(
                "NEATLOGS_API_KEY is set but the exporter is missing: uv sync --extra neatlogs"
            )
        else:
            key = settings.neatlogs_api_key.get_secret_value()
            exporters.append(
                GrpcSpanExporter(endpoint=NEATLOGS_ENDPOINT, headers={"x-api-key": key})
            )
    if not exporters:
        return None

    from openinference.semconv.resource import ResourceAttributes
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": "ledgerlens", ResourceAttributes.PROJECT_NAME: settings.trace_project}
    )
    provider = TracerProvider(resource=resource)
    for exporter in exporters:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def trace_url(settings: Settings, trace_id: str | None) -> str | None:
    """A link that opens this trace in the Phoenix UI."""
    if not (settings.phoenix_url and trace_id):
        return None
    return f"{settings.phoenix_url.rstrip('/')}/redirects/traces/{trace_id}"


def shutdown_tracing(provider: TracerProvider | None) -> None:
    """Flush buffered spans. One-shot processes (CLI, evals) must call this before exiting."""
    if provider is not None:
        provider.shutdown()
