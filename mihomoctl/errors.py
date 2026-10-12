"""Error hierarchy with stable machine-readable codes.

Exit-code mapping (architecture-v1):
  0 success; 1 observed failure / health block; 2 usage / permission / unverified.
"""


class MihomoctlError(Exception):
    """Base error. ``code`` is kebab-case and stable; ``exit_code`` in {1, 2}."""

    exit_code = 2
    code = "error"

    def __init__(self, code=None, detail=None, remediation=None):
        self.code = code or self.code
        self.detail = detail
        self.remediation = remediation
        super().__init__(self.render())

    def render(self):
        text = self.code
        if self.detail:
            text += ": " + str(self.detail)
        if self.remediation:
            text += " (" + self.remediation + ")"
        return text


class UsageError(MihomoctlError):
    code = "usage-error"


class PermissionScopeError(MihomoctlError):
    """Scope violation: root mutation without --system, user touching system, ..."""

    code = "scope-violation"


class ConfigError(MihomoctlError):
    code = "config-invalid"


class ValidationError(MihomoctlError):
    """Candidate configuration failed validation."""

    code = "validation-failed"


class NotFoundError(MihomoctlError):
    code = "not-found"


class StateError(MihomoctlError):
    code = "state-invalid"


class ObservedStateError(StateError):
    """An observed runtime failure (occupied port, dead start, leftover
    listener): exit 1, distinct from usage/permission/unverified (2)."""

    exit_code = 1
    code = "observed-state-failure"


class HealthBlockedError(MihomoctlError):
    """Local health not confirmed; fail-closed gate refuses the action."""

    exit_code = 1
    code = "health-blocked"


class TransactionError(MihomoctlError):
    code = "transaction-failed"


class RollbackFailedError(TransactionError):
    """Rollback itself failed: highest-priority distinct report."""

    code = "rollback-failed"


class LockError(MihomoctlError):
    code = "operation-in-progress"


class SupplyChainError(MihomoctlError):
    code = "supply-chain-check-failed"


class IntegrationError(MihomoctlError):
    code = "integration-error"
