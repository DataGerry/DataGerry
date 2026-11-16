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
Labels and messages of the ``/persons`` and ``/person_groups`` routes - a layer over the person and group objects
"""
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_LABEL: str = 'Person'
PERSON_GROUP_LABEL: str = 'PersonGroup'

# The label of each record kind, as the messages name it
RECORD_LABELS: dict[SpecialType, str] = {
    SpecialType.PERSON: PERSON_LABEL,
    SpecialType.PERSON_GROUP: PERSON_GROUP_LABEL,
}

# Refusal (HTTP 404) of an id naming no object of the record's kind. Formatted with the label and the id
RECORD_NOT_FOUND_MESSAGE: str = "The {label} with ID:{public_id} was not found!"

# Answer (HTTP 500) when the system has no default Type to create a record in. Formatted with the label
DEFAULT_TYPE_MISSING_MESSAGE: str = "The default {label} Type does not exist - restart the system to restore it!"

# Refusals (HTTP 403) of a person's membership change naming groups the writer may not read / update
MEMBERSHIP_NOT_READABLE_MESSAGE: str = "You may not read the PersonGroup ID(s) {ids}!"
MEMBERSHIP_NOT_UPDATABLE_MESSAGE: str = "You may not change the members of the PersonGroup ID(s) {ids}!"

# Refusals (HTTP 400) when the object write behind a record failed. Formatted with the label (and the id)
RECORD_CREATE_FAILED_MESSAGE: str = "Failed to insert the new {label} in the database!"
RECORD_READ_FAILED_MESSAGE: str = "Failed to retrieve the {label} data from the database!"
RECORD_UPDATE_FAILED_MESSAGE: str = "Failed to update the {label} with ID: {public_id}!"
RECORD_DELETE_FAILED_MESSAGE: str = "Failed to delete the {label} with ID:{public_id}!"
RECORD_ACCESS_DENIED_MESSAGE: str = "No permission to write the {label}!"
