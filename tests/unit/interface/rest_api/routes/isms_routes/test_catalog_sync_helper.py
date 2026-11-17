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
"""Unit tests of the catalog import / update sync plan"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.catalog_sync_helper import build_catalog_control, plan_catalog_sync
from cmdb.interface.rest_api.routes.isms_routes.control_measure_catalog_constants import CONTROL_MEASURE_WRITE_SCHEMA
# -------------------------------------------------------------------------------------------------------------------- #

def _new(identifier: str, values: dict[str, Any]) -> dict[str, Any]:
    return {'identifier': identifier, **values}


def _stored(public_id: int, identifier: str, title: str, chapter: str | None = 'Ch', description: str | None = 'D'):
    return {'public_id': public_id, 'identifier': identifier, 'title': title, 'chapter': chapter,
            'description': description}


def _control(identifier: str, title: str, chapter: str | None = 'Ch', description: str | None = 'D'):
    return {'identifier': identifier, 'title': title, 'chapter': chapter, 'description': description}


def test_a_first_import_creates_every_requirement_once() -> None:
    """Duplicates and blank identifiers in the catalog are ignored"""
    plan = plan_catalog_sync([], [_control('A.1', 'One'), _control('A.1', 'Again'), _control(' ', 'Blank'),
                                  _control('A.2', ' Two ')], _new)

    assert [doc['identifier'] for doc in plan.to_insert] == ['A.1', 'A.2']
    assert plan.to_insert[1]['title'] == 'Two'
    assert not plan.to_update and plan.unchanged == 0 and plan.obsolete == []


def test_an_update_changes_only_the_catalog_content_and_reports_obsolete_controls() -> None:
    """New ones are created, changed ones updated field by field, removed ones only reported"""
    existing = [_stored(1, 'A.1', 'One'), _stored(2, 'A.2', 'Two'), _stored(3, 'A.3', 'Gone')]
    controls = [_control('A.1', 'One'), _control('A.2', 'Two (revised)', description=None), _control('A.4', 'New')]

    plan = plan_catalog_sync(existing, controls, _new)

    assert [doc['identifier'] for doc in plan.to_insert] == ['A.4']
    assert plan.to_update == [(2, {'title': 'Two (revised)', 'description': None})]
    assert plan.unchanged == 1
    assert plan.obsolete == ['A.3']


def test_empty_strings_and_null_count_as_the_same_value() -> None:
    """A stored null chapter is not 'changed' by a catalog that has none"""
    plan = plan_catalog_sync([_stored(1, 'A.1', 'One', chapter=None, description='')],
                             [_control('A.1', 'One', chapter='', description=None)], _new)

    assert plan.unchanged == 1 and not plan.to_update


SOURCE_ID: int = 21
STATE_ID: int = 31


def test_a_new_requirement_is_a_requirement_control_of_the_catalog() -> None:
    """The catalog values kept; REQUIREMENT, the catalog's source and state, not applicable, no reason"""
    values = {'title': 'One', 'chapter': 'Ch', 'description': None}

    assert build_catalog_control('A.1', values, 'cat', SOURCE_ID, STATE_ID) == {
        'title': 'One', 'chapter': 'Ch', 'description': None, 'control_measure_type': 'REQUIREMENT',
        'source': SOURCE_ID, 'implementation_state': STATE_ID, 'identifier': 'A.1', 'is_applicable': False,
        'reason': None, 'catalog_id': 'cat',
    }


def test_the_write_schema_leaves_the_identity_and_the_catalog_to_the_server() -> None:
    """A create / update body can carry neither public_id nor catalog_id - every other key stays"""
    assert 'public_id' not in CONTROL_MEASURE_WRITE_SCHEMA
    assert 'catalog_id' not in CONTROL_MEASURE_WRITE_SCHEMA
    assert 'title' in CONTROL_MEASURE_WRITE_SCHEMA

