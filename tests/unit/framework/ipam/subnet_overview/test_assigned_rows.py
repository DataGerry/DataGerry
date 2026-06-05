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
Unit tests for cmdb.framework.ipam.subnet_overview.assigned_rows

Covers the DB-facing primitives the package shares: load_subnet_object, the
aggregation-backed load_assigned_rows_map (unparsable-IP drop, empty-MAC normalization,
in/out-of-CIDR is_valid tagging, projected pipeline shape), resolve_type_meta, the CIDR
parser parse_subnet_network, the sorted views over the assigned map, and the batched
resolve_summary_lines_for_ips helper
"""
from ipaddress import IPv4Network
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamOverviewKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    load_subnet_object,
    load_assigned_rows_map,
    resolve_type_meta,
    parse_subnet_network,
    sorted_assigned_ips,
    sorted_invalid_ips,
    resolve_summary_lines_for_ips,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_TYPE_ID: int = 51

SUBNET_RANGE: str = '10.0.0.0/24'
SUBNET_RANGE_V6: str = '2001:db8::/64'
PATH: str = 'cmdb.framework.ipam.subnet_overview.assigned_rows'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_cmdb_object(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with an optional fields list."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: fields or [],
    }


def _make_subnet_doc(public_id: int, network_range: Any, subnet_type: Any = None) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field and an optional type field."""
    fields: list[dict[str, Any]] = [{
        CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
        CmdbObjectFieldKey.VALUE: network_range,
    }]

    if subnet_type is not None:
        fields.append({
            CmdbObjectFieldKey.NAME: SubnetField.TYPE,
            CmdbObjectFieldKey.VALUE: subnet_type,
        })

    return _make_cmdb_object(public_id=public_id, type_id=SUBNET_TYPE_ID, fields=fields)


def _make_assigned_entry(
    object_id: int,
    type_id: int | None,
    mac: str | None,
    is_valid: bool = True,
) -> dict[str, Any]:
    """Builds one value of the assigned map (the shape load_assigned_rows_map produces)."""
    return {
        AssignedField.OBJECT_ID: object_id,
        AssignedField.TYPE_ID: type_id,
        AssignedField.MAC: mac,
        AssignedField.IS_VALID: is_valid,
    }


def _make_aggregation_row(
    object_id: int,
    type_id: int | None,
    ip: Any,
    mac: Any,
) -> dict[str, Any]:
    """Builds one projected aggregation row as load_assigned_rows_map's pipeline ships it."""
    return {
        AssignedField.OBJECT_ID: object_id,
        AssignedField.TYPE_ID: type_id,
        AssignedField.IP: ip,
        AssignedField.MAC: mac,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              load_subnet_object                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_subnet_object_aborts_400_when_subnet_cmdbtype_not_defined() -> None:
    """No SUBNET CmdbType → HTTP 400; no object query is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400
    objects_manager.find_objects.assert_not_called()


def test_load_subnet_object_aborts_404_when_object_not_found() -> None:
    """find_objects returns empty → HTTP 404"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_load_subnet_object_aborts_400_when_object_is_not_a_subnet() -> None:
    """Found object exists but has a different type_id → HTTP 400"""
    wrong_type_doc = _make_cmdb_object(SUBNET_OBJECT_ID, type_id=SUBNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_load_subnet_object_returns_candidate_on_happy_path() -> None:
    """A correct SUBNET object id returns the loaded doc with the expected filter"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [subnet_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert result is subnet_doc
    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID}, as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          load_assigned_rows_map                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_assigned_rows_map_returns_empty_when_no_objects_match() -> None:
    """No interface rows in the system → empty map"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = []

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_indexes_matching_rows_by_canonical_ip() -> None:
    """Each in-range projected row contributes one entry keyed by its parsed IP, tagged is_valid=True"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, '10.0.0.5', 'aa:bb:cc:dd:ee:ff'),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {
        '10.0.0.5': {
            AssignedField.OBJECT_ID: OWNER_OBJECT_ID,
            AssignedField.TYPE_ID: OWNER_TYPE_ID,
            AssignedField.MAC: 'aa:bb:cc:dd:ee:ff',
            AssignedField.IS_VALID: True,
        },
    }


def test_load_assigned_rows_map_sets_mac_to_none_when_field_is_empty_string() -> None:
    """An empty-string MAC is normalized to None in the map entry"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, '10.0.0.5', ''),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result['10.0.0.5'][AssignedField.MAC] is None


def test_load_assigned_rows_map_sets_mac_to_none_when_field_missing() -> None:
    """A None MAC (the $ifNull projection result for a missing field) becomes None"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, '10.0.0.5', None),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result['10.0.0.5'][AssignedField.MAC] is None


def test_load_assigned_rows_map_skips_rows_with_unparseable_ip() -> None:
    """Rows whose IP cannot be parsed as canonical dotted-quad / IPv6 are dropped"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'not-an-ip', None),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_drops_rows_with_non_string_ip() -> None:
    """A projected row whose ip is not a string (e.g. None / int) is dropped before parsing"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, None),
        _make_aggregation_row(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, 12345, None),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_keeps_out_of_range_rows_tagged_is_valid_false() -> None:
    """Rows with IPs outside the given network are kept and tagged is_valid=False as conflicts"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = [
        _make_aggregation_row(OWNER_OBJECT_ID, OWNER_TYPE_ID, '192.168.1.5', None),
    ]

    result = load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result['192.168.1.5'][AssignedField.IS_VALID] is False
    assert result['192.168.1.5'][AssignedField.OBJECT_ID] == OWNER_OBJECT_ID


def test_load_assigned_rows_map_uses_single_aggregation_call() -> None:
    """The map is built from a single aggregate_objects round-trip; find_objects is not used"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = []

    load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    objects_manager.aggregate_objects.assert_called_once()
    objects_manager.find_objects.assert_not_called()


def test_load_assigned_rows_map_pipeline_matches_interface_section_and_subnet_ref() -> None:
    """The pipeline's first $match pins the interface section and the subnet-ref $elemMatch"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = []

    load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    [pipeline] = objects_manager.aggregate_objects.call_args.args
    first_match = pipeline[0]['$match'][CmdbObjectKey.MULTI_DATA_SECTIONS]['$elemMatch']

    assert first_match[CmdbObjectMdsKey.SECTION_ID] == IpamSection.INTERFACE
    subnet_ref = (
        first_match[CmdbObjectMdsKey.VALUES]['$elemMatch'][CmdbObjectMdsRowKey.DATA]['$elemMatch']
    )
    assert subnet_ref[CmdbObjectFieldKey.NAME] == InterfaceField.SUBNET
    assert subnet_ref[CmdbObjectFieldKey.VALUE] == SUBNET_OBJECT_ID


def test_load_assigned_rows_map_pipeline_projects_the_assigned_field_keys() -> None:
    """The final $project ships exactly the four AssignedField projection keys (and drops _id)"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = []

    load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    [pipeline] = objects_manager.aggregate_objects.call_args.args
    project = pipeline[-1]['$project']

    assert project['_id'] == 0
    assert set(project) == {
        '_id',
        AssignedField.OBJECT_ID,
        AssignedField.TYPE_ID,
        AssignedField.IP,
        AssignedField.MAC,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              resolve_type_meta                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_type_meta_returns_empty_dict_for_empty_type_ids() -> None:
    """Empty input → empty result; the bulk-lookup endpoint is not invoked"""
    types_manager = MagicMock()

    result = resolve_type_meta(types_manager, [])

    assert result == {}
    types_manager.get_types_lookup.assert_not_called()


def test_resolve_type_meta_deduplicates_input_ids_before_lookup() -> None:
    """Duplicates are collapsed via set() so the bulk-lookup endpoint gets each id once"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}

    resolve_type_meta(types_manager, [OWNER_TYPE_ID, OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    [unique_ids] = types_manager.get_types_lookup.call_args.args
    assert set(unique_ids) == {OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID}


def test_resolve_type_meta_projects_to_label_and_ci_explorer_color() -> None:
    """Each resolved CmdbType is projected to {LABEL, CI_EXPLORER_COLOR} from its attributes"""
    server_type = MagicMock(label='Server', ci_explorer_color='#FF0000')
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {OWNER_TYPE_ID: server_type}

    result = resolve_type_meta(types_manager, [OWNER_TYPE_ID])

    assert result == {
        OWNER_TYPE_ID: {
            IpamOverviewKey.LABEL: 'Server',
            IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
        },
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            parse_subnet_network                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_subnet_network_returns_ipv4network_for_valid_cidr() -> None:
    """A canonical CIDR string parses to the corresponding IPv4Network"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    result = parse_subnet_network(doc)

    assert isinstance(result, IPv4Network)
    assert str(result) == SUBNET_RANGE


def test_parse_subnet_network_returns_none_when_field_missing() -> None:
    """A subnet doc without the network-range field yields None"""
    doc = _make_cmdb_object(SUBNET_OBJECT_ID, SUBNET_TYPE_ID, fields=[])

    assert parse_subnet_network(doc) is None


def test_parse_subnet_network_returns_none_for_non_string_value() -> None:
    """A network-range field carrying a non-string value (e.g. None) yields None"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range=None)

    assert parse_subnet_network(doc) is None


def test_parse_subnet_network_returns_none_for_unparsable_string() -> None:
    """A garbled CIDR string yields None rather than raising"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='not-a-cidr')

    assert parse_subnet_network(doc) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                       sorted_assigned_ips / sorted_invalid_ips                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_sorted_assigned_ips_selects_by_validity_and_sorts_ipv6_numerically() -> None:
    """sorted_assigned_ips returns valid/invalid IPv6 rows sorted by integer address value"""
    assigned = {
        '2001:db8::10': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '2001:db8::2': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '2001:dead::1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }

    assert sorted_assigned_ips(assigned, valid=True) == ['2001:db8::2', '2001:db8::10']
    assert sorted_assigned_ips(assigned, valid=False) == ['2001:dead::1']


def test_sorted_invalid_ips_returns_empty_when_all_rows_are_valid() -> None:
    """An assigned map with no invalid rows yields an empty list (steady-state)"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None),
    }

    assert sorted_invalid_ips(assigned) == []


def test_sorted_invalid_ips_returns_invalid_ips_in_ascending_ip_order() -> None:
    """Invalid rows are returned sorted by integer IP value (not lexicographic)"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.10': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
        '192.168.1.2': _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None, is_valid=False),
    }

    assert sorted_invalid_ips(assigned) == ['192.168.1.2', '192.168.1.10']


# -------------------------------------------------------------------------------------------------------------------- #
#                                       resolve_summary_lines_for_ips                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_summary_lines_for_ips_returns_empty_for_no_assigned_candidates() -> None:
    """When no candidate IP is in the assigned map, no batch call is issued"""
    objects_manager = MagicMock()

    result = resolve_summary_lines_for_ips(
        ['10.0.0.1', '10.0.0.2'], assigned={}, objects_manager=objects_manager,
    )

    assert result == {}
    objects_manager.get_summary_lines_lookup.assert_not_called()


def test_resolve_summary_lines_for_ips_maps_summary_to_each_assigned_ip() -> None:
    """An assigned candidate IP gets the resolved summary line keyed by its IP"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {
        OWNER_OBJECT_ID: 'Server: web01',
        OWNER_OBJECT_ID + 1: 'Server: web02',
    }

    result = resolve_summary_lines_for_ips(
        ['10.0.0.1', '10.0.0.5'], assigned=assigned, objects_manager=objects_manager,
    )

    assert result == {'10.0.0.1': 'Server: web01', '10.0.0.5': 'Server: web02'}
    objects_manager.get_summary_lines_lookup.assert_called_once()


def test_resolve_summary_lines_for_ips_skips_free_candidates() -> None:
    """Candidates not present in the assigned map are absent from the result"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    result = resolve_summary_lines_for_ips(
        ['10.0.0.1', '10.0.0.2'], assigned=assigned, objects_manager=objects_manager,
    )

    assert '10.0.0.2' not in result
    assert result == {'10.0.0.1': 'Server: web01'}


def test_resolve_summary_lines_for_ips_omits_ip_when_owner_unresolvable() -> None:
    """Owner missing from the manager's lookup → IP absent from the result (treated as NULL)"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {}

    result = resolve_summary_lines_for_ips(
        ['10.0.0.1'], assigned=assigned, objects_manager=objects_manager,
    )

    assert result == {}
