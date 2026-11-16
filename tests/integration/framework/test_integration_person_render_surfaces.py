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
Integration tests: the person pass and the CI Explorer enrichment label persons from a real MongoDB

Seeds a visible person type (Ada) and a second person type the reader is denied (Eve). Pinned on real reads: the
person pass rewrites a rendered object's own summaries, a reference's summaries and line, and its links from one
resolution; the CI Explorer enrichment replaces a person field with the visible labels
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.ci_explorer.graph import enrich_in_scope_objects
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.person_selector.person_selector_constants import PersonLineMarkerKey, PersonRenderMarker
from cmdb.framework.person_selector.selector_render import apply_person_selector_render
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 48601
HIDDEN_TYPE: int = 48602
HOLDER_TYPE: int = 48603
ADA: int = 48611
EVE: int = 48612
HOLDER: int = 48621
OWNER: str = 'owner'
LINE_TEMPLATE: str = 'Owned by {}'
HOLDER_FIELDS: list[dict[str, Any]] = [
    {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON'], 'multiple': True},
]


def _hidden() -> frozenset[int]:
    """The reader's denied Types"""
    return frozenset({HIDDEN_TYPE})


def _type(public_id: int, marker: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A type document"""
    return {'public_id': public_id, 'name': f'it-surface-{public_id}', 'label': 'Holder', 'author_id': 1,
            'active': True, 'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker,
            'fields': fields, 'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'sections': []},
            'acl': {'activated': False, 'groups': {'includes': None}}}


def _person(public_id: int, type_id: int, name: str) -> dict[str, Any]:
    """A person object"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': [{'name': 'display_name', 'value': name}]}


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The person types and persons; the objects and types managers - purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    name_field: list[dict[str, Any]] = [{'type': 'text', 'name': 'display_name', 'label': 'Name'}]

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [PERSON_TYPE, HIDDEN_TYPE, HOLDER_TYPE]}})
        objects.delete_many({'public_id': {'$in': [ADA, EVE, HOLDER]}})

    _purge()
    types.insert_many([_type(PERSON_TYPE, 'PERSON', name_field), _type(HIDDEN_TYPE, 'PERSON', name_field),
                       _type(HOLDER_TYPE, '', HOLDER_FIELDS)])
    objects.insert_many([_person(ADA, PERSON_TYPE, 'Ada'), _person(EVE, HIDDEN_TYPE, 'Eve')])
    yield SimpleNamespace(objects=ObjectsManager(database_manager, database_name),
                          types=TypesManager(database_manager, database_name), locations=None)
    _purge()


def _rendered() -> RenderResult:
    """A rendered holder: its own summary, a reference with a marked line, a marked link"""
    result = RenderResult()
    result.object_information = {'object_id': HOLDER}
    result.fields = [{'name': 'asset', 'type': 'ref', 'value': 1, 'reference': {
        'summaries': [{'type': 'person', 'value': [ADA, EVE]}], 'line': 'raw',
        PersonRenderMarker.LINE.value: {PersonLineMarkerKey.TEMPLATE.value: LINE_TEMPLATE,
                                        PersonLineMarkerKey.INPUTS.value: [[ADA, EVE]]},
    }}]
    result.summaries = [{'name': OWNER, 'type': 'person', 'value': [EVE, ADA]}]
    result.externals = [{'name': 'profile', PersonRenderMarker.LINK_IDS.value: [EVE]}]

    return result


def test_the_person_pass_labels_every_surface_from_the_database(managers: Any) -> None:
    """Eve's Type is denied: she is left out everywhere, her link too"""
    result: RenderResult = _rendered()

    apply_person_selector_render([(result, CmdbType.from_data(_type(HOLDER_TYPE, '', HOLDER_FIELDS)))],
                                 managers.objects, managers.types, _hidden)

    reference: dict[str, Any] = result.fields[0]['reference']
    assert reference['summaries'][0]['value'] == 'Ada'
    assert reference['line'] == LINE_TEMPLATE.format('Ada')
    assert result.summaries[0]['value'] == 'Ada'
    assert result.summary_line == 'Ada'
    assert result.externals == []


def test_the_ci_explorer_enrichment_labels_person_fields_from_the_database(managers: Any) -> None:
    """The holder's owner field becomes the visible label"""
    holder: dict[str, Any] = {'public_id': HOLDER, 'type_id': HOLDER_TYPE,
                              'fields': [{'name': OWNER, 'value': [EVE, ADA]}]}

    enriched: dict[int, dict[str, Any]] = enrich_in_scope_objects(
        [holder], {HOLDER_TYPE: _type(HOLDER_TYPE, '', HOLDER_FIELDS)}, managers, _hidden,
    )

    assert enriched[HOLDER]['fields'] == [{'name': OWNER, 'value': 'Ada'}]
