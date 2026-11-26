"""Errors the repositories raise, so callers never handle the driver's own.

The database's error text for a duplicate contains the value that clashed
(an email, a token hash). It is never passed on, logged or returned.
"""


class DuplicateRow(Exception):
    """A row was refused because it would break a "must be unique" rule."""
