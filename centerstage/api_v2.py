"""Compatibility import: V2 now uses the supported local FastAPI service.

The old Flask/YOLO prototype had incompatible routes and was never the active
CenterStage application. Use centerstage.app:create_app for new integrations.
"""
from .app import create_app

app = create_app()
