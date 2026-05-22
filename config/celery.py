from __future__ import annotations

import importlib.util
import os
from typing import Callable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def _passthrough_task(*task_args, **task_kwargs):
    def decorator(func: Callable):
        def delay(*args, **kwargs):
            return func(*args, **kwargs)

        def apply_async(args=None, kwargs=None, **options):
            return func(*(args or ()), **(kwargs or {}))

        func.delay = delay
        func.apply_async = apply_async
        func.task_options = task_kwargs
        return func

    if task_args and callable(task_args[0]) and len(task_args) == 1 and not task_kwargs:
        return decorator(task_args[0])
    return decorator


if importlib.util.find_spec("celery") is None:  # pragma: no cover - local fallback when Celery is not installed
    class CeleryStub:
        main = "config"

        def config_from_object(self, *args, **kwargs):
            return None

        def autodiscover_tasks(self, *args, **kwargs):
            return []

        task = staticmethod(_passthrough_task)


    app = CeleryStub()
else:  # pragma: no cover - exercised in runtime environments with Celery installed
    from celery import Celery

    app = Celery("config")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
