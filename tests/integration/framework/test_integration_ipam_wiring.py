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
Integration tests for the SpecialType ref_types cross-wiring against a real MongoDB

Runs handle_special_types against real type / section-template documents: wiring a new SUBNET
SpecialType updates the dg-ipam-interface template's subnet reference (and propagates it into
a user type that already inlined the section), the VLAN type's subnet reference and the
SUBNET's own parent-supernet reference; wiring a new SUPERNET updates the SUBNET type's
parent reference. Kept in its own module: handle_special_types resolves SpecialTypes via
get_one_by, so no other module-scoped SUBNET / SUPERNET seed may be alive at the same time
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager, SectionTemplatesManager
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
)
from cmdb.framework.ipam.special_type_wiring import handle_special_types
# -------------------------------------------------------------------------------------------------------------------- #

WIRE_SUPERNET_TYPE_ID: int = 9850
WIRE_SUBNET_TYPE_ID: int = 9851
WIRE_VLAN_TYPE_ID: int = 9852
WIRE_USER_TYPE_ID: int = 9853
WIRE_TEMPLATE_ID: int = 9854


def _type_doc(public_id: int, name: str, special_type: str | None) -> dict[str, Any]:
    """Builds a minimal active CmdbType doc."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        'name': name,
        'label': name,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'sections': [], 'summary': {'fields': ['dg-name']}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        'special_type': special_type if special_type is not None else '',
    }


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """Provides a TypesManager wired to the test database."""
    return TypesManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             SPECIAL TYPE WIRING                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _ref_field(name: str, label: str) -> dict[str, Any]:
    """Builds one ref field definition with an empty ref_types list."""
    return {'type': 'ref', 'name': name, 'label': label, 'ref_types': []}


def _wire_type_doc(public_id: int, name: str, special_type: str | None,
                   fields: list[dict[str, Any]],
                   sections: list[dict[str, Any]] | None = None,
                   global_template_ids: list[str] | None = None) -> dict[str, Any]:
    """Builds a CmdbType doc for the wiring scenario."""
    doc = _type_doc(public_id, name, special_type)
    doc['fields'] = fields
    doc['render_meta']['sections'] = sections or []
    doc['global_template_ids'] = global_template_ids or []

    return doc


@pytest.fixture(name='wiring_topology')
def fixture_wiring_topology(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the un-wired SpecialTypes, the interface template and a using type per test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    types.insert_many([
        _wire_type_doc(WIRE_SUPERNET_TYPE_ID, 'it-wire-supernet', SpecialType.SUPERNET,
                       fields=[{'type': 'text', 'name': SupernetField.NETWORK_RANGE, 'label': 'Network'}]),
        _wire_type_doc(WIRE_SUBNET_TYPE_ID, 'it-wire-subnet', SpecialType.SUBNET,
                       fields=[_ref_field(SubnetField.PARENT_SUPERNET, 'Supernet')]),
        _wire_type_doc(WIRE_VLAN_TYPE_ID, 'it-wire-vlan', SpecialType.VLAN,
                       fields=[_ref_field(VlanField.SUBNET_REF, 'Subnet')]),
        _wire_type_doc(
            WIRE_USER_TYPE_ID, 'it-wire-user', None,
            fields=[_ref_field(InterfaceField.SUBNET, 'Network')],
            sections=[{
                'type': 'multi-data-section',
                'name': IpamSection.INTERFACE,
                'label': 'Interfaces',
                'fields': [InterfaceField.SUBNET],
            }],
            global_template_ids=[IpamSection.INTERFACE],
        ),
    ])

    templates.insert_one({
        CmdbObjectKey.PUBLIC_ID: WIRE_TEMPLATE_ID,
        'name': IpamSection.INTERFACE,
        'label': 'Interfaces',
        'type': 'multi-data-section',
        'is_global': True,
        'predefined': True,
        'fields': [_ref_field(InterfaceField.SUBNET, 'Network')],
    })

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': [
        WIRE_SUPERNET_TYPE_ID, WIRE_SUBNET_TYPE_ID, WIRE_VLAN_TYPE_ID, WIRE_USER_TYPE_ID,
    ]}})
    templates.delete_many({CmdbObjectKey.PUBLIC_ID: WIRE_TEMPLATE_ID})


def _field_def(type_doc: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Returns a type document's field definition by name."""
    return next(f for f in type_doc['fields'] if f.get('name') == field_name)


@pytest.mark.usefixtures('wiring_topology')
def test_handle_special_types_wires_a_new_subnet_type_everywhere(
    database_manager: MongoDatabaseManager, database_name: str,
    types_manager: TypesManager,
) -> None:
    """SUBNET wiring updates the template (+ using type via propagation), the VLAN and itself"""
    section_templates_manager = SectionTemplatesManager(database_manager, database_name)

    handle_special_types(types_manager, SpecialType.SUBNET, section_templates_manager, WIRE_SUBNET_TYPE_ID)

    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    template_doc = templates.find_one({CmdbObjectKey.PUBLIC_ID: WIRE_TEMPLATE_ID})
    assert _field_def(template_doc, InterfaceField.SUBNET)['ref_types'] == [WIRE_SUBNET_TYPE_ID]

    user_doc = types.find_one({CmdbObjectKey.PUBLIC_ID: WIRE_USER_TYPE_ID})
    assert _field_def(user_doc, InterfaceField.SUBNET)['ref_types'] == [WIRE_SUBNET_TYPE_ID]

    vlan_doc = types.find_one({CmdbObjectKey.PUBLIC_ID: WIRE_VLAN_TYPE_ID})
    assert _field_def(vlan_doc, VlanField.SUBNET_REF)['ref_types'] == [WIRE_SUBNET_TYPE_ID]

    subnet_doc = types.find_one({CmdbObjectKey.PUBLIC_ID: WIRE_SUBNET_TYPE_ID})
    assert _field_def(subnet_doc, SubnetField.PARENT_SUPERNET)['ref_types'] == [WIRE_SUPERNET_TYPE_ID]


@pytest.mark.usefixtures('wiring_topology')
def test_handle_special_types_wires_a_new_supernet_into_the_subnet_type(
    database_manager: MongoDatabaseManager, database_name: str,
    types_manager: TypesManager,
) -> None:
    """SUPERNET wiring adds the supernet's id to the SUBNET type's parent-ref field"""
    section_templates_manager = SectionTemplatesManager(database_manager, database_name)

    handle_special_types(
        types_manager, SpecialType.SUPERNET, section_templates_manager, WIRE_SUPERNET_TYPE_ID,
    )

    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    subnet_doc = types.find_one({CmdbObjectKey.PUBLIC_ID: WIRE_SUBNET_TYPE_ID})

    assert _field_def(subnet_doc, SubnetField.PARENT_SUPERNET)['ref_types'] == [WIRE_SUPERNET_TYPE_ID]
