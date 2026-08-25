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
The SpecialType enum: CmdbType flavours that carry framework-level IPAM behaviour

A CmdbType marks itself as a SpecialType via its schema's 'special_type' key. On creation
such a type receives its predefined schema (see cmdb.models.special_type_model.schemas) and
the IPAM cross-wiring (reference fields, dg-ipam-interface template; see
cmdb.framework.ipam.special_type_wiring). The enum extends BaseStrEnum so members are
interchangeable with their string values for dict lookup, equality and JSON serialization
"""
from typing import Any, Iterable

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SpecialType(BaseStrEnum):
    """
    The available SpecialType tokens stored under a CmdbType schema's 'special_type' key

    At most one CmdbType per member may exist in an installation - the special-type creation
    route only offers members not yet claimed (see ``get_unused_types``). The string values
    are the wire-format tokens exchanged with the frontend
    """
    SUPERNET = 'SUPERNET'
    SUBNET = 'SUBNET'
    VLAN = 'VLAN'
    RACK = 'RACK'


    @classmethod
    def get_special_types(cls) -> dict[str, str]:
        """
        Returns every SpecialType member mapped to its user-facing display label

        Backs the special-type listing route when existing special types are not filtered
        out; the labels are the fixed English strings the frontend shows in the creation
        dialog

        Returns:
            dict[str, str]: {member: display label} for every member of the enum
        """
        return {
            cls.SUPERNET: "IPAM - Supernet class",
            cls.SUBNET: "IPAM - Subnet class",
            cls.VLAN: "IPAM - VLAN class",
            cls.RACK: "Rack View - Rack class"
        }


    @classmethod
    def get_ipam_types(cls) -> frozenset["SpecialType"]:
        """
        Returns the SpecialTypes belonging to the IPAM feature

        Not every SpecialType is an IPAM type: the license guards on the CmdbType and CmdbObject
        write paths gate the IPAM feature, so they must ask which members it actually covers instead
        of treating the presence of a 'special_type' marker as proof of IPAM

        Returns:
            frozenset[SpecialType]: The IPAM SpecialType members
        """
        return frozenset({cls.SUPERNET, cls.SUBNET, cls.VLAN})


    @classmethod
    def get_license_gated_types(cls) -> frozenset["SpecialType"]:
        """
        Returns the SpecialTypes whose management requires a licensed feature

        Every member here is currently gated behind ``LicenseFeature.IPAM`` - including RACK, which is
        an INTERIM decision: RACK is not an IPAM type (see get_ipam_types, which stays accurate) and
        the Rack View is expected to get a LicenseFeature of its own. One flat set is therefore
        enough while there is exactly one gating feature; the moment a second one exists this has to
        become a per-member mapping from SpecialType to LicenseFeature, and every caller listed in
        the class docstring has to pass the mapped feature instead of a hard-coded IPAM

        Kept separate from get_ipam_types deliberately. Folding RACK into that set would make
        ``is_ipam_type(RACK)`` true and silently change what the IPAM overviews, the wiring and the
        importer treat as an IPAM type - the exact conflation that had to be unpicked from four
        places when RACK was introduced

        Returns:
            frozenset[SpecialType]: The SpecialType members whose writes require a license
        """
        return cls.get_ipam_types() | frozenset({cls.RACK})


    @classmethod
    def is_license_gated(cls, value: Any) -> bool:
        """
        Checks whether a value names a SpecialType whose management requires a licensed feature

        The predicate behind every license guard on the type, object and import write paths. Tolerates
        None and any non-SpecialType value so a raw stored marker can be passed straight in

        Args:
            value (Any): A SpecialType member, its string value, or anything else

        Returns:
            bool: True if the value names a license-gated SpecialType, else False
        """
        if not cls.is_valid(value):
            return False

        return cls(value) in cls.get_license_gated_types()


    @classmethod
    def is_ipam_type(cls, value: Any) -> bool:
        """
        Checks whether a value names an IPAM SpecialType

        Tolerates None and any non-SpecialType value so the license guards can pass a raw stored
        marker straight in without pre-validating it

        Args:
            value (Any): A SpecialType member, its string value, or anything else

        Returns:
            bool: True if the value is one of the IPAM SpecialTypes, else False
        """
        if not cls.is_valid(value):
            return False

        return cls(value) in cls.get_ipam_types()


    @classmethod
    def get_unused_types(cls, existing: Iterable[str]) -> dict[str, str]:
        """
        Returns the SpecialTypes not yet claimed by an existing CmdbType, with display labels

        Drives the special-type creation dialog: each SpecialType may exist at most once, so
        members whose value appears in ``existing`` are omitted from the result

        Args:
            existing (Iterable[str]): SpecialType values already claimed by existing CmdbTypes

        Returns:
            dict[str, str]: {member: display label} for every member not in ``existing``
        """
        existing_set: set[str] = set(existing)

        unused_types: dict[str, str] = {
            key: value
            for key, value in cls.get_special_types().items()
            if key not in existing_set
        }

        return unused_types
