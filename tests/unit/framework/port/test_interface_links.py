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
Unit tests for cmdb.framework.port.interface_links

The resolution of a SOFT reference, and the detection of when it no longer resolves.

Two things carry these tests. First, that a row id is only unique WITHIN its section, so the section
has to be part of the match - looking a row up by id alone would silently return a row of another
section whenever the two happen to share a number, and the link would resolve to the wrong interface.
Second, that a link is dangling for three different reasons - the object is gone, the section is gone,
the row is gone - which all read the same to the customer and must all be reported.

Pure tests: the CmdbObject documents are handed in as plain dicts, no Mongo and no managers
"""
from typing import Any

import pytest

from cmdb.framework.port.interface_links import (
    collect_dangling_links,
    find_interface_row,
    group_links_by_interface_object,
    is_dangling,
    resolve_link_row,
)
from cmdb.models.port_interface_link_model import PortInterfaceLinkKey
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 8100
OTHER_OBJECT_ID: int = 8101
ROW_ID: int = 3
OTHER_ROW_ID: int = 4
OTHER_SECTION: str = 'dg-some-other-section'


def _row(multi_data_id: int, ip: str = '10.0.0.1') -> dict[str, Any]:
    """One MDS row of the dg-ipam-interface section."""
    return {
        'multi_data_id': multi_data_id,
        'data': [{'name': InterfaceField.IP.value, 'value': ip, 'type': 'text'}],
    }


def _object(
        public_id: int = OBJECT_ID,
        section_id: str = IpamSection.INTERFACE.value,
        rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A CmdbObject carrying one MDS section with the given rows."""
    return {
        'public_id': public_id,
        'multi_data_sections': [{
            'section_id': section_id,
            'highest_id': ROW_ID,
            'values': rows if rows is not None else [_row(ROW_ID)],
        }],
    }


def _link(
        object_id: int = OBJECT_ID,
        section_id: str = IpamSection.INTERFACE.value,
        multi_data_id: int = ROW_ID) -> dict[str, Any]:
    """A stored CmdbPortInterfaceLink document."""
    return {
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: object_id,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: section_id,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: multi_data_id,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              finding the interface row                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindInterfaceRow:
    """Resolving the triple to one MDS row."""

    def test_the_addressed_row_is_returned(self) -> None:
        """The ordinary case"""
        row = find_interface_row(_object(), IpamSection.INTERFACE.value, ROW_ID)

        assert row is not None
        assert row['multi_data_id'] == ROW_ID

    def test_the_right_row_is_picked_out_of_several(self) -> None:
        """A device with a bond and two VLAN sub-interfaces has several rows in one section"""
        obj = _object(rows=[_row(ROW_ID, '10.0.0.1'), _row(OTHER_ROW_ID, '10.0.0.2')])

        row = find_interface_row(obj, IpamSection.INTERFACE.value, OTHER_ROW_ID)

        assert row['data'][0]['value'] == '10.0.0.2'

    def test_the_section_has_to_match_too(self) -> None:
        """
        The reason the section is part of the reference and not assumed

        A row id is unique only WITHIN its section, so matching on the id alone would return a row of
        an unrelated section whenever the two happen to share a number - and the link would silently
        resolve to the wrong interface rather than reporting itself broken.
        """
        obj = _object(section_id=OTHER_SECTION)

        assert find_interface_row(obj, IpamSection.INTERFACE.value, ROW_ID) is None

    def test_a_missing_object_resolves_to_nothing(self) -> None:
        """The object was deleted - one of the three ways a link goes dangling"""
        assert find_interface_row(None, IpamSection.INTERFACE.value, ROW_ID) is None

    def test_a_missing_row_resolves_to_nothing(self) -> None:
        """The row was removed from a section that still exists"""
        assert find_interface_row(_object(), IpamSection.INTERFACE.value, OTHER_ROW_ID) is None

    def test_an_object_without_any_sections_resolves_to_nothing(self) -> None:
        """Every MDS row was removed, or the object never had that section"""
        assert find_interface_row({'public_id': OBJECT_ID}, IpamSection.INTERFACE.value, ROW_ID) is None

    @pytest.mark.parametrize('sections', [None, []], ids=['null', 'empty'])
    def test_a_null_or_empty_section_list_is_tolerated(self, sections: Any) -> None:
        """A read path must never fail on a document shape it did not write"""
        obj: dict[str, Any] = {'public_id': OBJECT_ID, 'multi_data_sections': sections}

        assert find_interface_row(obj, IpamSection.INTERFACE.value, ROW_ID) is None

    def test_a_section_with_no_values_is_tolerated(self) -> None:
        """An MDS section that exists but holds no rows"""
        obj: dict[str, Any] = {
            'public_id': OBJECT_ID,
            'multi_data_sections': [{'section_id': IpamSection.INTERFACE.value, 'values': None}],
        }

        assert find_interface_row(obj, IpamSection.INTERFACE.value, ROW_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                resolving a link                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveLinkRow:
    """The same lookup, driven from a stored link."""

    def test_a_live_link_resolves(self) -> None:
        """The ordinary case"""
        assert resolve_link_row(_link(), _object()) is not None

    def test_a_link_reads_its_own_section_and_row(self) -> None:
        """
        The triple is taken from the LINK, not assumed

        A link written when a second interface-bearing section existed still resolves against its own
        stored section rather than against today's default.
        """
        obj = _object(section_id=OTHER_SECTION)

        assert resolve_link_row(_link(section_id=OTHER_SECTION), obj) is not None

    def test_a_dangling_link_resolves_to_nothing(self) -> None:
        """The row was renumbered or removed by an object write"""
        assert resolve_link_row(_link(multi_data_id=OTHER_ROW_ID), _object()) is None


class TestIsDangling:
    """The predicate the report is built on."""

    def test_a_live_link_is_not_dangling(self) -> None:
        """The ordinary case"""
        assert is_dangling(_link(), _object()) is False

    @pytest.mark.parametrize('link,interface_object,reason', [
        (_link(), None, 'object gone'),
        (_link(section_id=OTHER_SECTION), _object(), 'section gone'),
        (_link(multi_data_id=OTHER_ROW_ID), _object(), 'row gone'),
    ], ids=['object-gone', 'section-gone', 'row-gone'])
    def test_every_way_a_link_can_break_is_reported(
            self, link: dict[str, Any], interface_object: Any, reason: str) -> None:
        """
        Three different causes, one answer

        They all read the same to a customer - what they named is not there - and all three have to
        reach the repair report, or the damage they can actually see would go unlisted.
        """
        assert is_dangling(link, interface_object) is True, reason


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the grouping                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupLinksByInterfaceObject:
    """Grouping is what turns one read per link into one read per object."""

    def test_links_are_grouped_by_their_object(self) -> None:
        """A port with several interfaces on the same peer shares one object read"""
        grouped = group_links_by_interface_object([
            _link(multi_data_id=ROW_ID),
            _link(multi_data_id=OTHER_ROW_ID),
            _link(object_id=OTHER_OBJECT_ID),
        ])

        assert sorted(grouped) == [OBJECT_ID, OTHER_OBJECT_ID]
        assert len(grouped[OBJECT_ID]) == 2

    def test_no_links_group_to_nothing(self) -> None:
        """The common case on an installation that documents no interfaces"""
        assert group_links_by_interface_object([]) == {}

    @pytest.mark.parametrize('object_id', [None, 'not-an-id'], ids=str)
    def test_a_link_without_a_usable_object_id_is_dropped(self, object_id: Any) -> None:
        """There is no object to check such a link against, so it cannot be judged either way"""
        assert group_links_by_interface_object([_link(object_id=object_id)]) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the dangling-link report                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectDanglingLinks:
    """The body of the repair report."""

    def test_a_live_installation_reports_nothing(self) -> None:
        """Nothing to repair is the normal state"""
        assert collect_dangling_links([_link()], {OBJECT_ID: _object()}) == []

    def test_only_the_broken_links_are_reported(self) -> None:
        """The report is a repair list, not an inventory"""
        obj = _object(rows=[_row(ROW_ID)])
        broken = _link(multi_data_id=OTHER_ROW_ID)

        dangling = collect_dangling_links([_link(), broken], {OBJECT_ID: obj})

        assert dangling == [broken]

    def test_an_object_missing_from_the_mapping_is_treated_as_deleted(self) -> None:
        """
        The caller reads exactly the objects the links name, so absence means the read found nothing

        Treating it as 'unknown' instead would hide the most obvious breakage of all - the whole
        object having been deleted.
        """
        assert collect_dangling_links([_link()], {}) == [_link()]

    def test_links_of_several_objects_are_all_judged(self) -> None:
        """One broken link must not be hidden by another object being fine"""
        dangling = collect_dangling_links(
            [_link(), _link(object_id=OTHER_OBJECT_ID)],
            {OBJECT_ID: _object(), OTHER_OBJECT_ID: _object(OTHER_OBJECT_ID, rows=[])},
        )

        assert dangling == [_link(object_id=OTHER_OBJECT_ID)]

    def test_the_given_order_is_preserved(self) -> None:
        """The report reads in the order the links were fetched, not grouped by object behind the scenes"""
        first = _link(multi_data_id=OTHER_ROW_ID)
        second = _link(object_id=OTHER_OBJECT_ID)

        dangling = collect_dangling_links([first, second], {OBJECT_ID: _object()})

        assert dangling == [first, second]

    def test_no_links_report_nothing(self) -> None:
        """An installation with no links at all"""
        assert collect_dangling_links([], {}) == []
