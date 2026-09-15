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
Integration tests for the IPAM license-gating detection against a real MongoDB

The object-write / object-delete IPAM detectors resolve an object's SpecialType through a real
TypesManager (the unit tests mock get_type). Here a special type and a normal type are seeded into
Mongo and the detectors are exercised against the real type lookup: special-type objects are gated,
ordinary objects are not, and a regular object that links a subnet on an interface row is gated for
writes but not for deletes
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.framework.ipam.enforcement import (
    object_write_requires_ipam_license,
    object_delete_requires_ipam_license,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SPECIAL_TYPE_ID: int = 47301
NORMAL_TYPE_ID: int = 47302
RACK_TYPE_ID: int = 47303
SUBNET_REF: int = 47350
OBJECT_ID: int = 47360

SEEDED_TYPE_IDS: list[int] = [SPECIAL_TYPE_ID, NORMAL_TYPE_ID, RACK_TYPE_ID]


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an IPAM special type, a normal type and a non-IPAM special type (RACK)"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_many([
        make_type_doc(SPECIAL_TYPE_ID, 'int-lic-special', SpecialType.SUBNET),
        make_type_doc(NORMAL_TYPE_ID, 'int-lic-normal', None),
        make_type_doc(RACK_TYPE_ID, 'int-lic-rack', SpecialType.RACK),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': SEEDED_TYPE_IDS}})


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """A real TypesManager backed by the test database"""
    return TypesManager(database_manager)


def _interface_object(type_id: int, subnet_ref: int | None) -> dict[str, Any]:
    """Builds a regular object carrying one dg-ipam-interface row with the given subnet selection"""
    data = [make_field(InterfaceField.IP, '10.0.0.5')]

    if subnet_ref is not None:
        data.insert(0, make_field(InterfaceField.SUBNET, subnet_ref))

    section = {
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: data}],
    }

    return make_object_doc(OBJECT_ID, type_id, [make_field('dg-name', 'host')], mds=[section])


# -------------------------------------------------------------------------------------------------------------------- #
#                                          object write detection                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_write_detection_gates_special_type_object(types_manager: TypesManager) -> None:
    """A write to a special-type object is detected as IPAM-gated via the real type lookup"""
    candidate = make_object_doc(OBJECT_ID, SPECIAL_TYPE_ID, [make_field('dg-name', 'sn')])

    assert object_write_requires_ipam_license(types_manager, candidate) is True


def test_write_detection_allows_plain_object(types_manager: TypesManager) -> None:
    """A write to an ordinary object (no special type, no interface subnet) is not gated"""
    candidate = make_object_doc(OBJECT_ID, NORMAL_TYPE_ID, [make_field('dg-name', 'host')])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is False


def test_write_detection_gates_interface_subnet_on_regular_object(types_manager: TypesManager) -> None:
    """Creating a regular object whose interface row selects a subnet is gated"""
    candidate = _interface_object(NORMAL_TYPE_ID, SUBNET_REF)

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is True


def test_write_detection_allows_interface_without_subnet(types_manager: TypesManager) -> None:
    """A regular object whose interface row selects no subnet is not gated"""
    candidate = _interface_object(NORMAL_TYPE_ID, None)

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is False


def test_write_detection_gates_a_rack_object_behind_ipam(types_manager: TypesManager) -> None:
    """
    A Rack object write is gated behind IPAM - an INTERIM policy, not a claim that a Rack is IPAM

    The detector matches per member via SpecialType.get_license_gated_types, so it still does not
    fire on the mere presence of a 'special_type' marker; RACK is simply in the gated set for now.
    """
    candidate = make_object_doc(OBJECT_ID, RACK_TYPE_ID, [make_field('dg-rack-name', 'rack-1')])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                          object delete detection                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_detection_gates_special_type_object(types_manager: TypesManager) -> None:
    """Deleting a special-type object is detected as IPAM-gated via the real type lookup"""
    target = make_object_doc(OBJECT_ID, SPECIAL_TYPE_ID, [make_field('dg-name', 'sn')])

    assert object_delete_requires_ipam_license(types_manager, target) is True


def test_delete_detection_allows_regular_object_with_interface_subnet(types_manager: TypesManager) -> None:
    """Deleting a regular object is never gated, even when it links a subnet on an interface"""
    target = _interface_object(NORMAL_TYPE_ID, SUBNET_REF)

    assert object_delete_requires_ipam_license(types_manager, target) is False


def test_delete_detection_gates_a_rack_object_behind_ipam(types_manager: TypesManager) -> None:
    """Deleting a Rack object is gated behind IPAM too, under the same interim policy"""
    target = make_object_doc(OBJECT_ID, RACK_TYPE_ID, [make_field('dg-rack-name', 'rack-1')])

    assert object_delete_requires_ipam_license(types_manager, target) is True
