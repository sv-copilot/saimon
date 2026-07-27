# research_shared — shared library for the Saimon Platform
#
# Six modules (envelope, llm, db, auth, resilience, audit) consumed by
# all MCP services. Each module is self-contained with no cross-MCP
# coupling.

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabaseConfig, DatabaseError, DatabasePool
from research_shared.envelope import (
    ErrorCode,
    ResearchRequest,
    ResearchResponse,
    SourceReference,
)
from research_shared.llm import LLMClient, LLMConfig, LLMError
from research_shared.resilience import CircuitBreaker, RetryConfig, retry

__all__ = [
    "AuditLogger",
    "AuthConfig",
    "AuthError",
    "AuthValidator",
    "CircuitBreaker",
    "DatabaseConfig",
    "DatabaseError",
    "DatabasePool",
    "ErrorCode",
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "ResearchRequest",
    "ResearchResponse",
    "RetryConfig",
    "SourceReference",
    "retry",
]
