from collections import deque
from datetime import datetime, timezone
import json
import logging
import sys
import threading
from typing import Any, Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from .config import settings

logger = logging.getLogger("dispute_agent")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(_handler)


class InMemorySpanBuffer(SpanExporter):
    """Stores recent OpenTelemetry spans in memory for self-contained cluster diagnostics."""

    def __init__(self, maxlen: int = 600):
        self._spans: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            for sp in spans:
                ctx = sp.get_span_context()
                parent = sp.parent
                duration_ms = 0.0
                if sp.start_time and sp.end_time:
                    duration_ms = round((sp.end_time - sp.start_time) / 1_000_000, 2)
                self._spans.appendleft(
                    {
                        "trace_id": format(ctx.trace_id, "032x"),
                        "span_id": format(ctx.span_id, "016x"),
                        "parent_span_id": format(parent.span_id, "016x") if parent else None,
                        "name": sp.name,
                        "duration_ms": duration_ms,
                        "status": sp.status.status_code.name,
                        "attributes": dict(sp.attributes or {}),
                        "start_time_ns": sp.start_time,
                    }
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def recent(self, limit: int = 120, trace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._spans)
        if trace_id:
            items = [s for s in items if s["trace_id"] == trace_id]
        return items[:limit]


SPAN_BUFFER = InMemorySpanBuffer()

_provider = TracerProvider(
    resource=Resource.create(
        {
            "service.name": settings.SERVICE_NAME,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
)
_provider.add_span_processor(SimpleSpanProcessor(SPAN_BUFFER))

if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        otlp_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        _provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception as exc:
        logger.warning(json.dumps({"event": "otlp_exporter_init_failed", "error": str(exc)}))

trace.set_tracer_provider(_provider)
tracer = trace.get_tracer("meridian.dispute.agent")


class PrometheusRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.http_requests_total: dict[str, int] = {}
        self.triage_runs_total: int = 0
        self.triage_duration_ms_values: deque[float] = deque(maxlen=500)
        self.tool_calls_total: dict[str, int] = {}
        self.downstream_http_calls_total: dict[str, int] = {}
        self.rag_queries_total: int = 0

    def inc_http(self, method: str, path: str, status: int) -> None:
        key = f'{method}|{path}|{status}'
        with self._lock:
            self.http_requests_total[key] = self.http_requests_total.get(key, 0) + 1

    def record_triage(self, duration_ms: float) -> None:
        with self._lock:
            self.triage_runs_total += 1
            self.triage_duration_ms_values.append(duration_ms)

    def inc_tool(self, tool_name: str) -> None:
        with self._lock:
            self.tool_calls_total[tool_name] = self.tool_calls_total.get(tool_name, 0) + 1

    def inc_downstream(self, endpoint: str, status: int) -> None:
        key = f"{endpoint}|{status}"
        with self._lock:
            self.downstream_http_calls_total[key] = self.downstream_http_calls_total.get(key, 0) + 1

    def inc_rag(self) -> None:
        with self._lock:
            self.rag_queries_total += 1

    def render_prometheus(self) -> str:
        with self._lock:
            lines = [
                "# HELP dispute_agent_triage_runs_total Total automated dispute triage runs",
                "# TYPE dispute_agent_triage_runs_total counter",
                f"dispute_agent_triage_runs_total {self.triage_runs_total}",
                "# HELP dispute_agent_rag_queries_total Total policy retrieval executions",
                "# TYPE dispute_agent_rag_queries_total counter",
                f"dispute_agent_rag_queries_total {self.rag_queries_total}",
            ]
            if self.triage_duration_ms_values:
                vals = sorted(self.triage_duration_ms_values)
                p50 = vals[int(len(vals) * 0.50)]
                p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
                avg = sum(vals) / len(vals)
            else:
                p50 = p95 = avg = 0.0
            lines.extend(
                [
                    "# HELP dispute_agent_triage_latency_ms Summary latency of triage runs in milliseconds",
                    "# TYPE dispute_agent_triage_latency_ms gauge",
                    f'dispute_agent_triage_latency_ms{{quantile="0.5"}} {round(p50, 2)}',
                    f'dispute_agent_triage_latency_ms{{quantile="0.95"}} {round(p95, 2)}',
                    f'dispute_agent_triage_latency_ms_avg {round(avg, 2)}',
                ]
            )
            lines.append("# HELP dispute_agent_tool_calls_total Agent tool invocations by name")
            lines.append("# TYPE dispute_agent_tool_calls_total counter")
            for tool, cnt in sorted(self.tool_calls_total.items()):
                lines.append(f'dispute_agent_tool_calls_total{{tool="{tool}"}} {cnt}')

            lines.append("# HELP dispute_agent_downstream_calls_total Downstream core-ledger calls by status")
            lines.append("# TYPE dispute_agent_downstream_calls_total counter")
            for key, cnt in sorted(self.downstream_http_calls_total.items()):
                ep, code = key.split("|", 1)
                lines.append(f'dispute_agent_downstream_calls_total{{endpoint="{ep}",status="{code}"}} {cnt}')

            lines.append("# HELP dispute_agent_http_requests_total Inbound HTTP requests")
            lines.append("# TYPE dispute_agent_http_requests_total counter")
            for key, cnt in sorted(self.http_requests_total.items()):
                method, path, code = key.split("|", 2)
                lines.append(
                    f'dispute_agent_http_requests_total{{method="{method}",path="{path}",status="{code}"}} {cnt}'
                )
            return "\n".join(lines) + "\n"


METRICS = PrometheusRegistry()


def log_event(event: str, **fields: Any) -> None:
    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    trace_id = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "service": settings.SERVICE_NAME,
        "env": settings.ENVIRONMENT,
        "event": event,
        "trace_id": trace_id,
        **fields,
    }
    logger.info(json.dumps(record, default=str))
