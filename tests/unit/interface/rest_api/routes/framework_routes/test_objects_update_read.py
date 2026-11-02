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
Unit tests for cmdb_objects.objects_update_read - the reads of an object update

The target is read once, raw; the object is built from a copy so the raw document stays the ledger's snapshot; the
type comes from the request's cache; the read check uses that type; failures are the manager's own errors
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.security import AccessDeniedError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_update_read import (
    UpdateTarget,
    read_stored_object,
    read_update_target,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
# -------------------------------------------------------------------------------------------------------------------- #

READ_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_update_read'
OBJECT_ID: int = 5
TYPE_ID: int = 3
HTTP_NOT_FOUND: int = 404
HTTP_INTERNAL_SERVER_ERROR: int = 500


def _document() -> dict[str, Any]:
    """A stored object document as the database answers it"""
    return {'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'author_id': 1, 'version': '1.0.0', 'active': True,
            'fields': [{'name': 'a', 'value': 1}]}


def _context(document: dict[str, Any] | None, type_cache: dict[int, Any] | None = None) -> ObjectWriteContext:
    """A context whose objects manager answers this document"""
    objects_manager = MagicMock()
    objects_manager.get_one.return_value = document

    return ObjectWriteContext(SimpleNamespace(public_id=1), objects_manager, MagicMock(), MagicMock(),
                              **({} if type_cache is None else {'type_cache': type_cache}))


class TestReadUpdateTarget:
    """One read of the target, its type from the cache, the read check on that type"""

    def test_a_cached_type_costs_no_type_read(self) -> None:
        """The second target of a bulk update"""
        cached = MagicMock()
        context = _context(_document(), {TYPE_ID: cached})

        with patch(f'{READ_PATH}.verify_access') as verify:
            target = read_update_target(OBJECT_ID, context)

        assert target.current_type is cached
        context.objects_manager.get_object_type.assert_not_called()
        verify.assert_called_once()
        assert verify.call_args.args[0] is cached

    def test_the_raw_document_is_left_untouched(self) -> None:
        """It is the write ledger's snapshot - the object is built from a copy"""
        document = _document()
        context = _context(document, {TYPE_ID: MagicMock()})

        with patch(f'{READ_PATH}.verify_access'):
            target = read_update_target(OBJECT_ID, context)

        assert target.stored_document is document
        assert document == _document()
        assert target.current_object.get_public_id() == OBJECT_ID

    def test_the_target_is_read_once(self) -> None:
        """No get_object - the raw read is the only object read"""
        context = _context(_document(), {TYPE_ID: MagicMock()})

        with patch(f'{READ_PATH}.verify_access'):
            read_update_target(OBJECT_ID, context)

        context.objects_manager.get_one.assert_called_once_with(OBJECT_ID)
        context.objects_manager.get_object.assert_not_called()

    def test_a_missing_object_is_a_404(self) -> None:
        """Before any type is read"""
        context = _context(None)

        with pytest.raises(HTTPException) as exc_info:
            read_update_target(OBJECT_ID, context)

        assert exc_info.value.code == HTTP_NOT_FOUND
        context.objects_manager.get_object_type.assert_not_called()

    def test_a_missing_type_is_a_500(self) -> None:
        """An object whose type is gone"""
        context = _context(_document())
        context.objects_manager.get_object_type.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            read_update_target(OBJECT_ID, context)

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR

    def test_a_denied_type_raises_access_denied(self) -> None:
        """The routes answer it 403, as for get_object"""
        context = _context(_document(), {TYPE_ID: MagicMock()})

        with patch(f'{READ_PATH}.verify_access', side_effect=AccessDeniedError('no')), \
                pytest.raises(AccessDeniedError):
            read_update_target(OBJECT_ID, context)

    def test_an_unreadable_document_is_the_managers_get_error(self) -> None:
        """A document the model cannot build"""
        context = _context({'public_id': OBJECT_ID})

        with pytest.raises(ObjectsManagerGetError):
            read_update_target(OBJECT_ID, context)

    def test_it_answers_an_update_target(self) -> None:
        """The three parts, named"""
        context = _context(_document(), {TYPE_ID: MagicMock()})

        with patch(f'{READ_PATH}.verify_access'):
            assert isinstance(read_update_target(OBJECT_ID, context), UpdateTarget)


class TestReadStoredObject:
    """The raw read, the database's failure as the manager's own"""

    def test_the_raw_document_comes_back(self) -> None:
        """As stored"""
        objects_manager = MagicMock()
        objects_manager.get_one.return_value = _document()

        assert read_stored_object(objects_manager, OBJECT_ID) == _document()

    def test_a_failed_read_is_the_managers_get_error(self) -> None:
        """Carried as the cause"""
        objects_manager = MagicMock()
        failure = BaseManagerGetError('lost')
        objects_manager.get_one.side_effect = failure

        with pytest.raises(ObjectsManagerGetError) as exc_info:
            read_stored_object(objects_manager, OBJECT_ID)

        assert exc_info.value.args[0] is failure
