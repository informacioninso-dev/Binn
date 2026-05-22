class AccessResolutionError(Exception):
    """Base error for access resolution failures."""


class AccessDeniedError(AccessResolutionError):
    """Raised when the resolved access decision rejects the request."""


class InvalidSessionContextError(AccessResolutionError):
    """Raised when the current active context is inconsistent or incomplete."""
