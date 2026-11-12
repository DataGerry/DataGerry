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
Unit tests for the object-relation history read rule: a CmdbObjectRelationLog is as readable as the relation it
records

Pure tests: the manager is a stub. Pinned:

  - ``read_object_relation_log_or_abort`` answers the stored log, a 404 for a missing one and a 403 for one with a
    denied type at either end; a side with no type stamped (or a log written before the stamp) is not refused
  - the log keys the rule reads are the relation's own keys, so the shared condition and check judge a log unchanged
  - the object-delete cascade reads back both type ids, so its DELETE entries are stamped like every other
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.log_model import ObjectRelationLogKey
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE,
)
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import read_object_relation_log_or_abort
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    RELATION_DELETE_LOG_PROJECTION,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOG_ID: int = 61
PARENT_TYPE_ID: int = 91
CHILD_TYPE_ID: int = 92
DENIED_TYPE_ID: int = 93
OTHER_DENIED_TYPE_ID: int = 94
DENIED: list[int] = [DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID]


def _stored(parent_type_id: int | None = PARENT_TYPE_ID, child_type_id: int | None = CHILD_TYPE_ID) -> dict[str, Any]:
    """A stored relation log with the given stamped types"""
    return {
        ObjectRelationLogKey.PUBLIC_ID.value: LOG_ID,
        ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value: parent_type_id,
        ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value: child_type_id,
    }


def _reading(document: dict[str, Any] | None) -> MagicMock:
    """An ObjectRelationLogsManager whose single read answers the given document"""
    manager = MagicMock()
    manager.get_object_relation_log.return_value = document

    return manager


class TestReadObjectRelationLogOrAbort:
    """The entry of the log read and the log delete"""

    def test_a_readable_log_is_answered(self) -> None:
        """As stored, read by its id"""
        manager = _reading(_stored())

        assert read_object_relation_log_or_abort(manager, LOG_ID, DENIED) == _stored()
        manager.get_object_relation_log.assert_called_once_with(LOG_ID)

    def test_a_missing_log_is_a_404_naming_it(self) -> None:
        """Before any ACL judgement"""
        with pytest.raises(HTTPException) as caught:
            read_object_relation_log_or_abort(_reading(None), LOG_ID, DENIED)

        assert caught.value.code == HTTPStatus.NOT_FOUND
        assert caught.value.description == OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE.format(public_id=LOG_ID)

    @pytest.mark.parametrize('parent_type_id, child_type_id', [
        (DENIED_TYPE_ID, CHILD_TYPE_ID), (PARENT_TYPE_ID, OTHER_DENIED_TYPE_ID), (DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID),
    ], ids=['parent-denied', 'child-denied', 'both-denied'])
    def test_a_denied_type_at_either_end_is_a_403_naming_it(self, parent_type_id: int, child_type_id: int) -> None:
        """The less readable of the two objects decides"""
        with pytest.raises(HTTPException) as caught:
            read_object_relation_log_or_abort(_reading(_stored(parent_type_id, child_type_id)), LOG_ID, DENIED)

        assert caught.value.code == HTTPStatus.FORBIDDEN
        assert caught.value.description == OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE.format(public_id=LOG_ID)

    def test_a_side_without_a_stamped_type_is_not_refused(self) -> None:
        """A type that could not be recovered is null, which the rule does not refuse"""
        document: dict[str, Any] = _stored(None, None)

        assert read_object_relation_log_or_abort(_reading(document), LOG_ID, DENIED) == document

    def test_a_log_written_before_the_stamp_is_not_refused(self) -> None:
        """No key at all reads like null"""
        document: dict[str, Any] = {ObjectRelationLogKey.PUBLIC_ID.value: LOG_ID}

        assert read_object_relation_log_or_abort(_reading(document), LOG_ID, DENIED) == document

    def test_with_nothing_denied_every_log_is_answered(self) -> None:
        """The admin's case"""
        document: dict[str, Any] = _stored(DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID)

        assert read_object_relation_log_or_abort(_reading(document), LOG_ID, []) == document


def test_the_log_stores_the_types_under_the_relations_own_keys() -> None:
    """What lets the relation's readable condition and check judge a log unchanged"""
    assert ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value == ObjectRelationKey.RELATION_PARENT_TYPE_ID.value
    assert ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value == ObjectRelationKey.RELATION_CHILD_TYPE_ID.value


def test_the_object_delete_cascade_reads_back_both_types() -> None:
    """Without them its DELETE entries would be the one unstamped kind of entry"""
    assert RELATION_DELETE_LOG_PROJECTION[ObjectRelationKey.RELATION_PARENT_TYPE_ID.value] == 1
    assert RELATION_DELETE_LOG_PROJECTION[ObjectRelationKey.RELATION_CHILD_TYPE_ID.value] == 1
