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
Unit tests for the concrete profile builders (create_profile across the six profiles)

Covers the build-and-insert ordering guarantee (a type's conditional / reference sections can
resolve types created earlier in the same profile - the regression that motivated the ordering
fix), the intra-profile dependent references, and a smoke test that every profile produces its
expected set of types. The static field/section layout of each individual get_*_type is not
asserted exhaustively (it is hard-coded data; that would be a brittle change-detector).
"""
from typing import Any

import pytest

from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import TypeSlotKey
from cmdb.framework.datagerry_assistant.profile_user_management import UserManagementProfile
from cmdb.framework.datagerry_assistant.profile_location import LocationProfile
from cmdb.framework.datagerry_assistant.profile_rack import RackProfile
from cmdb.framework.datagerry_assistant.profile_ipam import IPAMProfile
from cmdb.framework.datagerry_assistant.profile_client_management import ClientManagementProfile
from cmdb.framework.datagerry_assistant.profile_server_management import ServerManagementProfile
from cmdb.framework.datagerry_assistant.profile_network_infrastructure import NetworkInfrastructureProfile
# -------------------------------------------------------------------------------------------------------------------- #


def _section_labels(type_doc: dict[str, Any]) -> list[str]:
    """Section labels of a built type, in order"""
    return [section['label'] for section in type_doc['render_meta']['sections']]


def _ref_types_by_field_label(type_doc: dict[str, Any], field_label: str) -> list[int]:
    """ref_types of the (first) field carrying the given label"""
    return next(field['ref_types'] for field in type_doc['fields'] if field.get('label') == field_label)


def _section_by_name(type_doc: dict[str, Any], section_name: str) -> dict[str, Any] | None:
    """The render_meta section with the given name, or None"""
    return next((s for s in type_doc['render_meta']['sections'] if s['name'] == section_name), None)


def _ref_types_by_field_name(type_doc: dict[str, Any], field_name: str) -> list[int]:
    """ref_types of the field with the given name"""
    return next(field['ref_types'] for field in type_doc['fields'] if field.get('name') == field_name)

# -------------------------------------------------------------------------------------------------------------------- #
#                            the IPAM interface MDS section replaces the legacy dg-network                            #
# -------------------------------------------------------------------------------------------------------------------- #

def test_consuming_type_inlines_ipam_interface_as_mds_section(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """A consuming type carries dg-ipam-interface as a multi-data-section listed in global_template_ids"""
    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    interface_section: dict[str, Any] | None = _section_by_name(client, IpamSection.INTERFACE)

    assert interface_section is not None
    assert interface_section['type'] == SectionType.MDS_SECTION
    assert interface_section['hidden_fields'] == []
    assert IpamSection.INTERFACE in client['global_template_ids']
    # the legacy section is gone
    assert _section_by_name(client, 'dg-network') is None


def test_ipam_interface_subnet_ref_wired_when_subnet_exists(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """When a Subnet type was created earlier, the interface Subnet reference points at it"""
    empty_slot_map[TypeSlotKey.SUBNET_ID] = 55

    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    assert _ref_types_by_field_name(client, InterfaceField.SUBNET) == [55]


def test_ipam_interface_subnet_ref_empty_without_subnet(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Without an IPAM Subnet type the interface Subnet reference stays empty (still attached)"""
    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    assert _ref_types_by_field_name(client, InterfaceField.SUBNET) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                              ordering regression: Client references the in-profile OS                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_client_gets_os_section_referencing_os_created_in_same_profile(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """The Operating System is created before the Client, so the Client's OS section is emitted"""
    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    assert 'Operating system' in _section_labels(client)
    assert _ref_types_by_field_label(client, 'OS') == [empty_slot_map[TypeSlotKey.OPERATING_SYSTEM_ID]]


def test_client_user_section_absent_without_user_types(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Without User / Customer User types the Client's conditional User section is skipped"""
    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    assert 'User assignment' not in _section_labels(fake_types_manager.by_name('client'))


def test_client_user_section_present_when_user_types_exist(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """With User and Customer User slots populated (by a prior profile) the User section is added"""
    empty_slot_map[TypeSlotKey.USER_ID] = 100
    empty_slot_map[TypeSlotKey.CUSTOMER_USER_ID] = 101

    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    assert 'User assignment' in _section_labels(client)
    assert _ref_types_by_field_label(client, 'User') == [100, 101]

# -------------------------------------------------------------------------------------------------------------------- #
#                                       intra-profile dependent references                                            #
# -------------------------------------------------------------------------------------------------------------------- #

def test_customer_user_references_company(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Customer User (created last) references the Company created earlier in the profile"""
    UserManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    company: dict[str, Any] = fake_types_manager.by_name('company')
    customer_user: dict[str, Any] = fake_types_manager.by_name('customer_user')
    assert _ref_types_by_field_label(customer_user, 'Company') == [company['public_id']]


def test_monitor_references_client(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Monitor (created last) references the Client created earlier in the profile"""
    ClientManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    client: dict[str, Any] = fake_types_manager.by_name('client')
    monitor: dict[str, Any] = fake_types_manager.by_name('monitor')
    assert _ref_types_by_field_label(monitor, 'Device') == [client['public_id']]


def test_virtual_server_references_server(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Virtual Server (created last) references the Server created earlier in the profile"""
    ServerManagementProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    server: dict[str, Any] = fake_types_manager.by_name('server')
    virtual_server: dict[str, Any] = fake_types_manager.by_name('virtual_server')
    assert _ref_types_by_field_label(virtual_server, 'Server') == [server['public_id']]


def test_location_profile_skips_its_basic_rack_when_the_rack_view_type_exists(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """With the Rack View profile selected the location profile leaves the created RACK type alone"""
    RackProfile(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()
    rack_view_id: int | None = empty_slot_map[TypeSlotKey.RACK_ID]

    LocationProfile(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    ).create_profile()

    racks: list[dict[str, Any]] = [doc for doc in fake_types_manager.store.values() if doc['name'] == 'rack']
    assert len(racks) == 1
    assert empty_slot_map[TypeSlotKey.RACK_ID] == rack_view_id

# -------------------------------------------------------------------------------------------------------------------- #
#                                    smoke: each profile builds its expected types                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('profile_cls, expected_names', [
    (UserManagementProfile, {'company', 'user', 'customer_user'}),
    (LocationProfile, {'country', 'city', 'building', 'room', 'rack'}),
    (RackProfile, {'rack'}),
    (ClientManagementProfile, {'operating_system', 'client', 'printer', 'monitor'}),
    (ServerManagementProfile, {'server', 'appliance', 'virtual_server'}),
    (NetworkInfrastructureProfile, {'switch', 'router', 'patch_panel', 'wireless_access_point'}),
    (IPAMProfile, {'supernet', 'subnet', 'vlan'}),
], ids=lambda value: value.__name__ if isinstance(value, type) else '')
def test_profile_creates_expected_types(
    profile_cls: type,
    expected_names: set[str],
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Each profile creates exactly its expected set of named, well-formed CmdbType dicts"""
    profile_cls(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()

    created: list[dict[str, Any]] = list(fake_types_manager.store.values())
    assert {doc['name'] for doc in created} == expected_names

    for doc in created:
        assert doc['label']
        assert isinstance(doc['fields'], list) and doc['fields']
        assert 'sections' in doc['render_meta']
