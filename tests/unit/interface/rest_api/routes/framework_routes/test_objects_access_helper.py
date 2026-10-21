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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_access_helper

``read_object_or_abort`` reads an object through the caller's READ ACL: a denied object is a 403 with the caller's
message, a missing one is a 404 only when the caller asks for it, and a read failure is passed on
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_access_helper import read_object_or_abort
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 42
STORED_OBJECT: dict[str, Any] = {'public_id': OBJECT_ID, 'type_id': 7}
DENIED_MESSAGE: str = 'denied-message'
MISSING_MESSAGE: str = 'missing-message'


def _reader() -> CmdbUser:
    """The caller"""
    return CmdbUser(public_id=5, user_name='reader', active=True, group_id=9)


def _objects_manager(found: Any = None, error: Exception | None = None) -> MagicMock:
    """An ObjectsManager stand-in answering ``found``, or raising ``error``"""
    manager = MagicMock()
    manager.get_object.return_value = found

    if error is not None:
        manager.get_object.side_effect = error

    return manager


class TestADeniedObject:
    """The caller's group may not read the object's type"""

    @pytest.mark.parametrize('missing_message', [None, MISSING_MESSAGE], ids=['no-404', 'with-404'])
    def test_is_a_403_with_the_callers_message(self, missing_message: str | None) -> None:
        """The message the caller passed, whether or not it asked for a 404"""
        with pytest.raises(HTTPException) as exc_info:
            read_object_or_abort(OBJECT_ID, _reader(), _objects_manager(error=AccessDeniedError('no')),
                                 DENIED_MESSAGE, missing_message)

        assert (exc_info.value.code, exc_info.value.description) == (403, DENIED_MESSAGE)


class TestAMissingObject:
    """No object with that id"""

    def test_answers_none_without_a_missing_message(self) -> None:
        """The logs' reading: a deleted object is no refusal"""
        assert read_object_or_abort(OBJECT_ID, _reader(), _objects_manager(), DENIED_MESSAGE) is None

    def test_is_a_404_with_a_missing_message(self) -> None:
        """The relation tabs' reading: no object, nothing to answer"""
        with pytest.raises(HTTPException) as exc_info:
            read_object_or_abort(OBJECT_ID, _reader(), _objects_manager(), DENIED_MESSAGE, MISSING_MESSAGE)

        assert (exc_info.value.code, exc_info.value.description) == (404, MISSING_MESSAGE)


class TestAReadableObject:
    """The caller may read it"""

    @pytest.mark.parametrize('missing_message', [None, MISSING_MESSAGE], ids=['no-404', 'with-404'])
    def test_answers_the_object_read_with_the_callers_acl(self, missing_message: str | None) -> None:
        """One read, as the caller, with READ"""
        reader = _reader()
        manager = _objects_manager(found=STORED_OBJECT)

        assert read_object_or_abort(OBJECT_ID, reader, manager, DENIED_MESSAGE, missing_message) == STORED_OBJECT
        manager.get_object.assert_called_once_with(OBJECT_ID, reader, AccessControlPermission.READ)


def test_a_failed_read_is_passed_on() -> None:
    """The caller decides what a failed read answers"""
    with pytest.raises(ObjectsManagerGetError):
        read_object_or_abort(OBJECT_ID, _reader(), _objects_manager(error=ObjectsManagerGetError('down')),
                             DENIED_MESSAGE)
