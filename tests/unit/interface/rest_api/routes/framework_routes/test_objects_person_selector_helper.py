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
Unit tests for the person selector's route helper of the CmdbObject routes

Pinned: the picker's parameters (defaults, every refusal); the delete refusal naming the readable blockers and counting
the rest; the write check's refusal answered with its own status; and the ISMS side of deleting a person or group -
the risk-owner refusal and the references cleared
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.errors.manager import BaseManagerGetError
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.framework.person_types.person_types_constants import (
    RISK_OWNER_OBJECT_CHECK_FAILED_MESSAGE,
    RISK_OWNER_OBJECT_DELETE_MESSAGE,
)
from cmdb.framework.person_selector.person_selector_constants import (
    DEFAULT_PICKER_LIMIT,
    MAX_PICKER_LIMIT,
    PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE,
    PersonPickerError,
)
from cmdb.framework.person_selector.selector_picker import PickerQuery
from cmdb.framework.person_selector.selector_write_rule import SelectorRefusal
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects import objects_person_selector_helper as module
# -------------------------------------------------------------------------------------------------------------------- #

VISIBLE_TYPE: int = 5
HIDDEN_TYPE: int = 6


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A bare app for the request context"""
    return Flask(__name__)


def _query(flask_app: Flask, query_string: str) -> PickerQuery:
    """Reads the picker parameters of the given query string"""
    with flask_app.test_request_context(f'/?{query_string}'):
        return module.read_picker_query()


def test_the_picker_defaults(flask_app: Flask) -> None:
    """Both kinds, page 1, the default limit, browsing"""
    assert _query(flask_app, '') == PickerQuery([SpecialType.PERSON, SpecialType.PERSON_GROUP], None, None, 1,
                                                DEFAULT_PICKER_LIMIT)


def test_the_picker_reads_every_parameter(flask_app: Flask) -> None:
    """kinds, search, ids, page, limit"""
    assert _query(flask_app, 'kinds=PERSON_GROUP&search=ops&ids=3,4&page=2&limit=5') == PickerQuery(
        [SpecialType.PERSON_GROUP], 'ops', [3, 4], 2, 5)


@pytest.mark.parametrize('query_string, message', [
    ('kinds=RACK', PersonPickerError.KINDS.value),
    ('kinds=', PersonPickerError.KINDS.value),
    ('ids=3,x', PersonPickerError.IDS.value),
    ('page=0', PersonPickerError.PAGE.value),
    ('page=one', PersonPickerError.PAGE.value),
    ('limit=0', PersonPickerError.LIMIT.format(maximum=MAX_PICKER_LIMIT)),
    (f'limit={MAX_PICKER_LIMIT + 1}', PersonPickerError.LIMIT.format(maximum=MAX_PICKER_LIMIT)),
], ids=['unknown-kind', 'no-kind', 'id-not-a-number', 'page-zero', 'page-text', 'limit-zero', 'limit-over'])
def test_an_unusable_parameter_is_a_400(flask_app: Flask, query_string: str, message: str) -> None:
    """Named"""
    with pytest.raises(HTTPException) as caught:
        _query(flask_app, query_string)

    assert (caught.value.code, caught.value.description) == (HTTPStatus.BAD_REQUEST, message)


def test_a_delete_blocker_is_named_only_when_readable() -> None:
    """The rest are counted"""
    blockers: list[tuple[int, int]] = [(11, VISIBLE_TYPE), (12, HIDDEN_TYPE), (13, VISIBLE_TYPE)]

    with patch.object(module, 'find_required_selector_blockers', return_value=blockers), \
            patch.object(module, 'hidden_types_of', return_value=lambda: frozenset({HIDDEN_TYPE})), \
            pytest.raises(HTTPException) as caught:
        module.guard_person_selector_delete(MagicMock(), MagicMock(), MagicMock(), [1])

    assert (caught.value.code, caught.value.description) == (
        HTTPStatus.BAD_REQUEST, PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE.format(object_ids=[11, 13], hidden=1))


def test_no_blocker_passes() -> None:
    """And reads no denied types"""
    hidden: Any = MagicMock()

    with patch.object(module, 'find_required_selector_blockers', return_value=[]), \
            patch.object(module, 'hidden_types_of', hidden):
        module.guard_person_selector_delete(MagicMock(), MagicMock(), MagicMock(), [1])

    hidden.assert_not_called()


@pytest.mark.parametrize('status', [HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN])
def test_the_write_refusal_keeps_its_status(status: HTTPStatus) -> None:
    """400 or 403, with its message"""
    with patch.object(module, 'check_person_selector_values', return_value=SelectorRefusal(status, 'refused')), \
            patch.object(module, 'hidden_types_of'), pytest.raises(HTTPException) as caught:
        module.validate_person_selector_values(MagicMock(), MagicMock(), MagicMock(), {}, MagicMock())

    assert (caught.value.code, caught.value.description) == (status, 'refused')


def test_only_persons_and_groups_can_be_selected() -> None:
    """By the type's marker - the held type, else the stored one - never the object's own"""
    types_manager: Any = MagicMock()
    types_manager.get_type.side_effect = lambda type_id: {20: {'special_type': 'PERSON_GROUP'},
                                                          30: {'special_type': 'RACK'}, 40: {'special_type': None}}.get(
        type_id)
    held: dict[int, Any] = {10: MagicMock(public_id=10, special_type='PERSON')}
    targets: list[dict[str, Any]] = [
        {'public_id': 1, 'type_id': 10, 'special_type': None},
        {'public_id': 2, 'type_id': 20, 'special_type': None},
        {'public_id': 3, 'type_id': 30, 'special_type': 'PERSON'},
        {'public_id': 4, 'type_id': 40, 'special_type': 'PERSON_GROUP'},
        {'public_id': 5, 'type_id': 20},
        {'public_id': 6, 'type_id': 99, 'special_type': 'PERSON'},
    ]

    assert module.selectable_target_ids(types_manager, targets, held) == [1, 2, 5]
    assert sorted(call.args[0] for call in types_manager.get_type.call_args_list) == [20, 30, 40, 99]


def test_a_held_type_is_not_read() -> None:
    """The delete routes hand every target's type"""
    types_manager: Any = MagicMock()

    assert module.selectable_target_ids(types_manager, [{'public_id': 1, 'type_id': 10}],
                                        {10: MagicMock(public_id=10, special_type='PERSON')}) == [1]
    types_manager.get_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the ISMS side of deleting a person or group                                       #
# -------------------------------------------------------------------------------------------------------------------- #
PERSON_DOCUMENT: dict[str, Any] = {'public_id': 21, 'special_type': SpecialType.PERSON.value}
GROUP_DOCUMENT: dict[str, Any] = {'public_id': 22, 'special_type': SpecialType.PERSON_GROUP.value}
PLAIN_DOCUMENT: dict[str, Any] = {'public_id': 23, 'special_type': None}


def test_a_risk_owner_among_the_targets_refuses_the_delete() -> None:
    """400 naming the person / group ids and the owned count"""
    with patch.object(module, 'count_owned_risk_assessments', return_value=2), pytest.raises(HTTPException) as caught:
        module.guard_person_risk_owner_delete(MagicMock(), [PLAIN_DOCUMENT, GROUP_DOCUMENT, PERSON_DOCUMENT])

    assert (caught.value.code, caught.value.description) == (
        HTTPStatus.BAD_REQUEST, RISK_OWNER_OBJECT_DELETE_MESSAGE.format(ids=[21, 22], count=2))


def test_a_selection_without_persons_counts_nothing() -> None:
    """No read for ordinary objects"""
    with patch.object(module, 'count_owned_risk_assessments') as count:
        module.guard_person_risk_owner_delete(MagicMock(), [PLAIN_DOCUMENT])

    count.assert_not_called()


def test_an_owner_count_that_fails_is_a_400() -> None:
    """Named, logged"""
    with patch.object(module, 'count_owned_risk_assessments', side_effect=BaseManagerGetError('down')), \
            pytest.raises(HTTPException) as caught:
        module.guard_person_risk_owner_delete(MagicMock(), [PERSON_DOCUMENT])

    assert caught.value.description == RISK_OWNER_OBJECT_CHECK_FAILED_MESSAGE.format(ids=[21])


def test_the_isms_references_are_cleared_for_the_deleted_persons_and_groups() -> None:
    """By kind; an ordinary object costs nothing"""
    manager = MagicMock()

    with patch.object(module, 'clear_isms_person_references') as clear:
        module.clear_deleted_from_isms(manager, [PERSON_DOCUMENT, PLAIN_DOCUMENT, GROUP_DOCUMENT])
        module.clear_deleted_from_isms(manager, [PLAIN_DOCUMENT])

    clear.assert_called_once_with(manager, {PersonReferenceType.PERSON: [21], PersonReferenceType.PERSON_GROUP: [22]})
