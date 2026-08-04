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
Definition of required sections and fields for the SpecialType RACK
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
# -------------------------------------------------------------------------------------------------------------------- #

def get_rack_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the RACK SpecialType

    Unlike the IPAM SpecialTypes the Rack needs no post-insert cross-wiring: it holds no reference
    fields, so handle_special_types has nothing to do for it. The location field is what makes
    "assign a Rack to a Location" work with no new machinery, and it is also the parent the mounted
    objects' location nodes hang from - which is why a Rack CmdbType must stay selectable as a
    parent (enforced by enforce_rack_selectable_as_parent on the type write)

    Returns:
        dict[str, Any]: Blueprint with the RACK section, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.RACK,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: RackSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    RackField.NAME,
                    RackField.NUMBER,
                    RackField.HEIGHT,
                    RackField.NOTES,
                    RackField.LOCATION,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: RackField.NAME,
                FieldKey.LABEL: 'Rackname',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: RackField.NUMBER,
                FieldKey.LABEL: 'Racknumber',
            },
            {
                # The U count of the Rack. 'required' is honoured by the frontend form only, so the
                # positive-integer check lives in the Rack enforcement on the object write path
                FieldKey.TYPE: FieldType.NUMBER,
                FieldKey.NAME: RackField.HEIGHT,
                FieldKey.LABEL: 'Height',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: FieldType.TEXTAREA,
                FieldKey.NAME: RackField.NOTES,
                FieldKey.LABEL: 'Notes',
            },
            {
                FieldKey.TYPE: FieldType.LOCATION,
                FieldKey.NAME: RackField.LOCATION,
                FieldKey.LABEL: 'Location',
            },
        ],
    }
