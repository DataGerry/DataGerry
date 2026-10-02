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
Messages shared by the CmdbPerson and CmdbPersonGroup routes

A write of either side touches the other side's membership (and, on a delete, the ISMS references), so each
write route runs under a WriteLedger: the residue message answers the 500 when the undo of a failed write could not
finish, and names what is still in effect
"""
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_LABEL: str = 'Person'
PERSON_GROUP_LABEL: str = 'PersonGroup'

# The 500 of a failed write whose undo could not finish, formatted with the entity label and the residue
WRITE_RESIDUE_MESSAGE: str = (
    "The {label} write failed and could not be fully undone - still in effect: {{residue}}"
)

# The 500 of a create whose new document cannot be read back, formatted with the entity label
CREATED_NOT_READABLE_MESSAGE: str = "Could not retrieve the created {label} from the database!"

PERSON_WRITE_RESIDUE: str = WRITE_RESIDUE_MESSAGE.format(label=PERSON_LABEL)
PERSON_GROUP_WRITE_RESIDUE: str = WRITE_RESIDUE_MESSAGE.format(label=PERSON_GROUP_LABEL)
PERSON_CREATED_NOT_READABLE: str = CREATED_NOT_READABLE_MESSAGE.format(label=PERSON_LABEL)
PERSON_GROUP_CREATED_NOT_READABLE: str = CREATED_NOT_READABLE_MESSAGE.format(label=PERSON_GROUP_LABEL)
