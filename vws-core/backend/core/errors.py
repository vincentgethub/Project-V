"""Typed failure vocabulary for R-02 fail-closed boundaries."""


class SafetyError(Exception):
    """R-02: a failure that callers must convert into a veto or halt."""

    def __init__(self, message: str) -> None:
        """R-07: never expose configured credentials in typed failures."""
        from backend.core.logging import redact

        super().__init__(str(redact(message)))


class ConfigurationError(SafetyError):
    """R-06/R-07: configuration cannot safely start the application."""


class DataIntegrityError(SafetyError):
    """R-02/DAT-02: a value is missing, malformed, or unverifiable."""


class StaleDataError(DataIntegrityError):
    """R-02/DAT-01: required data is too old for its trading session."""


class LedgerIntegrityError(SafetyError):
    """R-02: ledger references, invariants, or hash chains failed."""


class AppendOnlyError(LedgerIntegrityError):
    """R-02: an attempt was made to alter an immutable ledger row."""


class DatabaseError(SafetyError):
    """R-02: persistence failed and its outcome must not be assumed."""


class StateTransitionError(SafetyError):
    """R-02/R-09: a requested state transition is unauthorized."""


class ReconciliationError(LedgerIntegrityError):
    """R-02: observed broker holdings differ from ledger holdings."""


class CalendarError(SafetyError):
    """R-02/DAT-01: the exchange session cannot be verified."""


class LiquidityUnavailable(SafetyError):
    """R-02/CRO-12: required checking balance information is unavailable."""


class ProviderError(SafetyError):
    """R-02/DAT-04: an external read could not produce trusted data."""


class EgressDeniedError(ProviderError):
    """SEC-30/SEC-32: an outbound destination was refused and audited."""
