from contextvars import ContextVar


request_id_var = ContextVar("request_id", default="-")
tenant_schema_var = ContextVar("tenant_schema", default="public")
actor_id_var = ContextVar("actor_id", default="-")


def set_request_context(*, request_id: str, tenant_schema: str, actor_id: str):
    return (
        request_id_var.set(request_id),
        tenant_schema_var.set(tenant_schema),
        actor_id_var.set(actor_id),
    )


def reset_request_context(tokens) -> None:
    request_id_var.reset(tokens[0])
    tenant_schema_var.reset(tokens[1])
    actor_id_var.reset(tokens[2])


def get_request_context() -> dict[str, str]:
    return {
        "request_id": request_id_var.get(),
        "tenant_schema": tenant_schema_var.get(),
        "actor_id": actor_id_var.get(),
    }
