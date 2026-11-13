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
The SpecialType enum: CmdbType flavours that carry framework-level behaviour

A CmdbType marks itself as a SpecialType via its schema's 'special_type' key. On creation
such a type receives its predefined schema (see cmdb.models.special_type_model.schemas) and
the IPAM cross-wiring (reference fields, dg-ipam-interface template; see
cmdb.framework.ipam.special_type_wiring). The enum extends BaseStrEnum so members are
interchangeable with their string values for dict lookup, equality and JSON serialization

Two properties vary per member. **Singleton**: SUPERNET, SUBNET, VLAN, RACK and CABLE are carried by at most one
CmdbType - the IPAM, Rack and Port code looks the Type up expecting exactly one, and a partial unique index over
these markers holds it; PERSON and PERSON_GROUP may be carried by any number of Types, so every reader of those asks
for all Types with the marker. **Creatable**: a member can be chosen for a new Type only once its schema exists;
PERSON and PERSON_GROUP are not creatable yet, because the person selector field their schemas need is not built
"""
from typing import Any, Iterable

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SpecialType(BaseStrEnum):
    """
    The available SpecialType tokens stored under a CmdbType schema's 'special_type' key

    A singleton member (``is_singleton``) is carried by at most one CmdbType - the special-type creation route only
    offers singletons not yet claimed (see ``get_unused_types``); PERSON and PERSON_GROUP may be carried by several.
    The string values are the wire-format tokens exchanged with the frontend
    """
    SUPERNET = 'SUPERNET'
    SUBNET = 'SUBNET'
    VLAN = 'VLAN'
    RACK = 'RACK'
    CABLE = 'CABLE'
    PERSON = 'PERSON'
    PERSON_GROUP = 'PERSON_GROUP'


    @classmethod
    def get_multiple_types(cls) -> frozenset["SpecialType"]:
        """
        Returns the SpecialTypes any number of CmdbTypes may carry

        Returns:
            frozenset[SpecialType]: The members that are not singletons
        """
        return frozenset({cls.PERSON, cls.PERSON_GROUP})


    @classmethod
    def get_singleton_types(cls) -> frozenset["SpecialType"]:
        """
        Returns the SpecialTypes at most one CmdbType may carry - the markers the partial unique index covers

        Returns:
            frozenset[SpecialType]: Every member that is not in ``get_multiple_types``
        """
        return frozenset(cls) - cls.get_multiple_types()


    @classmethod
    def is_singleton(cls, value: Any) -> bool:
        """
        Checks whether a value names a SpecialType at most one CmdbType may carry

        Tolerates None and any non-SpecialType value, so a raw payload or stored marker can be passed straight in

        Args:
            value (Any): A SpecialType member, its string value, or anything else

        Returns:
            bool: True if the value names a singleton SpecialType, else False
        """
        if not cls.is_valid(value):
            return False

        return cls(value) in cls.get_singleton_types()


    @classmethod
    def get_creatable_types(cls) -> frozenset["SpecialType"]:
        """
        Returns the SpecialTypes a new CmdbType may carry - the members whose schema exists

        Returns:
            frozenset[SpecialType]: The members offered for a new Type
        """
        return frozenset(cls) - frozenset({cls.PERSON, cls.PERSON_GROUP})


    @classmethod
    def is_creatable(cls, value: Any) -> bool:
        """
        Checks whether a value names a SpecialType a new CmdbType may carry

        Args:
            value (Any): A SpecialType member, its string value, or anything else

        Returns:
            bool: True if the value names a creatable SpecialType, else False
        """
        if not cls.is_valid(value):
            return False

        return cls(value) in cls.get_creatable_types()


    @classmethod
    def get_special_types(cls) -> dict[str, str]:
        """
        Returns every creatable SpecialType member mapped to its user-facing display label

        Backs the special-type listing route when existing special types are not filtered
        out; the labels are the fixed English strings the frontend shows in the creation
        dialog. A member that is not creatable yet is not offered

        Returns:
            dict[str, str]: {member: display label} for every creatable member
        """
        return {
            cls.SUPERNET: "IPAM - Supernet class",
            cls.SUBNET: "IPAM - Subnet class",
            cls.VLAN: "IPAM - VLAN class",
            cls.RACK: "Rack View - Rack class",
            cls.CABLE: "Port Connectivity - Cable class"
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

        PERSON and PERSON_GROUP are not here by decision: persons are needed in every edition. Every member here is
        gated behind ``LicenseFeature.IPAM``, the "Networks" licence, which
        covers IPAM, Rack View and Port Connectivity together. RACK and CABLE are in the set by
        decision, not because they are IPAM types: the IPAM licence sells Rack View (RACK) and the
        Port Connectivity design's decision D6 gates the whole port feature behind it (CABLE).
        get_ipam_types stays the narrower, accurate answer to "is this an IPAM type". One flat set is
        enough while every gated member maps to the one feature; should a member ever get a feature
        of its own, this becomes a per-member mapping from SpecialType to LicenseFeature, read by
        ``types_helper.special_type_license_feature``

        Kept separate from get_ipam_types deliberately. Folding RACK or CABLE into that set would
        make ``is_ipam_type`` true for them and silently change what the IPAM overviews, the wiring
        and the importer treat as an IPAM type - the exact conflation that had to be unpicked from
        four places when RACK was introduced

        Returns:
            frozenset[SpecialType]: The SpecialType members whose writes require a license
        """
        return cls.get_ipam_types() | frozenset({cls.RACK, cls.CABLE})


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
        Returns the SpecialTypes a new CmdbType may still take, with display labels

        Drives the special-type creation dialog: a singleton SpecialType may exist at most once, so a singleton
        whose value appears in ``existing`` is omitted; a member several Types may carry is always offered

        Args:
            existing (Iterable[str]): SpecialType values already claimed by existing CmdbTypes

        Returns:
            dict[str, str]: {member: display label} for every creatable member still available
        """
        existing_set: set[str] = set(existing)

        unused_types: dict[str, str] = {
            key: value
            for key, value in cls.get_special_types().items()
            if not (cls.is_singleton(key) and key in existing_set)
        }

        return unused_types
