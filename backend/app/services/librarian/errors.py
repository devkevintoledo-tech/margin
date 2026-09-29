"""Typed failures the librarian routes map to HTTP statuses (spec §8)."""


class LibrarianError(Exception):
    status_code = 400

    def __init__(self, message: str, consequences: dict | None = None):
        super().__init__(message)
        self.message = message
        self.consequences = consequences


class NotFound(LibrarianError):
    status_code = 404


class Conflict(LibrarianError):
    """The subject changed underneath the request."""

    status_code = 409


class Invalid(LibrarianError):
    """Impossible or incomplete."""

    status_code = 422


class NeedsConfirmation(Invalid):
    """Merge and split answer with what they would do; the client confirms."""

    def __init__(self, message: str, consequences: dict):
        super().__init__(message, consequences)
