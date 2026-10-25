"""Diffing normalized OpenAPI documents."""

from .operations import diff_documents
from .schemas import SchemaDiff

__all__ = ["SchemaDiff", "diff_documents"]
