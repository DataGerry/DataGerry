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
Integration tests for the compare-and-swap object write behind the subnet 'unassign IPs' flow, on a real MongoDB

``ObjectsManager.update_object(..., expected=..., stored_type_id=...)`` against a stored owner whose interface rows
carry a timestamp - the guard is built from the document as read, so it must round-trip through the driver:

  - an unchanged owner is written, and the answer says so
  - a row edited meanwhile without a version bump, a version bumped meanwhile, and a type changed meanwhile each make
    the write miss, and the stored owner keeps the concurrent state
  - ``write_owner_unassign`` re-reads such an owner and lands its re-planned write on the second attempt
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.framework.ipam.subnet_unassign import clear_subnet_ref_in_owner, owner_write_guard, write_owner_unassign
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

CARRIER_TYPE_ID: int = 9851
OTHER_TYPE_ID: int = 9852
CARRIER_ID: int = 9853
SUBNET_ID: int = 9854
TARGET_IP: str = '10.92.0.5'
CONCURRENT_IP: str = '10.92.0.6'
SEEN_AT: datetime = datetime(2026, 5, 4, 3, 2, 1, tzinfo=timezone.utc)
START_VERSION: str = '1.0.0'
BUMPED_VERSION: str = '1.0.7'
MDS_KEY: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
ROWS_PATH: str = f'{MDS_KEY}.0.{CmdbObjectMdsKey.VALUES.value}'


def _row(ip: str) -> dict[str, Any]:
    """An interface row with a timestamp entry"""
    return {CmdbObjectMdsRowKey.DATA.value: [
        make_field(InterfaceField.SUBNET, SUBNET_ID),
        make_field(InterfaceField.IP, ip),
        make_field('dg-interface-seen', SEEN_AT),
    ]}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Two types and a carrier of the first, with one interface row; removed again"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': [CARRIER_TYPE_ID, OTHER_TYPE_ID]}})
        objects.delete_many({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})

    _purge()
    types.insert_many([make_type_doc(CARRIER_TYPE_ID, 'int-cas-carrier', None),
                       make_type_doc(OTHER_TYPE_ID, 'int-cas-other', None)])
    objects.insert_one(make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [make_field('dg-name', 'int-cas-host')], mds=[{
        CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
        CmdbObjectMdsKey.VALUES.value: [_row(TARGET_IP)],
    }]))

    yield objects

    _purge()


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """The real ObjectsManager"""
    return ObjectsManager(database_manager)


def _read(manager: ObjectsManager) -> dict[str, Any]:
    """The carrier as stored"""
    return manager.find_objects({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, as_dict=True)[0]


def _write(manager: ObjectsManager, owner: dict[str, Any]) -> bool:
    """A partial version write guarded by the owner as read"""
    return manager.update_object(
        CARRIER_ID, {CmdbObjectKey.VERSION.value: BUMPED_VERSION}, partial=True,
        expected=owner_write_guard(owner), stored_type_id=owner[CmdbObjectKey.TYPE_ID.value],
    )


def test_an_unchanged_owner_is_written(manager: ObjectsManager, objects) -> None:
    """The guard built from the read - timestamp included - matches the stored document"""
    assert _write(manager, _read(manager)) is True
    assert objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})[CmdbObjectKey.VERSION.value] == BUMPED_VERSION


@pytest.mark.parametrize('concurrent_update', [
    {'$push': {ROWS_PATH: _row(CONCURRENT_IP)}},
    {'$set': {CmdbObjectKey.VERSION.value: '1.0.3'}},
    {'$set': {CmdbObjectKey.TYPE_ID.value: OTHER_TYPE_ID}},
], ids=['row-without-version-bump', 'version-bump', 'type-change'])
def test_a_concurrent_edit_makes_the_write_miss(
        manager: ObjectsManager, objects, concurrent_update: dict[str, Any]) -> None:
    """Nothing written over the concurrent state"""
    owner: dict[str, Any] = _read(manager)
    objects.update_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, concurrent_update)
    before: dict[str, Any] = objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})

    assert _write(manager, owner) is False
    assert objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}) == before


def test_the_unassign_write_lands_on_the_second_attempt(manager: ObjectsManager, objects) -> None:
    """Re-read, re-planned: the concurrent row kept, the target unassigned"""
    owner: dict[str, Any] = _read(manager)
    objects.update_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, {'$push': {ROWS_PATH: _row(CONCURRENT_IP)}})

    plan, affected = write_owner_unassign(
        manager, owner, clear_subnet_ref_in_owner, SUBNET_ID, {TARGET_IP}, None, {}, {},
    )

    assert affected == {TARGET_IP}
    assert plan is not None
    rows = objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})[MDS_KEY][0][CmdbObjectMdsKey.VALUES.value]
    values = [[entry[CmdbObjectFieldKey.VALUE.value] for entry in row[CmdbObjectMdsRowKey.DATA.value]] for row in rows]
    assert [row_values[:2] for row_values in values] == [
        [None, TARGET_IP], [SUBNET_ID, CONCURRENT_IP],
    ]
