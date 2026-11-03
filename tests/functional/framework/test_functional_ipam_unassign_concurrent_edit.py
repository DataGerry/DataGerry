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
The subnet 'unassign IPs' route against an owner edited between its read and its write, over the wire

The race is staged by running a concurrent edit of the owner right before the route's write reaches the database
(``ObjectsManager.update_object`` wrapped). Pinned through the real route, the real stack and the real database:

  - a row another edit added meanwhile survives, the target row is unassigned, and the owner is bumped once from the
    version the concurrent edit left - which is also the version its EDIT entry records
  - a concurrent edit that does not bump the version (as the type-update propagation writes) is caught as well
  - an owner changed on every attempt stops the request with the 400 naming it, and keeps the concurrent edit
  - a request naming more IPs than ``IpamUnassignLimits.MAX_IPS`` is refused before anything is written
"""
from http import HTTPStatus
from typing import Any, Callable, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamUnassignLimits,
    IpAddressFamily,
)
from cmdb.framework.ipam.subnet_unassign_constants import (
    IPS_TOO_MANY_MSG,
    MAX_OWNER_WRITE_ATTEMPTS,
    OWNER_KEPT_CHANGING_MSG,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUBNET_OVERVIEW_URL: str = '/ipam/subnet/overview'
SUBNET_TYPE_ID: int = 9831
CARRIER_TYPE_ID: int = 9832
SUBNET_ID: int = 9841
CARRIER_ID: int = 9842
TYPE_IDS: list[int] = [SUBNET_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUBNET_ID, CARRIER_ID]

SUBNET_RANGE: str = '10.91.0.0/16'
TARGET_IP: str = '10.91.0.5'
CONCURRENT_IP: str = '10.91.0.77'
START_VERSION: str = '1.0.0'
CONCURRENT_VERSION: str = '1.0.4'
AFTER_CONCURRENT_VERSION: str = '1.0.5'
MESSAGE_KEY: str = 'message'
MDS_KEY: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value


def _interface_row(ip: str, subnet_ref: int | None = SUBNET_ID) -> dict[str, Any]:
    """One stored interface row"""
    return {CmdbObjectMdsRowKey.DATA.value: [
        make_field(InterfaceField.SUBNET, subnet_ref),
        make_field(InterfaceField.IP, ip),
        make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
    ]}


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the IPAM feature so the gated /ipam routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """A subnet and a carrier with one interface row in it; removed again with the carrier's log entries"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': TYPE_IDS}})
        objects.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': OBJECT_IDS}})
        logs.delete_many({ObjectLogKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})

    _purge()
    types.insert_many([
        make_type_doc(SUBNET_TYPE_ID, 'fn-race-subnet', SpecialType.SUBNET),
        make_type_doc(CARRIER_TYPE_ID, 'fn-race-carrier', None),
    ])
    objects.insert_many([
        make_object_doc(SUBNET_ID, SUBNET_TYPE_ID, [
            make_field(SubnetField.NAME, 'fn-race-sub'),
            make_field(SubnetField.TYPE, IpAddressFamily.IPV4),
            make_field(SubnetField.NETWORK_RANGE, SUBNET_RANGE),
        ]),
        make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [make_field('dg-name', 'fn-race-host')], mds=[{
            CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
            CmdbObjectMdsKey.VALUES.value: [_interface_row(TARGET_IP)],
        }]),
    ])

    yield objects

    _purge()


def _race(monkeypatch: pytest.MonkeyPatch, concurrent_edit: Callable[[], None], times: int) -> None:
    """Runs ``concurrent_edit`` right before each of the first ``times`` unassign writes"""
    original = ObjectsManager.update_object
    remaining: list[int] = [times]

    def _racing(self: ObjectsManager, *args: Any, **kwargs: Any) -> bool:
        if remaining[0] > 0:
            remaining[0] -= 1
            concurrent_edit()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ObjectsManager, 'update_object', _racing)


def _rows(objects: Any) -> list[dict[str, Any]]:
    """The carrier's stored interface rows"""
    return objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})[MDS_KEY][0][CmdbObjectMdsKey.VALUES.value]


def _value(row: dict[str, Any], field_name: str) -> Any:
    """One field's value in a row"""
    return next(entry[CmdbObjectFieldKey.VALUE.value] for entry in row[CmdbObjectMdsRowKey.DATA.value]
                if entry[CmdbObjectFieldKey.NAME.value] == field_name)


def _unassign(rest_api, ips: list[str]) -> Any:
    """POST the subnet-side unassign"""
    return rest_api.post(f'{SUBNET_OVERVIEW_URL}/{SUBNET_ID}/unassign', json={'ips': ips})


def test_a_row_added_meanwhile_survives(rest_api, objects, monkeypatch, database_manager: MongoDatabaseManager,
                                        database_name: str) -> None:
    """The write re-plans from the edited owner: both rows kept, the target unassigned, one bump, one entry"""
    def _add_row() -> None:
        objects.update_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, {
            '$push': {f'{MDS_KEY}.0.{CmdbObjectMdsKey.VALUES.value}': _interface_row(CONCURRENT_IP)},
            '$set': {CmdbObjectKey.VERSION.value: CONCURRENT_VERSION},
        })

    _race(monkeypatch, _add_row, times=1)

    response = _unassign(rest_api, [TARGET_IP])

    assert response.status_code == HTTPStatus.OK
    rows = _rows(objects)
    assert [_value(row, InterfaceField.IP.value) for row in rows] == [TARGET_IP, CONCURRENT_IP]
    assert [_value(row, InterfaceField.SUBNET.value) for row in rows] == [None, SUBNET_ID]
    stored = objects.find_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID})
    assert stored[CmdbObjectKey.VERSION.value] == AFTER_CONCURRENT_VERSION
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    entries = list(logs.find({ObjectLogKey.OBJECT_ID.value: CARRIER_ID, 'action': LogAction.EDIT.value}))
    assert [entry[ObjectLogKey.VERSION.value] for entry in entries] == [AFTER_CONCURRENT_VERSION]


def test_an_edit_that_keeps_the_version_is_caught_too(rest_api, objects, monkeypatch) -> None:
    """The sections are compared, not only the version: the propagation-style edit survives"""
    def _add_row_quietly() -> None:
        objects.update_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, {
            '$push': {f'{MDS_KEY}.0.{CmdbObjectMdsKey.VALUES.value}': _interface_row(CONCURRENT_IP)},
        })

    _race(monkeypatch, _add_row_quietly, times=1)

    assert _unassign(rest_api, [TARGET_IP]).status_code == HTTPStatus.OK
    assert [_value(row, InterfaceField.IP.value) for row in _rows(objects)] == [TARGET_IP, CONCURRENT_IP]


def test_an_owner_changed_on_every_attempt_is_the_400(rest_api, objects, monkeypatch) -> None:
    """Named in the message; every concurrent row kept, the target still assigned"""
    added: list[str] = []

    def _add_another_row() -> None:
        ip: str = f'10.91.1.{len(added) + 1}'
        added.append(ip)
        objects.update_one({CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID}, {
            '$push': {f'{MDS_KEY}.0.{CmdbObjectMdsKey.VALUES.value}': _interface_row(ip)},
        })

    _race(monkeypatch, _add_another_row, times=MAX_OWNER_WRITE_ATTEMPTS)

    response = _unassign(rest_api, [TARGET_IP])

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()[MESSAGE_KEY] == OWNER_KEPT_CHANGING_MSG.format(
        owner_id=CARRIER_ID, attempts=MAX_OWNER_WRITE_ATTEMPTS,
    )
    rows = _rows(objects)
    assert [_value(row, InterfaceField.IP.value) for row in rows] == [TARGET_IP, *added]
    assert _value(rows[0], InterfaceField.SUBNET.value) == SUBNET_ID


def test_too_many_ips_are_refused_before_anything_is_written(rest_api, objects) -> None:
    """The limit's 400, naming both counts"""
    count: int = IpamUnassignLimits.MAX_IPS + 1

    response = _unassign(rest_api, [TARGET_IP] * count)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()[MESSAGE_KEY] == IPS_TOO_MANY_MSG.format(max_ips=IpamUnassignLimits.MAX_IPS, count=count)
    assert _value(_rows(objects)[0], InterfaceField.SUBNET.value) == SUBNET_ID
