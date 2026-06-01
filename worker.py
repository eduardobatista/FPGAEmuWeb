# Huey consumer entry point.
# Imports the huey instance and registers the tasks without triggering the
# full Flask application (main/__init__.py imports blueprints/routes which
# are not needed in the worker process).
import importlib.util
import sys
import os

from appp import huey  # noqa: F401  — creates the RedisHuey instance

# Load main/tasks.py directly, bypassing main/__init__.py
_tasks_path = os.path.join(os.path.dirname(__file__), "main", "tasks.py")
_spec = importlib.util.spec_from_file_location("main.tasks", _tasks_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["main.tasks"] = _mod
_spec.loader.exec_module(_mod)
