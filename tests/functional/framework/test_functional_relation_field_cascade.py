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
Functional tests: a CmdbRelation update writes its DECLARED-field diff onto the instances, never a name twice

``PUT /relations/<id>`` reconciles every CmdbObjectRelation's ``field_values`` with the declared ``fields``. Pinned:

  - moving a declared field into a section changes no instance (it was appended a second time)
  - taking a declared field out of every section keeps its values (they were wiped)
  - no longer declaring a field no section shows removes its values (they stayed under an undeclared name)
  - a newly declared field arrives null, once, also when it declares a default
  - after each of these, saving the instance unchanged is accepted (the duplicate / undeclared name was a 400)
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from tests.utils.ipam_doc_builders import make_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

RELATIONS_URL: str = '/relations'
INSTANCES_URL: str = '/object_relations'

PARENT_TYPE_ID: int = 79531
CHILD_TYPE_ID: int = 79532
RELATION_ID: int = 79501
INSTANCE_ID: int = 79511
PARENT_OBJECT_ID: int = 79521
CHILD_OBJECT_ID: int = 79522

SHOWN: str = 'shown'
HIDDEN: str = 'hidden'
LATER: str = 'later'
SHOWN_VALUE: str = 'shown-value'
HIDDEN_VALUE: str = 'hidden-value'
DECLARED_DEFAULT: str = 'a default'


def _field(name: str, **extra: Any) -> dict[str, Any]:
    """A declared relation field."""
    return {'type': FieldType.TEXT.value, 'name': name, 'label': name.title(), **extra}


def _relation(declared: list[dict[str, Any]], shown: list[str]) -> dict[str, Any]:
    """The relation as PUT sends it: the declared fields, one section showing `shown`."""
    return {
        'public_id': RELATION_ID,
        'relation_name': f'field-cascade-{RELATION_ID}',
        'relation_name_parent': 'is-parent-of',
        'relation_name_child': 'is-child-of',
        'parent_type_ids': [PARENT_TYPE_ID],
        'child_type_ids': [CHILD_TYPE_ID],
        'fields': declared,
        'sections': [{'type': SectionType.SECTION.value, 'name': 's1', 'label': 'S', 'fields': shown}],
    }


STORED_RELATION: dict[str, Any] = _relation([_field(SHOWN), _field(HIDDEN)], [SHOWN])
STORED_VALUES: list[dict[str, Any]] = [{'name': SHOWN, 'value': SHOWN_VALUE}, {'name': HIDDEN, 'value': HIDDEN_VALUE}]


@pytest.fixture(name='instances', autouse=True)
def fixture_instances(database_manager: MongoDatabaseManager, database_name: str):
    """The relation declaring SHOWN (in a section) and HIDDEN (in none), its types and objects, one instance of both"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    instances = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [PARENT_TYPE_ID, CHILD_TYPE_ID]}})
        relations.delete_many({'public_id': RELATION_ID})
        objects.delete_many({'public_id': {'$in': [PARENT_OBJECT_ID, CHILD_OBJECT_ID]}})
        instances.delete_many({'relation_id': RELATION_ID})

    _purge()
    types.insert_many([{'public_id': type_id, 'name': f'field-cascade-type-{type_id}', 'label': f'T{type_id}',
                        'active': True, 'fields': [], 'sections': []} for type_id in (PARENT_TYPE_ID, CHILD_TYPE_ID)])
    relations.insert_one(dict(STORED_RELATION))
    objects.insert_many([make_object_doc(PARENT_OBJECT_ID, PARENT_TYPE_ID, []),
                         make_object_doc(CHILD_OBJECT_ID, CHILD_TYPE_ID, [])])
    instances.insert_one({
        'public_id': INSTANCE_ID, 'relation_id': RELATION_ID,
        'relation_parent_id': PARENT_OBJECT_ID, 'relation_parent_type_id': PARENT_TYPE_ID,
        'relation_child_id': CHILD_OBJECT_ID, 'relation_child_type_id': CHILD_TYPE_ID,
        'field_values': [dict(entry) for entry in STORED_VALUES], 'author_id': 1,
    })
    yield instances
    _purge()


def _update_relation(rest_api: Any, declared: list[dict[str, Any]], shown: list[str]) -> None:
    """PUTs the relation and asserts it was accepted."""
    response = rest_api.put(f'{RELATIONS_URL}/{RELATION_ID}', json=_relation(declared, shown))

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()


def _stored_values(instances: Any) -> list[dict[str, Any]]:
    """The instance's field_values as stored."""
    return instances.find_one({'public_id': INSTANCE_ID})['field_values']


def _save_unchanged(rest_api: Any, instances: Any) -> int:
    """PUTs the instance back with what is stored - what the relation tab's save does - and answers the status."""
    stored: dict[str, Any] = instances.find_one({'public_id': INSTANCE_ID}, {'_id': 0})
    payload: dict[str, Any] = {key: stored[key] for key in (
        'relation_id', 'relation_parent_id', 'relation_parent_type_id', 'relation_child_id',
        'relation_child_type_id', 'field_values',
    )}

    return rest_api.put(f'{INSTANCES_URL}/{INSTANCE_ID}', json=payload).status_code


def test_moving_a_declared_field_into_a_section_changes_no_instance(rest_api, instances) -> None:
    """HIDDEN shown now: its value stays, once, and the instance saves unchanged"""
    _update_relation(rest_api, [_field(SHOWN), _field(HIDDEN)], [SHOWN, HIDDEN])

    assert _stored_values(instances) == STORED_VALUES
    assert _save_unchanged(rest_api, instances) == HTTPStatus.ACCEPTED


def test_taking_a_declared_field_out_of_every_section_keeps_its_value(rest_api, instances) -> None:
    """SHOWN still declared but in no section: its value is kept"""
    _update_relation(rest_api, [_field(SHOWN), _field(HIDDEN)], [])

    assert _stored_values(instances) == STORED_VALUES


def test_no_longer_declaring_an_unsectioned_field_removes_its_value(rest_api, instances) -> None:
    """HIDDEN dropped from `fields`: its value goes, and the instance saves unchanged"""
    _update_relation(rest_api, [_field(SHOWN)], [SHOWN])

    assert _stored_values(instances) == [{'name': SHOWN, 'value': SHOWN_VALUE}]
    assert _save_unchanged(rest_api, instances) == HTTPStatus.ACCEPTED


def test_a_newly_declared_field_arrives_null_once_despite_a_default(rest_api, instances) -> None:
    """LATER declared with a default: the existing instance gets {LATER: null}, the held values untouched"""
    _update_relation(rest_api, [_field(SHOWN), _field(HIDDEN), _field(LATER, value=DECLARED_DEFAULT)], [SHOWN, LATER])

    assert _stored_values(instances) == [*STORED_VALUES, {'name': LATER, 'value': None}]
    assert _save_unchanged(rest_api, instances) == HTTPStatus.ACCEPTED
