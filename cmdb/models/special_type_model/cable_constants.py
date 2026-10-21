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
Constants of the CABLE SpecialType (the Cable CI of the Port Connectivity feature)

Holds the field and section identifiers of the Cable CmdbType created from
cmdb.models.special_type_model.schemas.cable_schema. A field's 'name' is its immutable identifier, so
these values are a stored-data contract and must not be changed once a Cable type exists in any
installation.

The Cable CI is OPTIONAL: a connection carries its cable information on its own document and works
with no CI at all (Scenario A of the concept). The CI exists for customers who inventory cables as
assets, and a connection then points at one through its ``cable_ci_id`` - one way only, nothing points
back
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class CableField(BaseStrEnum):
    """
    Field names of the CABLE SpecialType

    Deliberately the same vocabulary a connection's own cable info offers, so Scenario A (cable info
    only) and Scenario B (info plus an inventoried CI) ask the user for the same five things. NAME is
    the only required one - a CI created from an inventory import often knows nothing else.

    LENGTH is TEXT and not a number on purpose: the concept keeps customer notations like '5 m' or
    '2.5 m' verbatim rather than splitting a value from a unit
    """
    NAME = 'dg-cable-name'
    TYPE = 'dg-cable-type'
    LENGTH = 'dg-cable-length'
    COLOR = 'dg-cable-color'
    DESCRIPTION = 'dg-cable-description'


class CableSection(BaseStrEnum):
    """
    Section names of the CABLE SpecialType

    The Cable keeps all of its fields in a single section, like the Rack
    """
    INFORMATION = 'dg-cable-information'
