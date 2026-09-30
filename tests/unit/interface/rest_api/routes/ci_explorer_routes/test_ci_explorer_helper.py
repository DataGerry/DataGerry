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
Unit tests for the CI Explorer route helpers

Pure tests with stub callables: load_ci_explorer_entity aborts 404 for an unknown entity and otherwise
reports the entity plus the field's previous value. flask.abort raises a werkzeug HTTPException, so
the status codes are asserted without a Flask app context, and the request schema is checked against a
real Cerberus Validator.
"""
from http import HTTPStatus
from typing import Any
import pytest
from cerberus import Validator
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from unittest.mock import Mock

from cmdb.models.ci_explorer_model import CiExplorerProfileKey
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import PROFILE_FILTER_UNKNOWN_IDS_MSG
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_helper import (
    abort_if_profile_filters_name_unknown_ids,
    find_unknown_ids,
    get_ci_explorer_label_schema,
    load_ci_explorer_entity,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
LABEL_KEY: str = TypeSchemaKey.CI_EXPLORER_LABEL.value
LABEL_VALUE: str = 'hostname'
PREVIOUS_LABEL: str = 'serial'
ENTITY_LABEL: str = 'Type'


class TestLoadCiExplorerEntity:
    """
    load_ci_explorer_entity resolves the entity a field write targets

    Only the label field route uses it, but the entity and the field it reads are both parameters - it
    answers 404 for whatever it is pointed at.
    """

    def test_missing_entity_aborts_404(self) -> None:
        """An unknown public_id is a 404 naming the entity."""
        with pytest.raises(HTTPException) as exc_info:
            load_ci_explorer_entity(lambda _id: None, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL)

        assert exc_info.value.code == HTTPStatus.NOT_FOUND

    def test_returns_the_entity_and_the_previous_value(self) -> None:
        """The entity is returned together with what the field held before."""
        entity: dict[str, Any] = {'public_id': PUBLIC_ID, LABEL_KEY: PREVIOUS_LABEL}

        loaded, previous = load_ci_explorer_entity(lambda _id: entity, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL)

        assert loaded is entity
        assert previous == PREVIOUS_LABEL

    def test_unset_field_reports_none_as_previous_value(self) -> None:
        """An entity that never carried the field reports None rather than raising."""
        _loaded, previous = load_ci_explorer_entity(
            lambda _id: {'public_id': PUBLIC_ID}, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL,
        )

        assert previous is None


class TestRequestSchema:
    """The label-field route validates its one-key body."""

    def test_accepts_a_string_and_purges_unknown_keys(self) -> None:
        """A valid body passes and anything else in it is dropped rather than written."""
        validator = Validator(get_ci_explorer_label_schema(), purge_unknown=True)

        assert validator.validate({LABEL_KEY: LABEL_VALUE, 'active': False})
        assert validator.document == {LABEL_KEY: LABEL_VALUE}

    def test_empty_string_clears_the_field(self) -> None:
        """An empty value is how the nomination is cleared, so it must validate."""
        assert Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate({LABEL_KEY: ''})

    def test_missing_key_is_rejected(self) -> None:
        """A body without the field is refused instead of silently writing nothing."""
        assert not Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate(
            {'unrelated': 'x'},
        )

    def test_non_string_value_is_rejected(self) -> None:
        """The field holds a field NAME; a number or an object is refused."""
        assert not Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate({LABEL_KEY: 5})


# -------------------------------------------------------------------------------------------------------------------- #
#                                             the profile filter ids                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
EXISTING_IDS: list[int] = [11, 12]
UNKNOWN_IDS: list[int] = [98, 99]


def _manager(existing: list[int]) -> Mock:
    """A manager whose find() answers the documents among the asked ids that exist."""
    manager = Mock()
    manager.find.side_effect = lambda criteria, projection: [
        {'public_id': public_id} for public_id in criteria['public_id']['$in'] if public_id in existing
    ]

    return manager


class TestFindUnknownIds:
    """Which ids name no document."""

    def test_every_id_existing_answers_none(self) -> None:
        """Nothing unknown"""
        assert find_unknown_ids(_manager(EXISTING_IDS), EXISTING_IDS) == []

    def test_the_unknown_ids_are_answered_sorted(self) -> None:
        """Sorted, so a message naming them is stable"""
        assert find_unknown_ids(_manager(EXISTING_IDS), [99, 11, 98]) == UNKNOWN_IDS

    @pytest.mark.parametrize('ids', [None, []])
    def test_no_ids_cost_no_query(self, ids: list[int] | None) -> None:
        """An empty or absent filter asks nothing"""
        manager = _manager(EXISTING_IDS)

        assert find_unknown_ids(manager, ids) == []
        manager.find.assert_not_called()

    def test_the_whole_list_is_one_projected_query(self) -> None:
        """One query, reading the public_id alone"""
        manager = _manager(EXISTING_IDS)

        find_unknown_ids(manager, EXISTING_IDS + UNKNOWN_IDS)

        manager.find.assert_called_once_with(
            criteria={'public_id': {'$in': EXISTING_IDS + UNKNOWN_IDS}}, projection={'public_id': 1},
        )


class TestAbortIfProfileFiltersNameUnknownIds:
    """A profile naming a type or relation that does not exist is refused."""

    def test_known_ids_pass(self) -> None:
        """Nothing raised"""
        data = {CiExplorerProfileKey.TYPES_FILTER.value: EXISTING_IDS,
                CiExplorerProfileKey.RELATIONS_FILTER.value: EXISTING_IDS}

        abort_if_profile_filters_name_unknown_ids(data, _manager(EXISTING_IDS), _manager(EXISTING_IDS))

    @pytest.mark.parametrize('field', [CiExplorerProfileKey.TYPES_FILTER.value,
                                       CiExplorerProfileKey.RELATIONS_FILTER.value])
    def test_an_unknown_id_is_a_400_naming_the_filter(self, field: str) -> None:
        """Each filter is checked against its own collection"""
        data = {field: EXISTING_IDS + UNKNOWN_IDS}

        with pytest.raises(HTTPException) as refused:
            abort_if_profile_filters_name_unknown_ids(data, _manager(EXISTING_IDS), _manager(EXISTING_IDS))

        assert refused.value.code == HTTPStatus.BAD_REQUEST
        assert refused.value.description == PROFILE_FILTER_UNKNOWN_IDS_MSG.format(field=field, ids=UNKNOWN_IDS)

    def test_each_filter_is_checked_against_its_own_manager(self) -> None:
        """A relation id is not accepted because some TYPE carries it"""
        data = {CiExplorerProfileKey.RELATIONS_FILTER.value: [11]}

        with pytest.raises(HTTPException):
            abort_if_profile_filters_name_unknown_ids(data, _manager([11]), _manager([]))

