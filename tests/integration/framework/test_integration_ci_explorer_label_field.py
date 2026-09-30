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
Integration tests for the CI Explorer label field against a real stored CmdbType

The label-field route judges the nomination against the Type as stored and then writes only that one
key through `TypesManager.update_type_field`. Against MongoDB this shows what the pure unit tests of
the rule cannot: the rule reads the stored document the same way it reads a payload - a declared
field in no section is selectable, a multi-data-section field is not - and the targeted write leaves
every other key of the stored Type exactly as it was
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ci_explorer.label_field import label_field_error, selectable_label_fields
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model import CmdbType, FieldType, SectionType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 93960
PLAIN_FIELD: str = 'hostname'
MDS_FIELD: str = 'port-name'
UNASSIGNED_FIELD: str = 'asset-tag'


def _type_document() -> dict[str, Any]:
    """A stored CmdbType with an ordinary section, a multi-data-section and one unassigned field."""
    return {
        'public_id': TYPE_ID, 'name': 'label-field-integration', 'label': 'Label Field Integration',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [
            {'type': FieldType.TEXT.value, 'name': PLAIN_FIELD, 'label': 'Hostname'},
            {'type': FieldType.TEXT.value, 'name': MDS_FIELD, 'label': 'Port'},
            {'type': FieldType.TEXT.value, 'name': UNASSIGNED_FIELD, 'label': 'Asset tag'},
        ],
        'render_meta': {
            'icon': '', 'summary': {'fields': []},
            'sections': [
                {'type': SectionType.SECTION.value, 'name': 'information', 'fields': [PLAIN_FIELD]},
                {'type': SectionType.MDS_SECTION.value, 'name': 'ports', 'fields': [MDS_FIELD]},
            ],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        TypeSchemaKey.CI_EXPLORER_LABEL.value: None,
    }


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Type; yields the raw collection."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(_type_document())
    yield types
    types.delete_many({'public_id': TYPE_ID})


def test_the_rule_reads_the_stored_type(types, database_manager: MongoDatabaseManager) -> None:
    """The unassigned field is offered, the multi-data-section field is not"""
    stored: dict[str, Any] = TypesManager(database_manager).get_type(TYPE_ID)

    assert selectable_label_fields(stored) == [PLAIN_FIELD, UNASSIGNED_FIELD]
    assert label_field_error(stored, UNASSIGNED_FIELD) is None
    assert label_field_error(stored, MDS_FIELD) is not None


def test_the_targeted_write_changes_only_the_nomination(types, database_manager: MongoDatabaseManager) -> None:
    """update_type_field sets the one key; the fields, sections and version are the stored ones"""
    before: dict[str, Any] = types.find_one({'public_id': TYPE_ID}, {'_id': 0})

    TypesManager(database_manager).update_type_field(TYPE_ID, TypeSchemaKey.CI_EXPLORER_LABEL.value, PLAIN_FIELD)

    after: dict[str, Any] = types.find_one({'public_id': TYPE_ID}, {'_id': 0})

    assert after[TypeSchemaKey.CI_EXPLORER_LABEL.value] == PLAIN_FIELD
    assert {key: value for key, value in after.items() if key != TypeSchemaKey.CI_EXPLORER_LABEL.value} == \
        {key: value for key, value in before.items() if key != TypeSchemaKey.CI_EXPLORER_LABEL.value}
