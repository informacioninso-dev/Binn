import logging

from .request_context import get_request_context


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.request_id = getattr(record, "request_id", context["request_id"])
        record.tenant_schema = getattr(record, "tenant_schema", context["tenant_schema"])
        record.actor_id = getattr(record, "actor_id", context["actor_id"])
        return True
