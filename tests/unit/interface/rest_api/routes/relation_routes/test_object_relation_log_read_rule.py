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
    denied type at either end; a side with no type stamped (or a log written before the stamp) is not refused while
    Types are only listed
  - with every Type restricted (the complement form), a side stamped with a gone Type or with none is refused, and
    the list condition admits only the granted Types on both keys - null and missing out
  - the log keys the rule reads are the relation's own keys, so the shared condition and check judge a log unchanged
  - the object-delete cascade reads back both type ids, so its DELETE entries are stamped like every other
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.access_engine import DeniedTypes
from cmdb.models.log_model import ObjectRelationLogKey
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE,
)
from cmdb.interface.rest_api.routes.relation_routes import relation_log_access
from cmdb.interface.rest_api.routes.relation_routes.relation_log_access import (
    read_log_denial_or_abort,
    read_object_relation_log_or_abort,
    readable_log_condition,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    RELATION_DELETE_LOG_PROJECTION,
)

from cmdb.errors.manager import BaseManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOG_ID: int = 61
PARENT_TYPE_ID: int = 91
CHILD_TYPE_ID: int = 92
DENIED_TYPE_ID: int = 93
OTHER_DENIED_TYPE_ID: int = 94
GONE_TYPE_ID: int = 95
DENIED: DeniedTypes = DeniedTypes(ids=frozenset({DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID}))
# An every-Type role: only the two granted Types are admitted
ADMITTING: DeniedTypes = DeniedTypes(admitted=frozenset({PARENT_TYPE_ID, CHILD_TYPE_ID}))


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

        assert read_object_relation_log_or_abort(_reading(document), LOG_ID, DeniedTypes()) == document

    def test_every_type_restricted_answers_a_log_of_two_admitted_types(self) -> None:
        """The complement admits the granted Types"""
        assert read_object_relation_log_or_abort(_reading(_stored()), LOG_ID, ADMITTING) == _stored()

    @pytest.mark.parametrize('document', [
        _stored(GONE_TYPE_ID, CHILD_TYPE_ID),
        _stored(PARENT_TYPE_ID, None),
        {ObjectRelationLogKey.PUBLIC_ID.value: LOG_ID},
    ], ids=['gone-parent', 'null-child', 'unstamped'])
    def test_every_type_restricted_refuses_a_side_of_a_gone_type_or_none(self, document: dict[str, Any]) -> None:
        """History of a Type that is not admitted - gone or unknown - is hidden like its objects"""
        with pytest.raises(HTTPException) as caught:
            read_object_relation_log_or_abort(_reading(document), LOG_ID, ADMITTING)

        assert caught.value.code == HTTPStatus.FORBIDDEN


class TestReadableLogCondition:
    """The list's twin of the single-read rule"""

    def test_nothing_denied_is_no_condition(self) -> None:
        """No filter at all"""
        assert not readable_log_condition(DeniedTypes())

    def test_listed_types_are_excluded_on_both_keys(self) -> None:
        """A null side passes $nin"""
        assert readable_log_condition(DENIED) == {
            ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value: {'$nin': [DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID]},
            ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value: {'$nin': [DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID]},
        }

    def test_every_type_restricted_admits_on_both_keys(self) -> None:
        """A null, missing or gone side matches no $in"""
        assert readable_log_condition(ADMITTING) == {
            ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value: {'$in': [PARENT_TYPE_ID, CHILD_TYPE_ID]},
            ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value: {'$in': [PARENT_TYPE_ID, CHILD_TYPE_ID]},
        }


class TestReadLogDenialOrAbort:
    """The input of every relation-log rule"""

    def test_the_denial_is_the_callers_for_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """As the access engine holds it"""
        resolve = MagicMock(return_value=ADMITTING)
        monkeypatch.setattr(relation_log_access, 'resolve_denied_types', resolve)
        request_user = MagicMock()

        assert read_log_denial_or_abort(request_user) is ADMITTING
        resolve.assert_called_once_with(request_user, AccessControlPermission.READ)

    def test_an_unreadable_grant_is_a_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The relation routes' lookup-failed answer"""
        monkeypatch.setattr(relation_log_access, 'resolve_denied_types',
                            MagicMock(side_effect=BaseManagerGetError('down')))

        with pytest.raises(HTTPException) as caught:
            read_log_denial_or_abort(MagicMock())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert caught.value.description == OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE


def test_the_log_stores_the_types_under_the_relations_own_keys() -> None:
    """What lets the relation's readable condition and check judge a log unchanged"""
    assert ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value == ObjectRelationKey.RELATION_PARENT_TYPE_ID.value
    assert ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value == ObjectRelationKey.RELATION_CHILD_TYPE_ID.value


def test_the_object_delete_cascade_reads_back_both_types() -> None:
    """Without them its DELETE entries would be the one unstamped kind of entry"""
    assert RELATION_DELETE_LOG_PROJECTION[ObjectRelationKey.RELATION_PARENT_TYPE_ID.value] == 1
    assert RELATION_DELETE_LOG_PROJECTION[ObjectRelationKey.RELATION_CHILD_TYPE_ID.value] == 1
