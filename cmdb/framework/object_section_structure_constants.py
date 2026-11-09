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
Constants of the shared object structure check (``object_section_structure``): the bounds of a row id and the
wording of each reason a write is refused for
"""
# -------------------------------------------------------------------------------------------------------------------- #

# A row id (``multi_data_id``) and a section's ``highest_id`` are whole numbers from this one up
MIN_ROW_ID: int = 0

# How many reasons the 400 names; the rest are counted ("... and 4 more")
MAX_LISTED_REASONS: int = 20

OBJECT_STRUCTURE_INVALID_MSG: str = "The object's structure is invalid - {reasons}!"
REASON_SEPARATOR: str = "; "
MORE_REASONS_PART: str = "{listed} and {more} more"

# The reasons. A section is named by its section_id once it has one, by its position before; a row by its position
FIELDS_REPEATED: str = "fields names field(s) more than once: {names}"
SECTIONS_NOT_A_LIST: str = "multi_data_sections is not a list"
SECTION_NOT_AN_OBJECT: str = "multi-data section {position} is not an object"
SECTION_WITHOUT_ID: str = "multi-data section {position} has no section_id"
SECTION_UNDECLARED: str = "multi-data section '{section_id}' is not a multi-data section of the type"
SECTION_REPEATED: str = "multi-data section '{section_id}' is sent more than once"
HIGHEST_ID_INVALID: str = "multi-data section '{section_id}': highest_id is no whole number from {minimum}"
VALUES_NOT_A_LIST: str = "multi-data section '{section_id}': values is not a list"
ROW_NOT_AN_OBJECT: str = "multi-data section '{section_id}': the row at position {position} is not an object"
ROW_ID_INVALID: str = (
    "multi-data section '{section_id}': the row at position {position} has no multi_data_id (a whole number from "
    "{minimum})"
)
ROW_IDS_REPEATED: str = "multi-data section '{section_id}': multi_data_id(s) used by more than one row: {row_ids}"
ROW_DATA_NOT_A_LIST: str = "multi-data section '{section_id}': the data of the row at position {position} is not a list"
ENTRY_INVALID: str = (
    "multi-data section '{section_id}': the row at position {position} holds an entry that is not an object with a "
    "string name"
)
ROW_FIELDS_UNDECLARED: str = (
    "multi-data section '{section_id}': the row at position {position} carries field(s) the section does not "
    "declare: {names}"
)
ROW_FIELDS_REPEATED: str = (
    "multi-data section '{section_id}': the row at position {position} names field(s) more than once: {names}"
)
