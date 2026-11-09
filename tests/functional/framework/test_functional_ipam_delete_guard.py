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
Functional tests: the IPAM delete guards on DELETE /objects/<id> and /objects/delete/<ids>, and what they cost

A SUPERNET is refused while a subnet references it, a SUBNET while a VLAN or an interface row does - unless the
referencing objects are deleted in the same request. The 400 names at most 20 ids and counts the rest. The guard
asks a whole selection in a few queries (one per kind of reference, each stopping at the first match) after one read
of the special types, whatever the number of targets, and every reference read answers two keys per object. The CI
Explorer's IPAM neighbours resolve the special types in one read and load at most item_limit objects
"""
import json
from collections import Counter
from http import HTTPStatus
from typing import Any, Iterator

import pymongo.collection
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection, SubnetField, VlanField
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.references_constants import REFERENCE_PROJECTION
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
CI_EXPLORER_URL: str = '/ci_explorer/items'

SUPERNET_TYPE_ID: int = 942501
SUBNET_TYPE_ID: int = 942502
VLAN_TYPE_ID: int = 942503
CARRIER_TYPE_ID: int = 942504

SUPERNET_ID: int = 942510             # subnets A and B
BIG_SUPERNET_ID: int = 942511         # 23 subnets: the capped 400
SUBNET_A_ID: int = 942520             # VLAN + interface carrier
SUBNET_B_ID: int = 942521             # free
VLAN_ID: int = 942530
CARRIER_ID: int = 942540
FIRST_BIG_SUBNET_ID: int = 942600
BIG_SUBNET_COUNT: int = 23
FIRST_FREE_SUBNET_ID: int = 942700    # unreferenced subnets for the read counts, no supernet
FREE_SUBNET_COUNT: int = 12
FEW_FREE_SUBNETS: int = 3
LISTED: int = 20
ITEM_LIMIT: int = 2

BIG_SUBNET_IDS: list[int] = [FIRST_BIG_SUBNET_ID + offset for offset in range(BIG_SUBNET_COUNT)]
FREE_SUBNET_IDS: list[int] = [FIRST_FREE_SUBNET_ID + offset for offset in range(FREE_SUBNET_COUNT)]
TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, VLAN_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUPERNET_ID, BIG_SUPERNET_ID, SUBNET_A_ID, SUBNET_B_ID, VLAN_ID, CARRIER_ID,
                         *BIG_SUBNET_IDS, *FREE_SUBNET_IDS]

#: Per request: the one read of the SUBNET / VLAN type ids (special_type $in)
SPECIAL_TYPE_READS: int = 1
#: Per request, for a selection of subnets nothing references: the VLAN and the interface-row existence checks
SUBNET_SELECTION_REFERENCE_READS: int = 2
#: The field and section names only a reference query filters on
REFERENCE_MARKERS: tuple[str, ...] = (
    SubnetField.PARENT_SUPERNET.value, VlanField.SUBNET_REF.value, IpamSection.INTERFACE.value,
)


def _subnet(public_id: int, supernet_id: int | None) -> dict[str, Any]:
    """A SUBNET object, optionally under a supernet."""
    fields = [make_field(SubnetField.NAME, f'fn-guard-sub-{public_id}')]

    if supernet_id is not None:
        fields.append(make_field(SubnetField.PARENT_SUPERNET, supernet_id))

    return make_object_doc(public_id, SUBNET_TYPE_ID, fields)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str,
          monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The topology, re-seeded per test (the deletes remove it); IPAM licensed"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'fn-guard-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'fn-guard-subnet', SpecialType.SUBNET),
        make_type_doc(VLAN_TYPE_ID, 'fn-guard-vlan', SpecialType.VLAN),
        make_type_doc(CARRIER_TYPE_ID, 'fn-guard-carrier', None),
    ])
    objects.insert_many([
        make_object_doc(SUPERNET_ID, SUPERNET_TYPE_ID, []),
        make_object_doc(BIG_SUPERNET_ID, SUPERNET_TYPE_ID, []),
        _subnet(SUBNET_A_ID, SUPERNET_ID),
        _subnet(SUBNET_B_ID, SUPERNET_ID),
        *(_subnet(subnet_id, BIG_SUPERNET_ID) for subnet_id in BIG_SUBNET_IDS),
        *(_subnet(subnet_id, None) for subnet_id in FREE_SUBNET_IDS),
        make_object_doc(VLAN_ID, VLAN_TYPE_ID, [make_field(VlanField.SUBNET_REF, SUBNET_A_ID)]),
        make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [], mds=[{
            CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
            CmdbObjectMdsKey.VALUES.value: [{CmdbObjectMdsRowKey.DATA.value: [
                make_field(InterfaceField.SUBNET, SUBNET_A_ID),
            ]}],
        }]),
    ])
    yield
    types.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': OBJECT_IDS}})


@pytest.fixture(name='finds')
def fixture_finds(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Records every find the driver runs: (collection, filter, options)"""
    recorded: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    original_find = pymongo.collection.Collection.find

    def _recording_find(collection: Any, *args: Any, **kwargs: Any) -> Any:
        query: Any = args[0] if args else kwargs.get('filter', {})
        recorded.append((collection.name, query or {}, kwargs))
        return original_find(collection, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, 'find', _recording_find)

    return recorded


def _reference_reads(finds: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    """The options of the object reads that look for IPAM references."""
    return [options for collection, query, options in finds
            if collection == CmdbObject.COLLECTION and _names_a_reference(query)]


def _names_a_reference(query: dict[str, Any]) -> bool:
    """Whether a filter is an IPAM reference lookup (it names a reference field or the interface section)."""
    text: str = json.dumps(query, default=str)

    return any(marker in text for marker in REFERENCE_MARKERS)


def _special_type_reads(finds: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> Counter:
    """The type reads by special-type marker filter."""
    return Counter(json.dumps(query[TypeSchemaKey.SPECIAL_TYPE.value], default=str, sort_keys=True)
                   for collection, query, _options in finds
                   if collection == CmdbType.COLLECTION and TypeSchemaKey.SPECIAL_TYPE.value in query)


def _ids(*public_ids: int) -> str:
    """A bulk delete's id list."""
    return ','.join(map(str, public_ids))


def _exists(rest_api, public_id: int) -> bool:
    """Whether the object is still stored."""
    return rest_api.get(f'{OBJECTS_URL}/native/{public_id}').status_code == HTTPStatus.OK


def _message(response) -> str:
    """The 400's text."""
    return json.dumps(response.get_json())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the answers                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWhatIsRefused:
    """A reference from outside the request blocks; one deleted in the same request does not"""

    def test_a_supernet_with_subnets_is_refused_naming_them(self, rest_api) -> None:
        """Single delete: 400 naming both subnets, nothing deleted"""
        response = rest_api.delete(f'{OBJECTS_URL}/{SUPERNET_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Supernet is referenced by subnets: {SUBNET_A_ID}, {SUBNET_B_ID}' in _message(response)
        assert _exists(rest_api, SUPERNET_ID)

    def test_a_supernet_goes_together_with_everything_that_references_it(self, rest_api) -> None:
        """Supernet + its subnets + the subnet's VLAN and interface carrier: deleted in one request"""
        selection = (SUPERNET_ID, SUBNET_A_ID, SUBNET_B_ID, VLAN_ID, CARRIER_ID)

        response = rest_api.delete(f'{OBJECTS_URL}/delete/{_ids(*selection)}')

        assert response.status_code == HTTPStatus.OK
        assert sorted(response.get_json()['successfully']) == sorted(selection)
        assert not any(_exists(rest_api, public_id) for public_id in selection)

    def test_a_reference_left_outside_still_refuses_the_whole_selection(self, rest_api) -> None:
        """Without the VLAN in the request, subnet A is still referenced: 400, nothing deleted"""
        selection = (SUPERNET_ID, SUBNET_A_ID, SUBNET_B_ID, CARRIER_ID)

        response = rest_api.delete(f'{OBJECTS_URL}/delete/{_ids(*selection)}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Subnet is referenced by vlans: {VLAN_ID}' in _message(response)
        assert 'interface rows' not in _message(response), 'the carrier is in the selection'
        assert all(_exists(rest_api, public_id) for public_id in selection)

    def test_a_long_list_names_twenty_and_counts_the_rest(self, rest_api) -> None:
        """23 subnets: the 20 lowest ids, then 'and 3 more'"""
        response = rest_api.delete(f'{OBJECTS_URL}/{BIG_SUPERNET_ID}')

        listed = ', '.join(map(str, BIG_SUBNET_IDS[:LISTED]))
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Supernet is referenced by subnets: {listed} and 3 more' in _message(response)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the reads                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWhatTheGuardReads:
    """Counted at the driver: a selection costs the same few reference reads however many targets it holds"""

    @pytest.mark.parametrize('count', [FEW_FREE_SUBNETS, FREE_SUBNET_COUNT])
    def test_a_bulk_delete_of_free_subnets_costs_the_same_whatever_its_size(self, rest_api, finds, count) -> None:
        """One special-type read, two existence checks with limit 1 - none per target, no whole document"""
        response = rest_api.delete(f'{OBJECTS_URL}/delete/{_ids(*FREE_SUBNET_IDS[:count])}')

        assert response.status_code == HTTPStatus.OK
        reference_reads = _reference_reads(finds)
        assert len(reference_reads) == SUBNET_SELECTION_REFERENCE_READS
        assert all(options.get('limit') == 1 for options in reference_reads)
        assert all(options.get('projection') == {'_id': 0, **REFERENCE_PROJECTION} for options in reference_reads)
        ipam_type_reads = _special_type_reads(finds)
        assert sum(ipam_type_reads.values()) == SPECIAL_TYPE_READS

    def test_a_refused_delete_reads_two_keys_per_referencing_object(self, rest_api, finds) -> None:
        """The naming pass reads projected, capped documents too"""
        assert rest_api.delete(f'{OBJECTS_URL}/{BIG_SUPERNET_ID}').status_code == HTTPStatus.BAD_REQUEST

        reference_reads = _reference_reads(finds)
        assert reference_reads
        assert all(options.get('projection') == {'_id': 0, **REFERENCE_PROJECTION} for options in reference_reads)
        assert {options.get('limit') for options in reference_reads} <= {1, LISTED + 1}

    def test_the_ci_explorer_resolves_the_ipam_types_once_and_loads_only_the_cap(self, rest_api, finds) -> None:
        """A supernet with 23 subnets under item_limit=2: one IPAM type read, the bulk load capped at 2"""
        response = rest_api.get(CI_EXPLORER_URL, query_string={
            'target_id': BIG_SUPERNET_ID, 'item_limit': ITEM_LIMIT, 'with_locations': 'false',
            'with_port_connections': 'false',
        })

        assert response.status_code == HTTPStatus.OK
        ipam_markers = json.dumps({'$in': [SpecialType.SUPERNET.value, SpecialType.SUBNET.value,
                                           SpecialType.VLAN.value]}, sort_keys=True)
        assert _special_type_reads(finds)[ipam_markers] == SPECIAL_TYPE_READS
        bulk_loads = [options for collection, query, options in finds
                      if collection == CmdbObject.COLLECTION and '$in' in json.dumps(query.get('public_id', {}))
                      and options.get('limit') == ITEM_LIMIT]
        assert len(bulk_loads) == 1
        assert all(options.get('projection') == {'_id': 0, **REFERENCE_PROJECTION}
                   for options in _reference_reads(finds))
