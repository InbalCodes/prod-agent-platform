"""Provider-neutral LLM errors.

Adapters translate SDK exceptions into these, so callers decide retry/fallback policy
from `retryable` without knowing which provider is behind the client.
"""


class LLMError(Exception):
    retryable: bool = False


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRateLimitError(LLMError):
    retryable = True

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMUnavailableError(LLMError):
    """Provider 5xx / overloaded / connection failure."""

    retryable = True


class LLMRequestError(LLMError):
    """The request itself is wrong (4xx other than 429): a bug or misconfiguration."""


class LLMOutputError(LLMError):
    """The call succeeded but produced no usable output (refusal, truncated, unparseable)."""
