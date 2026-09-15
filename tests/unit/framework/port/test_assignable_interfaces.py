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
Unit tests for the assignable-interfaces picker builders

Pure tests: the CmdbObject documents and the three bulk lookups are handed in, so the two rules that
decide what is offered (a row needs a multi_data_id, a row this port already links is out), the value
resolution and the search / pagination are exercised without a database.

The row's first three keys are the create route's own field names - that is the point of the payload,
and it is asserted directly rather than through a comment, because a rename on either side would
silently turn the picker into something the create route cannot read.
"""
from typing import Any

from cmdb.models.port_interface_link_model import (
    AssignableInterfaceKey,
    AssignableInterfaceObjectKey,
    AssignableInterfaceSubnetKey,
    PortInterfaceLinkKey,
)
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamOverviewKey, IpamSection
from cmdb.framework.port.assignable_interfaces import (
    build_assignable_interface_row,
    build_assignable_interface_rows,
    build_assignable_interfaces_page,
    build_subnet_lookup,
    interface_rows_of_object,
    is_offerable,
    read_row_value,
    referenced_subnet_ids,
    row_matches_search,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 7100
OTHER_OBJECT_ID: int = 7101
TYPE_ID: int = 7200
SUBNET_ID: int = 7300

ROW_ID: int = 1
OTHER_ROW_ID: int = 2

ROW_IP: str = '10.0.0.1'
ROW_MAC: str = '00:1A:2B:3C:4D:5E'
ROW_HOST: str = 'edge-switch'
ROW_DOMAIN: str = 'example.test'

TYPE_LABEL: str = 'Switch'
SUMMARY_LINE: str = 'Switch / edge-01'
SUBNET_NAME: str = 'Office LAN'

TYPE_LABELS: dict[int, str] = {TYPE_ID: TYPE_LABEL}
SUMMARY_LINES: dict[int, str] = {OBJECT_ID: SUMMARY_LINE, OTHER_OBJECT_ID: SUMMARY_LINE}
SUBNET_NAMES: dict[int, str] = {SUBNET_ID: SUBNET_NAME}

OTHER_SECTION: str = 'dg-some-other-section'


def _row(multi_data_id: Any = ROW_ID, ip: str = ROW_IP, subnet_id: Any = SUBNET_ID) -> dict[str, Any]:
    """One dg-ipam-interface MDS row carrying every declared field."""
    data = [
        {'name': InterfaceField.ACTIVE.value, 'value': True, 'type': 'checkbox'},
        {'name': InterfaceField.TYPE.value, 'value': 'ipv4', 'type': 'select'},
        {'name': InterfaceField.SUBNET.value, 'value': subnet_id, 'type': 'ref'},
        {'name': InterfaceField.IP.value, 'value': ip, 'type': 'text'},
        {'name': InterfaceField.HOST.value, 'value': ROW_HOST, 'type': 'text'},
        {'name': InterfaceField.DOMAIN.value, 'value': ROW_DOMAIN, 'type': 'text'},
        {'name': InterfaceField.MAC.value, 'value': ROW_MAC, 'type': 'text'},
    ]

    row: dict[str, Any] = {'data': data}

    if multi_data_id is not None:
        row['multi_data_id'] = multi_data_id

    return row


def _object(public_id: int = OBJECT_ID, rows: list[dict[str, Any]] | None = None,
            section_id: str = IpamSection.INTERFACE.value) -> dict[str, Any]:
    """A CmdbObject carrying one MDS section with the given rows."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'multi_data_sections': [{
            'section_id': section_id,
            'highest_id': OTHER_ROW_ID,
            'values': rows if rows is not None else [_row()],
        }],
    }


def _rows_of(*object_docs: dict[str, Any], linked: set[tuple[Any, Any]] | None = None) -> list[dict[str, Any]]:
    """Shapes the offerable rows of the given objects with the standard lookups."""
    return build_assignable_interface_rows(
        list(object_docs), linked or set(), TYPE_LABELS, SUMMARY_LINES, SUBNET_NAMES,
    )


# -------------------------------------------------------------------------------------------------------------------- #
class TestReadRowValue:
    """Reading one field out of an MDS row."""

    def test_reads_by_name(self) -> None:
        """The ordinary case"""
        assert read_row_value(_row(), InterfaceField.MAC.value) == ROW_MAC

    def test_an_absent_field_is_none(self) -> None:
        """A row written before a field was declared answers None rather than raising"""
        assert read_row_value({'data': []}, InterfaceField.IP.value) is None

    def test_a_row_without_data_is_none(self) -> None:
        """A drifted document must not take the picker down"""
        assert read_row_value({}, InterfaceField.IP.value) is None


class TestInterfaceRowsOfObject:
    """Finding the interface rows on an object."""

    def test_returns_the_sections_rows(self) -> None:
        """The ordinary case"""
        assert len(interface_rows_of_object(_object(rows=[_row(), _row(OTHER_ROW_ID)]))) == 2

    def test_another_section_contributes_nothing(self) -> None:
        """Only the IPAM interface section holds interfaces"""
        assert interface_rows_of_object(_object(section_id=OTHER_SECTION)) == []

    def test_an_object_without_sections_is_empty(self) -> None:
        """Not every object carries interfaces"""
        assert interface_rows_of_object({'public_id': OBJECT_ID}) == []


class TestIsOfferable:
    """The two exclusion rules."""

    def test_a_row_with_an_id_is_offerable(self) -> None:
        """The ordinary case"""
        assert is_offerable(_row(), OBJECT_ID, set()) is True

    def test_a_row_without_a_multi_data_id_is_not(self) -> None:
        """The create route refuses it, so offering it would promise a refusal"""
        assert is_offerable(_row(multi_data_id=None), OBJECT_ID, set()) is False

    def test_an_already_linked_row_is_not(self) -> None:
        """The unique index refuses the second link of the same pair"""
        assert is_offerable(_row(), OBJECT_ID, {(OBJECT_ID, ROW_ID)}) is False

    def test_the_exclusion_is_per_object(self) -> None:
        """Same row id, different object - the triple is what identifies a row, not the id alone"""
        assert is_offerable(_row(), OBJECT_ID, {(OTHER_OBJECT_ID, ROW_ID)}) is True


class TestRowShape:
    """What one picker row carries."""

    def test_the_triple_uses_the_create_routes_key_names(self) -> None:
        """
        The payload contract: selecting a row and posting it must be a copy, not a translation

        A rename on either side would leave the picker producing something the create route cannot read,
        and nothing else would notice.
        """
        row = build_assignable_interface_row(_object(), _row(), TYPE_LABELS, SUMMARY_LINES, SUBNET_NAMES)

        assert row[PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value] == OBJECT_ID
        assert row[PortInterfaceLinkKey.INTERFACE_SECTION_ID.value] == IpamSection.INTERFACE.value
        assert row[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value] == ROW_ID

    def test_the_interface_values_are_resolved(self) -> None:
        """The FE renders the table without knowing one dg-interface-* field name"""
        row = build_assignable_interface_row(_object(), _row(), TYPE_LABELS, SUMMARY_LINES, SUBNET_NAMES)

        assert (row[AssignableInterfaceKey.IP.value], row[AssignableInterfaceKey.MAC.value]) == (ROW_IP, ROW_MAC)
        assert row[AssignableInterfaceKey.HOSTNAME.value] == ROW_HOST
        assert row[AssignableInterfaceKey.DOMAIN.value] == ROW_DOMAIN
        assert row[AssignableInterfaceKey.ADDRESS_FAMILY.value] == 'ipv4'
        assert row[AssignableInterfaceKey.ACTIVE.value] is True

    def test_the_subnet_is_resolved_to_id_and_name(self) -> None:
        """A reference is a number on the row; the picker has to show something readable"""
        row = build_assignable_interface_row(_object(), _row(), TYPE_LABELS, SUMMARY_LINES, SUBNET_NAMES)

        assert row[AssignableInterfaceKey.SUBNET.value] == {
            AssignableInterfaceSubnetKey.PUBLIC_ID.value: SUBNET_ID,
            AssignableInterfaceSubnetKey.NAME.value: SUBNET_NAME,
        }

    def test_a_subnet_that_no_longer_resolves_is_none(self) -> None:
        """A deleted subnet leaves the row usable - the link does not depend on it"""
        row = build_assignable_interface_row(_object(), _row(), TYPE_LABELS, SUMMARY_LINES, {})

        assert row[AssignableInterfaceKey.SUBNET.value] is None

    def test_a_row_without_a_subnet_is_none(self) -> None:
        """An interface may carry an address with no network reference"""
        row = build_assignable_interface_row(_object(), _row(subnet_id=None), TYPE_LABELS,
                                             SUMMARY_LINES, SUBNET_NAMES)

        assert row[AssignableInterfaceKey.SUBNET.value] is None

    def test_the_object_is_described(self) -> None:
        """Two devices can hold the same IP in different subnets - the device is part of the choice"""
        row = build_assignable_interface_row(_object(), _row(), TYPE_LABELS, SUMMARY_LINES, SUBNET_NAMES)

        assert row[AssignableInterfaceKey.OBJECT_INFO.value] == {
            AssignableInterfaceObjectKey.PUBLIC_ID.value: OBJECT_ID,
            AssignableInterfaceObjectKey.TYPE_ID.value: TYPE_ID,
            AssignableInterfaceObjectKey.TYPE_LABEL.value: TYPE_LABEL,
            AssignableInterfaceObjectKey.SUMMARY_LINE.value: SUMMARY_LINE,
        }

    def test_missing_lookups_fall_back_to_empty_strings(self) -> None:
        """An unresolvable type or summary line must not drop the row the user is looking for"""
        row = build_assignable_interface_row(_object(), _row(), {}, {}, {})

        assert row[AssignableInterfaceKey.OBJECT_INFO.value][
            AssignableInterfaceObjectKey.TYPE_LABEL.value] == ''
        assert row[AssignableInterfaceKey.OBJECT_INFO.value][
            AssignableInterfaceObjectKey.SUMMARY_LINE.value] == ''


class TestRowCollection:
    """Which rows come out, and in which order."""

    def test_every_offerable_row_is_shaped(self) -> None:
        """A device with a bond and a VLAN sub-interface offers both"""
        assert len(_rows_of(_object(rows=[_row(), _row(OTHER_ROW_ID)]))) == 2

    def test_the_rules_are_applied(self) -> None:
        """An id-less row and an already-linked row both drop out"""
        rows = _rows_of(
            _object(rows=[_row(), _row(OTHER_ROW_ID), _row(multi_data_id=None)]),
            linked={(OBJECT_ID, ROW_ID)},
        )

        assert [row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value] for row in rows] == [OTHER_ROW_ID]

    def test_the_order_is_stable(self) -> None:
        """
        A page boundary has to mean the same thing on every request

        The rows come out of documents rather than out of an ordered query, so nothing but this sort
        keeps page 2 from repeating a row of page 1.
        """
        rows = _rows_of(
            _object(OTHER_OBJECT_ID, rows=[_row(OTHER_ROW_ID), _row(ROW_ID)]),
            _object(OBJECT_ID, rows=[_row(OTHER_ROW_ID), _row(ROW_ID)]),
        )
        ordered = [(row[AssignableInterfaceKey.INTERFACE_OBJECT_ID.value],
                    row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value]) for row in rows]

        assert ordered == sorted(ordered)

    def test_an_object_without_rows_contributes_nothing(self) -> None:
        """Not a 404, just nothing to offer"""
        assert _rows_of(_object(rows=[])) == []


class TestSubnetCollection:
    """The subnet ids the page has to resolve."""

    def test_each_referenced_subnet_is_collected_once(self) -> None:
        """Five sub-interfaces on one subnet must not cost five reads"""
        assert referenced_subnet_ids([_object(rows=[_row(), _row(OTHER_ROW_ID)])]) == [SUBNET_ID]

    def test_rows_without_a_subnet_are_skipped(self) -> None:
        """Nothing to resolve, nothing to query"""
        assert referenced_subnet_ids([_object(rows=[_row(subnet_id=None)])]) == []

    def test_the_lookup_reads_the_name_field(self) -> None:
        """The subnet's name comes from its own SpecialType field"""
        subnet_doc = {'public_id': SUBNET_ID, 'fields': [{'name': 'dg-name', 'value': SUBNET_NAME}]}

        assert build_subnet_lookup([subnet_doc]) == {SUBNET_ID: SUBNET_NAME}


class TestSearch:
    """What a query matches."""

    def test_the_ip_matches(self) -> None:
        """The obvious one"""
        assert row_matches_search(_rows_of(_object())[0], '10.0.0') is True

    def test_the_mac_matches_case_insensitively(self) -> None:
        """A MAC is typed in whatever case the source printed it"""
        assert row_matches_search(_rows_of(_object())[0], '3c:4d') is True

    def test_the_subnet_name_matches(self) -> None:
        """'which interface is on the office LAN' is a real question"""
        assert row_matches_search(_rows_of(_object())[0], 'office') is True

    def test_the_owning_device_matches(self) -> None:
        """The device answers 'which interface is this' as often as the address does"""
        assert row_matches_search(_rows_of(_object())[0], 'edge-01') is True

    def test_an_unrelated_query_does_not(self) -> None:
        """The filter has to narrow"""
        assert row_matches_search(_rows_of(_object())[0], 'nothing-like-this') is False


class TestPageEnvelope:
    """Search, pagination and the response shape."""

    def test_the_envelope_carries_the_page_and_the_total(self) -> None:
        """The shape the IPAM pickers answer with"""
        page = build_assignable_interfaces_page(_rows_of(_object()), page=1, page_size=50, search='')

        assert page[IpamOverviewKey.TOTAL] == 1
        assert len(page[IpamOverviewKey.ROWS]) == 1
        assert page[IpamOverviewKey.PAGE] == 1

    def test_the_total_is_the_post_filter_count(self) -> None:
        """A client paginating a filtered list must not be told about rows it will never see"""
        rows = _rows_of(_object(rows=[_row(), _row(OTHER_ROW_ID, ip='192.168.5.9')]))

        page = build_assignable_interfaces_page(rows, page=1, page_size=50, search='192.168')

        assert page[IpamOverviewKey.TOTAL] == 1
        assert page[IpamOverviewKey.ROWS][0][AssignableInterfaceKey.IP.value] == '192.168.5.9'

    def test_a_short_query_is_not_a_filter(self) -> None:
        """One typed character is the user still typing, not a filter"""
        page = build_assignable_interfaces_page(_rows_of(_object()), page=1, page_size=50, search='x')

        assert page[IpamOverviewKey.TOTAL] == 1
        assert page[IpamOverviewKey.SEARCH] == ''

    def test_the_page_is_clamped(self) -> None:
        """A page past the end answers the last page rather than an empty list"""
        page = build_assignable_interfaces_page(_rows_of(_object()), page=99, page_size=50, search='')

        assert page[IpamOverviewKey.PAGE] == 1
        assert len(page[IpamOverviewKey.ROWS]) == 1

    def test_pagination_cuts_the_rows(self) -> None:
        """The page size is what the caller asked for, within the clamps"""
        rows = _rows_of(_object(rows=[_row(), _row(OTHER_ROW_ID)]))

        page = build_assignable_interfaces_page(rows, page=2, page_size=1, search='')

        assert page[IpamOverviewKey.TOTAL] == 2
        assert [row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value]
                for row in page[IpamOverviewKey.ROWS]] == [OTHER_ROW_ID]
