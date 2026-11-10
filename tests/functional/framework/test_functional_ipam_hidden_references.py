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
Functional tests: an IPAM refusal names only the objects the caller may READ

The IPAM invariants are judged over every stored object; the answer is not. Pinned, as a writer whose group may not
READ one carrier Type and as an administrator:

  - deleting a subnet referenced by interface rows on readable and hidden carriers is still refused - the 400 names
    the readable carriers and counts the hidden ones; a subnet only hidden carriers reference names no id at all
  - an administrator sees every id, as before
  - the interface IP pre-check (``POST /ipam/validate/interface``) refuses an IP a hidden carrier uses without naming
    that object or its row; a readable carrier is named as before
"""
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection, SubnetField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.ipam.references_constants import (
    IP_ALREADY_USED_MSG,
    IP_OWNER_HIDDEN_LABEL,
    IP_OWNER_READABLE_LABEL,
    SUBNET_REFERENCED_BY_INTERFACES_MSG,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
VALIDATE_URL: str = '/ipam/validate/interface'
MESSAGE_KEY: str = 'message'

SUBNET_TYPE_ID: int = 943601
OPEN_CARRIER_TYPE_ID: int = 943602
HIDDEN_CARRIER_TYPE_ID: int = 943603
MIXED_SUBNET_ID: int = 943611     # referenced by two readable and three hidden carriers
HIDDEN_ONLY_SUBNET_ID: int = 943612   # referenced by one hidden carrier only
OPEN_CARRIER_IDS: list[int] = [943621, 943622]
HIDDEN_CARRIER_IDS: list[int] = [943631, 943632, 943633]
HIDDEN_ONLY_CARRIER_ID: int = 943634
OPEN_IP: str = '10.96.0.5'
HIDDEN_IP: str = '10.96.0.6'
NETWORK_RANGE: str = '10.96.0.0/24'
ROW_ID: int = 1

WRITER_GROUP_ID: int = 943641
WRITER_ID: int = 943642
WRITER_NAME: str = 'ipam-hidden-reference-writer'
WRITER_RIGHTS: list[str] = ['base.framework.object.*', 'base.framework.ipam.view']

ADMIN_ALL: dict[str, list[str]] = {str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}
HIDDEN_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': ADMIN_ALL}}

TYPE_IDS: list[int] = [SUBNET_TYPE_ID, OPEN_CARRIER_TYPE_ID, HIDDEN_CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [MIXED_SUBNET_ID, HIDDEN_ONLY_SUBNET_ID, *OPEN_CARRIER_IDS, *HIDDEN_CARRIER_IDS,
                         HIDDEN_ONLY_CARRIER_ID]


def _carrier(public_id: int, type_id: int, subnet_id: int, ip_address: str) -> dict[str, Any]:
    """An object with one interface row on the subnet, using the IP"""
    return make_object_doc(public_id, type_id, [], mds=[{
        CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
        CmdbObjectMdsKey.VALUES.value: [{'multi_data_id': ROW_ID, CmdbObjectMdsRowKey.DATA.value: [
            make_field(InterfaceField.SUBNET, subnet_id), make_field(InterfaceField.IP, ip_address),
        ]}],
    }])


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str,
          monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The subnets, their carriers, the hidden carrier type and the writer; IPAM licensed; removed again"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)
    collection = partial(database_manager.get_collection, db_name=database_name)

    def _purge() -> None:
        collection(CmdbType.COLLECTION).delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': TYPE_IDS}})
        collection(CmdbObject.COLLECTION).delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': OBJECT_IDS}})
        collection(CmdbUserGroup.COLLECTION).delete_many({'public_id': WRITER_GROUP_ID})
        collection(CmdbUser.COLLECTION).delete_many({'public_id': WRITER_ID})

    _purge()
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_CARRIER_TYPE_ID, 'fn-hidden-carrier')
    hidden_type['acl'] = HIDDEN_ACL
    collection(CmdbType.COLLECTION).insert_many([
        make_type_doc(SUBNET_TYPE_ID, 'fn-hidden-subnet', SpecialType.SUBNET),
        make_type_doc(OPEN_CARRIER_TYPE_ID, 'fn-open-carrier'),
        hidden_type,
    ])
    collection(CmdbObject.COLLECTION).insert_many([
        make_object_doc(MIXED_SUBNET_ID, SUBNET_TYPE_ID, [make_field(SubnetField.NETWORK_RANGE, NETWORK_RANGE)]),
        make_object_doc(HIDDEN_ONLY_SUBNET_ID, SUBNET_TYPE_ID, [make_field(SubnetField.NETWORK_RANGE, NETWORK_RANGE)]),
        _carrier(OPEN_CARRIER_IDS[0], OPEN_CARRIER_TYPE_ID, MIXED_SUBNET_ID, OPEN_IP),
        _carrier(OPEN_CARRIER_IDS[1], OPEN_CARRIER_TYPE_ID, MIXED_SUBNET_ID, '10.96.0.7'),
        _carrier(HIDDEN_CARRIER_IDS[0], HIDDEN_CARRIER_TYPE_ID, MIXED_SUBNET_ID, HIDDEN_IP),
        _carrier(HIDDEN_CARRIER_IDS[1], HIDDEN_CARRIER_TYPE_ID, MIXED_SUBNET_ID, '10.96.0.8'),
        _carrier(HIDDEN_CARRIER_IDS[2], HIDDEN_CARRIER_TYPE_ID, MIXED_SUBNET_ID, '10.96.0.9'),
        _carrier(HIDDEN_ONLY_CARRIER_ID, HIDDEN_CARRIER_TYPE_ID, HIDDEN_ONLY_SUBNET_ID, '10.96.0.10'),
    ])
    collection(CmdbUserGroup.COLLECTION).insert_one(
        {'public_id': WRITER_GROUP_ID, 'name': WRITER_NAME, 'label': WRITER_NAME, 'rights': WRITER_RIGHTS})
    collection(CmdbUser.COLLECTION).insert_one(
        {'public_id': WRITER_ID, 'user_name': WRITER_NAME, 'active': True, 'group_id': WRITER_GROUP_ID,
         'registration_time': datetime.now(timezone.utc)})
    yield
    _purge()


@pytest.fixture(name='writer')
def fixture_writer() -> CmdbUser:
    """The seeded writer: the object rights and IPAM view, no READ on the hidden carrier type"""
    return CmdbUser(public_id=WRITER_ID, user_name=WRITER_NAME, active=True, group_id=WRITER_GROUP_ID)


def _refusal(response: Any) -> str:
    """The 400's message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()

    return response.get_json()[MESSAGE_KEY]


def _ids(*public_ids: int) -> str:
    """Ids as the description lists them"""
    return ', '.join(str(public_id) for public_id in public_ids)


class TestTheDeleteGuard:
    """DELETE /objects/<id> on a referenced subnet"""

    def test_the_writer_sees_the_readable_carriers_and_a_count(self, rest_api, writer: CmdbUser) -> None:
        """Still refused - every reference blocks"""
        message: str = _refusal(rest_api.delete(f'{OBJECTS_URL}/{MIXED_SUBNET_ID}', user=writer))

        assert SUBNET_REFERENCED_BY_INTERFACES_MSG.format(
            ids=f'{_ids(*OPEN_CARRIER_IDS)}, plus 3 object(s) you cannot see',
        ) in message
        assert all(str(hidden_id) not in message for hidden_id in HIDDEN_CARRIER_IDS)

    def test_only_hidden_carriers_name_no_id(self, rest_api, writer: CmdbUser) -> None:
        """Just the count"""
        message: str = _refusal(rest_api.delete(f'{OBJECTS_URL}/{HIDDEN_ONLY_SUBNET_ID}', user=writer))

        assert SUBNET_REFERENCED_BY_INTERFACES_MSG.format(ids='1 object(s) you cannot see') in message
        assert str(HIDDEN_ONLY_CARRIER_ID) not in message

    def test_the_administrator_sees_every_id(self, rest_api) -> None:
        """As before"""
        message: str = _refusal(rest_api.delete(f'{OBJECTS_URL}/{MIXED_SUBNET_ID}'))

        assert SUBNET_REFERENCED_BY_INTERFACES_MSG.format(
            ids=_ids(*OPEN_CARRIER_IDS, *HIDDEN_CARRIER_IDS),
        ) in message

    def test_the_bulk_delete_names_the_same(self, rest_api, writer: CmdbUser) -> None:
        """The selection route shares the guard"""
        message: str = _refusal(rest_api.delete(f'{OBJECTS_URL}/delete/{MIXED_SUBNET_ID}', user=writer))

        assert 'plus 3 object(s) you cannot see' in message


def _validate(rest_api: Any, ip_address: str, **kwargs: Any) -> list[str]:
    """The interface pre-check's error messages for one row on the mixed subnet"""
    response = rest_api.post(VALIDATE_URL, json={'rows': [{
        'row_index': 0, 'subnet_id': MIXED_SUBNET_ID, 'ip_address': ip_address, 'interface_type': 'IPv4',
    }]}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return [error['message'] for error in response.get_json()['errors']]


class TestTheIpPreCheck:
    """POST /ipam/validate/interface"""

    def test_an_ip_a_hidden_carrier_uses_names_no_object(self, rest_api, writer: CmdbUser) -> None:
        """Still taken"""
        assert IP_ALREADY_USED_MSG.format(
            ip_address=HIDDEN_IP, subnet_id=MIXED_SUBNET_ID, owner=IP_OWNER_HIDDEN_LABEL,
        ) in _validate(rest_api, HIDDEN_IP, user=writer)

    def test_an_ip_a_readable_carrier_uses_names_it(self, rest_api, writer: CmdbUser) -> None:
        """As before"""
        assert IP_ALREADY_USED_MSG.format(
            ip_address=OPEN_IP, subnet_id=MIXED_SUBNET_ID,
            owner=IP_OWNER_READABLE_LABEL.format(object_id=OPEN_CARRIER_IDS[0], row_key=ROW_ID),
        ) in _validate(rest_api, OPEN_IP, user=writer)

    def test_the_administrator_sees_the_hidden_carrier(self, rest_api) -> None:
        """Its id and row"""
        assert IP_ALREADY_USED_MSG.format(
            ip_address=HIDDEN_IP, subnet_id=MIXED_SUBNET_ID,
            owner=IP_OWNER_READABLE_LABEL.format(object_id=HIDDEN_CARRIER_IDS[0], row_key=ROW_ID),
        ) in _validate(rest_api, HIDDEN_IP)

