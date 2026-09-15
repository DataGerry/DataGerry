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
Constants of the RACK SpecialType (the Rack View feature)

Holds the field and section identifiers of the Rack CmdbType created from
cmdb.models.special_type_model.schemas.rack_schema. A field's 'name' is its immutable identifier,
so these values are a stored-data contract and must not be changed once a Rack type exists in any
installation
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class RackField(BaseStrEnum):
    """
    Field names of the RACK SpecialType

    NAME and HEIGHT are required; NUMBER and NOTES are optional. LOCATION carries the conventional
    'dg_location' name shared with the assistant profiles - the location machinery itself matches on
    the field's FieldType, never on this name (see extract_object_location_parent)
    """
    NAME = 'dg-rack-name'
    NUMBER = 'dg-rack-number'
    HEIGHT = 'dg-rack-height'
    NOTES = 'dg-rack-notes'
    LOCATION = 'dg_location'


class RackSection(BaseStrEnum):
    """
    Section names of the RACK SpecialType

    The Rack keeps all of its fields in a single section
    """
    INFORMATION = 'dg-rack-information'
