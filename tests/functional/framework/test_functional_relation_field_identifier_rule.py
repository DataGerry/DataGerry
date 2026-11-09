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
Functional tests: a relation field's name is its identifier, and a field that changes its type starts over

``PUT /relations/<id>`` on a relation with one instance. Pinned:

  - stopping to declare one field and declaring another in the same payload - a rename on the wire - is a 400 naming
    both sets while the relation has instances; the relation and the instance are left as they were (the instance's
    value used to be dropped and the new field added empty)
  - the same payload passes once the relation has no instances; removing alone and adding alone always pass
  - a field that keeps its name but changes its type is reset to null on the instance (its text used to stay under a
    date field), and the instance saves back unchanged
  - a failed count of the instances is its own 400, not a 500
"""
from http import HTTPStatus
from typing import Any

from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    RELATION_FIELD_IDENTIFIER_IMMUTABLE_MESSAGE,
    RELATION_INSTANCE_LOOKUP_FAILED_MESSAGE,
)
from tests.functional.framework.test_functional_relation_field_cascade import (  # pylint: disable=unused-import
    HIDDEN,
    HIDDEN_VALUE,
    INSTANCE_ID,
    RELATIONS_URL,
    RELATION_ID,
    SHOWN,
    SHOWN_VALUE,
    STORED_VALUES,
    _field,
    _relation,
    _save_unchanged,
    _stored_values,
    fixture_instances,
)
# -------------------------------------------------------------------------------------------------------------------- #

MESSAGE_KEY: str = 'message'
RENAMED: str = 'renamed'


def _put(rest_api: Any, declared: list[dict[str, Any]]) -> Any:
    """PUTs the relation declaring `declared`, SHOWN shown"""
    return rest_api.put(f'{RELATIONS_URL}/{RELATION_ID}', json=_relation(declared, [SHOWN]))


def _stored_field_names(database_manager: Any, database_name: str) -> list[str]:
    """The names the stored relation declares"""
    relation: dict[str, Any] = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
        .find_one({'public_id': RELATION_ID})

    return [field['name'] for field in relation['fields']]


class TestTheIdentifierRule:
    """Removing and adding names in one update"""

    def test_a_rename_with_an_instance_is_refused_and_nothing_changes(self, rest_api, instances, database_manager,
                                                                      database_name) -> None:
        """Both sets named; relation and instance unchanged"""
        response = _put(rest_api, [_field(SHOWN), _field(RENAMED)])

        assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (
            HTTPStatus.BAD_REQUEST, RELATION_FIELD_IDENTIFIER_IMMUTABLE_MESSAGE.format(removed=HIDDEN, added=RENAMED),
        )
        assert _stored_field_names(database_manager, database_name) == [SHOWN, HIDDEN]
        assert _stored_values(instances) == STORED_VALUES

    def test_a_rename_without_instances_passes(self, rest_api, instances) -> None:
        """Nothing to lose"""
        instances.delete_many({'relation_id': RELATION_ID})

        assert _put(rest_api, [_field(SHOWN), _field(RENAMED)]).status_code == HTTPStatus.ACCEPTED

    def test_removing_alone_passes_and_drops_the_value(self, rest_api, instances) -> None:
        """A deliberate removal"""
        assert _put(rest_api, [_field(SHOWN)]).status_code == HTTPStatus.ACCEPTED
        assert _stored_values(instances) == [{'name': SHOWN, 'value': SHOWN_VALUE}]

    def test_adding_alone_passes(self, rest_api, instances) -> None:
        """The second update of a remove-then-add"""
        assert _put(rest_api, [_field(SHOWN), _field(HIDDEN), _field(RENAMED)]).status_code == HTTPStatus.ACCEPTED
        assert _stored_values(instances) == [*STORED_VALUES, {'name': RENAMED, 'value': None}]

    def test_a_failed_instance_count_is_its_own_400(self, rest_api, instances, monkeypatch) -> None:
        """Not a 500; nothing changes"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('instances unreadable')

        monkeypatch.setattr(ObjectRelationsManager, 'relation_has_instances', _failing)

        response = _put(rest_api, [_field(SHOWN), _field(RENAMED)])

        assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (
            HTTPStatus.BAD_REQUEST, RELATION_INSTANCE_LOOKUP_FAILED_MESSAGE,
        )
        assert _stored_values(instances) == STORED_VALUES


class TestATypeChange:
    """A kept name with another type"""

    def test_the_value_is_reset_and_the_rest_kept(self, rest_api, instances) -> None:
        """SHOWN text -> date: its text is gone, HIDDEN keeps its value, the order is kept"""
        response = _put(rest_api, [_field(SHOWN, type=FieldType.DATE.value), _field(HIDDEN)])

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_values(instances) == [{'name': SHOWN, 'value': None}, {'name': HIDDEN, 'value': HIDDEN_VALUE}]

    def test_the_instance_saves_back_unchanged(self, rest_api, instances) -> None:
        """The relation tab's save"""
        _put(rest_api, [_field(SHOWN, type=FieldType.DATE.value), _field(HIDDEN)])

        assert _save_unchanged(rest_api, instances) == HTTPStatus.ACCEPTED

    def test_an_unchanged_type_keeps_the_value(self, rest_api, instances) -> None:
        """The control: a label edit resets nothing"""
        assert _put(rest_api, [_field(SHOWN, label='Relabelled'), _field(HIDDEN)]).status_code == HTTPStatus.ACCEPTED
        assert _stored_values(instances) == STORED_VALUES

    def test_a_rename_check_still_runs_alongside(self, rest_api, instances) -> None:
        """A type change and a rename in one payload: the rename refuses it, nothing reset"""
        response = _put(rest_api, [_field(SHOWN, type=FieldType.DATE.value), _field(RENAMED)])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_values(instances) == STORED_VALUES
        assert INSTANCE_ID == instances.find_one({'relation_id': RELATION_ID})['public_id']
