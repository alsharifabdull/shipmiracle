"""shipmiracle: the small stdlib-only core of the Shipmiracle (Python 3.9). Errors carry the CLI exit code."""
from __future__ import annotations

__version__ = "0.1.0"


class ShipmiracleError(Exception):
    exit_code = 1


class UsageError(ShipmiracleError):
    """Bad input from the caller (name, key, value, size)."""
    exit_code = 2


class NotFound(ShipmiracleError):
    exit_code = 3


class SafetyError(ShipmiracleError):
    """Isolation, ownership, symlink or foreign-uid refusal."""
    exit_code = 4


class LockTimeout(ShipmiracleError):
    pass


class SchemaError(ShipmiracleError):
    """A stored file does not have the expected shape."""
