# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for the typed duplicate-key refusals in cmdb.errors.database
"""
import pytest

from cmdb.errors.database import (
    DataBaseError,
    DocumentDuplicateKeyError,
    DocumentInsertDuplicateKeyError,
    DocumentInsertError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    DocumentUpdateDuplicateKeyError,
    DocumentUpdateError,
    TRANSIENT_DATABASE_ERRORS,
)
# -------------------------------------------------------------------------------------------------------------------- #

KEY_PATTERN: dict[str, int] = {'object_id': 1, 'name': 1}
KEY_VALUE: dict[str, object] = {'object_id': 8802, 'name': 'Gi0/1'}


@pytest.mark.parametrize('refusal_class, operation_class', [
    (DocumentInsertDuplicateKeyError, DocumentInsertError),
    (DocumentUpdateDuplicateKeyError, DocumentUpdateError),
], ids=['insert', 'update'])
class TestTheTypedRefusals:
    """Each refusal is both: its operation's error for every existing caller, and the duplicate marker."""

    def test_it_is_still_the_operations_error(self, refusal_class, operation_class) -> None:
        """Every `except DocumentInsertError` / `DocumentUpdateError` keeps catching it."""
        assert isinstance(refusal_class('dup'), operation_class)

    def test_it_is_the_duplicate_marker(self, refusal_class, operation_class) -> None:
        """What find_cause looks for, whichever write raised it."""
        del operation_class
        assert isinstance(refusal_class('dup'), DocumentDuplicateKeyError)

    def test_it_carries_the_violated_index_and_the_value(self, refusal_class, operation_class) -> None:
        """So no caller reads them out of the message."""
        del operation_class
        refusal = refusal_class('dup', key_pattern=KEY_PATTERN, key_value=KEY_VALUE)

        assert refusal.key_pattern == KEY_PATTERN
        assert refusal.key_value == KEY_VALUE
        assert str(refusal) == 'dup'

    def test_it_copies_what_it_was_given(self, refusal_class, operation_class) -> None:
        """A caller mutating its dict afterwards does not change what the refusal reports."""
        del operation_class
        pattern = dict(KEY_PATTERN)
        refusal = refusal_class('dup', key_pattern=pattern)
        pattern.clear()

        assert refusal.key_pattern == KEY_PATTERN

    def test_what_was_not_reported_is_empty(self, refusal_class, operation_class) -> None:
        """Always dicts, so `key in refusal.key_pattern` never needs a None check."""
        del operation_class
        refusal = refusal_class('dup')

        assert refusal.key_pattern == {}
        assert refusal.key_value == {}


def test_the_transient_errors_are_exactly_the_two_retryable_ones() -> None:
    """The tuple every wrapping layer lets through - a third member would widen what escapes them all."""
    assert TRANSIENT_DATABASE_ERRORS == (DocumentLockTimeoutError, DocumentNetworkError)
    assert all(issubclass(error_class, DataBaseError) for error_class in TRANSIENT_DATABASE_ERRORS)
