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
Integration tests for the global-template copy reconcile against a real MongoDB

The template stays the source of truth, and the IPAM SpecialType wiring writes the subnet reference's ``ref_types``
INTO the predefined ``dg-ipam-interface`` template and then propagates it. Pinned with real type and template
documents:

  - after the wiring, a type write whose interface copy carries stale ``ref_types`` is reconciled to the wired ones
  - the wiring after a reconciled write still reaches the type - the two compose in either order
  - the import's reconcile is idempotent: a second run over the reconciled entry changes nothing
"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SectionTemplatesManager, TypesManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField, SubnetField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.ipam.special_type_wiring import handle_special_types
from cmdb.framework.section_templates.global_template_reconcile import (
    reconcile_type_with_global_templates,
    resolve_global_templates,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_repairs import reconcile_global_templates
# -------------------------------------------------------------------------------------------------------------------- #

SUBNET_TYPE_ID: int = 98201
USER_TYPE_ID: int = 98202
TEMPLATE_ID: int = 98203
STALE_TYPE_ID: int = 98299
ALL_TYPE_IDS: list[int] = [SUBNET_TYPE_ID, USER_TYPE_ID]


def _ref_field(ref_types: list[int]) -> dict[str, Any]:
    """The interface template's subnet reference"""
    return {'type': 'ref', 'name': InterfaceField.SUBNET, 'label': 'Network', 'ref_types': list(ref_types)}


def _type(public_id: int, name: str, special_type: str, fields: list[dict[str, Any]],
          sections: list[dict[str, Any]], claims: list[str]) -> dict[str, Any]:
    """A stored type document"""
    return {
        'public_id': public_id, 'name': name, 'label': name, 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': special_type,
        'fields': fields, 'global_template_ids': claims,
        'render_meta': {'icon': 'fa-cube', 'sections': sections, 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': {}}},
    }


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """An unwired Subnet type, a type using the interface template, and the template itself"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        templates.delete_many({'public_id': TEMPLATE_ID})

    _purge()
    types.insert_many([
        _type(SUBNET_TYPE_ID, 'it-t30-subnet', SpecialType.SUBNET,
              [{'type': 'ref', 'name': SubnetField.PARENT_SUPERNET, 'label': 'Supernet', 'ref_types': []}], [], []),
        _type(USER_TYPE_ID, 'it-t30-user', '', [_ref_field([])],
              [{'type': 'multi-data-section', 'name': IpamSection.INTERFACE, 'label': 'Interfaces',
                'fields': [InterfaceField.SUBNET]}],
              [IpamSection.INTERFACE]),
    ])
    templates.insert_one({
        'public_id': TEMPLATE_ID, 'name': IpamSection.INTERFACE, 'label': 'Interfaces', 'type': 'multi-data-section',
        'is_global': True, 'predefined': True, 'fields': [_ref_field([])],
    })
    yield {'types': types, 'templates': templates}
    _purge()


def _reconciled(database_manager: MongoDatabaseManager, database_name: str, document: dict[str, Any]) -> None:
    """Runs the write-path reconcile against the stored templates"""
    templates = resolve_global_templates(
        SectionTemplatesManager(database_manager, database_name), [IpamSection.INTERFACE],
    )
    outcome = reconcile_type_with_global_templates(document, templates)

    assert outcome.conflicts == []


def _subnet_ref_types(document: dict[str, Any]) -> list[int]:
    """The ref_types of a document's interface subnet reference"""
    return next(field for field in document['fields'] if field['name'] == InterfaceField.SUBNET)['ref_types']


def test_a_stale_copy_is_reconciled_to_the_wired_template(seeded, database_manager, database_name) -> None:
    """The wiring put the Subnet type into the template; a write carrying the old copy gets it back"""
    handle_special_types(
        TypesManager(database_manager), SpecialType.SUBNET,
        SectionTemplatesManager(database_manager, database_name), SUBNET_TYPE_ID,
    )
    stale: dict[str, Any] = seeded['types'].find_one({'public_id': USER_TYPE_ID}, {'_id': 0})
    stale['fields'] = [_ref_field([STALE_TYPE_ID])]

    _reconciled(database_manager, database_name, stale)

    assert _subnet_ref_types(stale) == [SUBNET_TYPE_ID]


def test_the_wiring_after_a_reconciled_write_still_reaches_the_type(seeded, database_manager, database_name) -> None:
    """Reconcile, write, then wire: the template and the type end up with the Subnet type"""
    types_manager = TypesManager(database_manager)
    document: dict[str, Any] = seeded['types'].find_one({'public_id': USER_TYPE_ID}, {'_id': 0})
    _reconciled(database_manager, database_name, document)
    types_manager.update_type(USER_TYPE_ID, document)

    handle_special_types(
        types_manager, SpecialType.SUBNET, SectionTemplatesManager(database_manager, database_name), SUBNET_TYPE_ID,
    )

    assert _subnet_ref_types(seeded['templates'].find_one({'public_id': TEMPLATE_ID})) == [SUBNET_TYPE_ID]
    assert _subnet_ref_types(seeded['types'].find_one({'public_id': USER_TYPE_ID})) == [SUBNET_TYPE_ID]


def test_the_import_reconcile_is_idempotent(seeded, database_manager, database_name) -> None:
    """Re-run safe: the second run over the reconciled entry changes nothing"""
    entry: dict[str, Any] = seeded['types'].find_one({'public_id': USER_TYPE_ID}, {'_id': 0})
    entry['fields'] = [_ref_field([STALE_TYPE_ID])]
    entry['global_template_ids'].append('it-t30-no-such-template')
    manager = SectionTemplatesManager(database_manager, database_name)

    assert reconcile_global_templates(entry, manager) is None
    first: dict[str, Any] = deepcopy(entry)

    assert reconcile_global_templates(entry, manager) is None
    assert entry == first
    assert entry['global_template_ids'] == [IpamSection.INTERFACE]
