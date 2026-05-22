from __future__ import annotations

import importlib.util
from typing import Callable


CELERY_RUNTIME_AVAILABLE = importlib.util.find_spec("celery") is not None


def _attach_local_task_api(func: Callable, task_kwargs: dict):
    def delay(*args, **kwargs):
        return func(*args, **kwargs)

    def apply_async(args=None, kwargs=None, **options):
        return func(*(args or ()), **(kwargs or {}))

    func.delay = delay
    func.apply_async = apply_async
    func.task_options = task_kwargs
    return func


if CELERY_RUNTIME_AVAILABLE:  # pragma: no cover - direct Celery integration is runtime-bound
    from celery import shared_task as shared_task
else:
    def shared_task(*task_args, **task_kwargs):
        def decorator(func: Callable):
            return _attach_local_task_api(func, task_kwargs)

        if task_args and callable(task_args[0]) and len(task_args) == 1 and not task_kwargs:
            return decorator(task_args[0])
        return decorator
