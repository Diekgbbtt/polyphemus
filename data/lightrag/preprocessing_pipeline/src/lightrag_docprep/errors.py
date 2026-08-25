class PreprocessorError(Exception):
    """Base error for document preprocessing."""


class UnsupportedSourceError(PreprocessorError):
    """Raised when no parser supports a source type."""


class ParserUnavailableError(PreprocessorError):
    """Raised when an optional parser dependency is unavailable."""


class ParserExecutionError(PreprocessorError):
    """Raised when a parser fails to process a document."""
