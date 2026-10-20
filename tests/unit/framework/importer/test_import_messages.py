# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the import result message wrappers

DB-free: these are data holders serialized to JSON via their ``__dict__`` (the app encoder's
fallback). Focus: the stored attributes, the ImportMessage base wiring, and that error_message is
coerced to a readable string so exceptions do not serialize as an empty object.
"""
from cmdb.framework.importer.messages.import_message import ImportMessage
from cmdb.framework.importer.messages.import_success_message import ImportSuccessMessage
from cmdb.framework.importer.messages.import_failed_message import ImportFailedMessage
from cmdb.framework.importer.messages.response_failed_message import ResponseFailedMessage
# -------------------------------------------------------------------------------------------------------------------- #


class TestImportMessage:
    """The base message wrapper."""

    def test_stores_obj(self) -> None:
        """The wrapped object dict is stored."""
        assert ImportMessage(obj={'x': 1}).obj == {'x': 1}

    def test_obj_defaults_to_none(self) -> None:
        """Omitting obj leaves it None."""
        assert ImportMessage().obj is None


class TestImportSuccessMessage:
    """The success message carries the assigned public_id."""

    def test_stores_public_id_and_obj(self) -> None:
        """public_id and the wrapped object are stored (obj via the base)."""
        message = ImportSuccessMessage(public_id=42, obj={'x': 1})

        assert message.public_id == 42
        assert message.obj == {'x': 1}
        assert isinstance(message, ImportMessage)


class TestImportFailedMessage:
    """The failure message carries the provided object and the list of reasons it failed."""

    def test_stores_failed_object_and_errors(self) -> None:
        """The provided object and its error list are stored (serialize to {failed_object, errors})."""
        message = ImportFailedMessage(failed_object={'x': 1}, errors=['bad row', 'and another'])

        assert message.failed_object == {'x': 1}
        assert message.errors == ['bad row', 'and another']

    def test_serializes_to_failed_object_and_errors(self) -> None:
        """Its __dict__ (how it is JSON-encoded) is exactly {failed_object, errors}."""
        message = ImportFailedMessage(failed_object={'public_id': 5}, errors=["Invalid value for 'active'"])

        assert message.__dict__ == {'failed_object': {'public_id': 5}, 'errors': ["Invalid value for 'active'"]}


class TestResponseFailedMessage:
    """The multi-response failure message."""

    def test_stores_all_fields(self) -> None:
        """status, public_id, error_message and obj are stored."""
        message = ResponseFailedMessage(error_message='nope', status=400, public_id=7, obj={'x': 1})

        assert message.status == 400
        assert message.public_id == 7
        assert message.error_message == 'nope'
        assert message.obj == {'x': 1}

    def test_defaults(self) -> None:
        """public_id and obj default to None."""
        message = ResponseFailedMessage(error_message='nope', status=500)

        assert message.public_id is None
        assert message.obj is None

    def test_exception_error_message_is_coerced_to_text(self) -> None:
        """An exception reason is coerced to its string text — B1."""
        message = ResponseFailedMessage(error_message=KeyError('k'), status=400)

        assert message.error_message == "'k'"
        assert isinstance(message.error_message, str)
