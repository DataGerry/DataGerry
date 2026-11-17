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
Integration tests: summary lines label person selector values from a real MongoDB

Seeds a person type everybody may READ (Ada), one the reader is denied (Eve), a PERSON_GROUP (Ops) and an asset type
summarised by its name and a person selector. Pinned on real reads through ``ObjectsManager.get_summary_lines_lookup``
and ``person_selector.selector_labeller.person_labeller``: the line shows the labels the reader may see, a value of
only hidden persons is left out without a separator, no labeller leaves every person value out, and the raw ids never
reach the line
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.ipam.reference_disclosure import hidden_types_from, no_hidden_types
from cmdb.framework.person_selector.selector_labeller import person_labeller
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 48951
HIDDEN_TYPE: int = 48952
GROUP_TYPE: int = 48953
ASSET_TYPE: int = 48954
TYPE_IDS: list[int] = [PERSON_TYPE, HIDDEN_TYPE, GROUP_TYPE, ASSET_TYPE]
ADA: int = 48961
EVE: int = 48962
OPS: int = 48963
SHARED_ASSET: int = 48971
EVE_ASSET: int = 48972
GROUP_ASSET: int = 48973
OBJECT_IDS: list[int] = [ADA, EVE, OPS, SHARED_ASSET, EVE_ASSET, GROUP_ASSET]

ASSET_LABEL: str = 'Asset'
NAME: str = 'name'
OWNER: str = 'owner'
ASSET_FIELDS: list[dict[str, Any]] = [
    {'type': 'text', 'name': NAME, 'label': 'Name'},
    {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON', 'PERSON_GROUP'], 'multiple': True},
]


def _type(public_id: int, marker: str, fields: list[dict[str, Any]], summary: list[str]) -> dict[str, Any]:
    """A type document"""
    return {'public_id': public_id, 'name': f'it-summary-{public_id}', 'label': ASSET_LABEL, 'author_id': 1,
            'active': True, 'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker,
            'fields': fields, 'render_meta': {'icon': 'fa-cube', 'summary': {'fields': summary}, 'sections': []},
            'acl': {'activated': False, 'groups': {'includes': None}}}


def _object(public_id: int, type_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    """An object document"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'fields': [{'name': name, 'value': value} for name, value in fields.items()]}


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager,
                     database_name: str) -> Iterator[tuple[ObjectsManager, TypesManager]]:
    """The person types, the group type, the asset type and their objects; purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    person_fields: list[dict[str, Any]] = [{'type': 'text', 'name': 'display_name', 'label': 'Name'}]
    group_fields: list[dict[str, Any]] = [{'type': 'text', 'name': 'name', 'label': 'Name'}]

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_many([
        _type(PERSON_TYPE, 'PERSON', person_fields, []), _type(HIDDEN_TYPE, 'PERSON', person_fields, []),
        _type(GROUP_TYPE, 'PERSON_GROUP', group_fields, []), _type(ASSET_TYPE, '', ASSET_FIELDS, [NAME, OWNER]),
    ])
    objects.insert_many([
        _object(ADA, PERSON_TYPE, {'display_name': 'Ada'}),
        _object(EVE, HIDDEN_TYPE, {'display_name': 'Eve'}),
        _object(OPS, GROUP_TYPE, {'name': 'Ops'}),
        _object(SHARED_ASSET, ASSET_TYPE, {NAME: 'srv-shared', OWNER: [ADA, EVE]}),
        _object(EVE_ASSET, ASSET_TYPE, {NAME: 'srv-eve', OWNER: [EVE]}),
        _object(GROUP_ASSET, ASSET_TYPE, {NAME: 'srv-ops', OWNER: [OPS, ADA]}),
    ])
    yield ObjectsManager(database_manager, database_name), TypesManager(database_manager, database_name)
    _purge()


ASSET_IDS: list[int] = [SHARED_ASSET, EVE_ASSET, GROUP_ASSET]


def test_the_reader_sees_the_labels_of_the_persons_they_may_read(
        managers: tuple[ObjectsManager, TypesManager]) -> None:
    """Eve's Type is denied: she is left out; a value of only Eve leaves the field out without a separator"""
    objects_manager, types_manager = managers

    lines: dict[int, str] = objects_manager.get_summary_lines_lookup(
        ASSET_IDS, labeller=person_labeller(objects_manager, types_manager, hidden_types_from([HIDDEN_TYPE])),
    )

    assert lines == {
        SHARED_ASSET: f'{ASSET_LABEL} #{SHARED_ASSET} - srv-shared | Ada',
        EVE_ASSET: f'{ASSET_LABEL} #{EVE_ASSET} - srv-eve',
        GROUP_ASSET: f'{ASSET_LABEL} #{GROUP_ASSET} - srv-ops | Ops, Ada',
    }


def test_a_reader_nothing_is_hidden_from_sees_every_label(managers: tuple[ObjectsManager, TypesManager]) -> None:
    """Without denied Types every selected person and group is labelled, in the stored order"""
    objects_manager, types_manager = managers

    lines: dict[int, str] = objects_manager.get_summary_lines_lookup(
        ASSET_IDS, with_type=False, labeller=person_labeller(objects_manager, types_manager, no_hidden_types),
    )

    assert lines == {
        SHARED_ASSET: f'#{SHARED_ASSET} - srv-shared | Ada, Eve',
        EVE_ASSET: f'#{EVE_ASSET} - srv-eve | Eve',
        GROUP_ASSET: f'#{GROUP_ASSET} - srv-ops | Ops, Ada',
    }


def test_no_labeller_leaves_every_person_value_out(managers: tuple[ObjectsManager, TypesManager]) -> None:
    """A caller without a labeller never shows person ids"""
    objects_manager, _ = managers

    lines: dict[int, str] = objects_manager.get_summary_lines_lookup(ASSET_IDS)

    assert lines == {asset_id: f'{ASSET_LABEL} #{asset_id} - {name}'
                     for asset_id, name in zip(ASSET_IDS, ['srv-shared', 'srv-eve', 'srv-ops'])}
    assert not any(str(person_id) in line for line in lines.values() for person_id in (ADA, EVE, OPS))
