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
Unit tests for cmdb.models.special_type_model.special_type_enum

Pins the member tokens and display labels of the SpecialType enum (both are wire-format
values the frontend depends on), covers the get_unused_types filter that drives the
special-type creation dialog, and the IPAM-membership split the license guards depend on
"""
import pytest

from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                               get_special_types                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_special_types_maps_every_member_to_its_display_label() -> None:
    """The full listing pins every member token and its fixed English display label"""
    assert SpecialType.get_special_types() == {
        SpecialType.SUPERNET: 'IPAM - Supernet class',
        SpecialType.SUBNET: 'IPAM - Subnet class',
        SpecialType.VLAN: 'IPAM - VLAN class',
        SpecialType.RACK: 'Rack View - Rack class',
    }


def test_get_special_types_covers_every_enum_member() -> None:
    """Adding a SpecialType member without a display label fails loudly here"""
    assert set(SpecialType.get_special_types()) == set(SpecialType)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_unused_types                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_unused_types_omits_claimed_special_types() -> None:
    """A SpecialType value present in 'existing' drops out of the offer"""
    unused = SpecialType.get_unused_types([SpecialType.SUBNET.value])

    assert set(unused) == {SpecialType.SUPERNET, SpecialType.VLAN, SpecialType.RACK}


def test_get_unused_types_returns_everything_when_nothing_exists() -> None:
    """An empty 'existing' iterable leaves the full listing intact"""
    assert SpecialType.get_unused_types([]) == SpecialType.get_special_types()


def test_get_unused_types_returns_empty_when_all_claimed() -> None:
    """With every member claimed, nothing is offered"""
    assert SpecialType.get_unused_types([m.value for m in SpecialType]) == {}


def test_get_unused_types_ignores_unknown_tokens() -> None:
    """Tokens in 'existing' that are no SpecialType value have no effect on the offer"""
    unused = SpecialType.get_unused_types(['NOT-A-SPECIAL-TYPE'])

    assert unused == SpecialType.get_special_types()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          IPAM membership (license gating)                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_ipam_types_holds_exactly_the_three_ipam_members() -> None:
    """The IPAM feature owns SUPERNET / SUBNET / VLAN and nothing else"""
    assert SpecialType.get_ipam_types() == frozenset(
        {SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN}
    )


@pytest.mark.parametrize('value', [
    SpecialType.SUPERNET,
    SpecialType.SUBNET,
    SpecialType.VLAN,
    'SUPERNET',
    'SUBNET',
    'VLAN',
], ids=str)
def test_is_ipam_type_accepts_members_and_their_raw_values(value: object) -> None:
    """The guards pass raw stored markers straight in, so plain strings must resolve too"""
    assert SpecialType.is_ipam_type(value) is True


def test_is_ipam_type_rejects_rack() -> None:
    """
    RACK is a SpecialType that IPAM does not own

    This is what keeps creating a Rack from demanding an IPAM license - the type/object license
    guards used to treat the mere presence of a 'special_type' marker as proof of IPAM.
    """
    assert SpecialType.is_ipam_type(SpecialType.RACK) is False
    assert SpecialType.is_ipam_type('RACK') is False


@pytest.mark.parametrize('value', [None, '', 'NOT-A-SPECIAL-TYPE', 0], ids=str)
def test_is_ipam_type_tolerates_non_special_type_values(value: object) -> None:
    """A missing or unknown marker is simply not IPAM, never an error"""
    assert SpecialType.is_ipam_type(value) is False
