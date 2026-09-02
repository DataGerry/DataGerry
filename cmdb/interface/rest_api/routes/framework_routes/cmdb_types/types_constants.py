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
Response-shape constants for the CmdbType REST routes

Names the dict keys of the ``/rest/types/overview`` response items and their nested user-data block,
so the route helpers build that response from one set of named keys instead of repeating the literals,
plus the refusal messages and the response keys of the reference-section usage pre-check.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Message returned when a CmdbType lookup by public_id finds nothing (HTTP 404). Shared by every
# "look it up or 404" helper so a missing type reads the same wherever it is reported
TYPE_NOT_FOUND_MESSAGE: str = 'The Type with ID:{public_id} was not found!'

# Refusal returned (HTTP 400) when an update would delete a section that another CmdbType's
# reference section pulls its fields from. Deleting it would leave that reference dangling: the
# dependent type keeps a reference to a section name that no longer resolves, its Section dropdown
# comes up empty and the referenced block disappears from every object view of that type
REFERENCED_SECTION_REMOVAL_MESSAGE: str = (
    'Cannot remove section(s) that other Types reference: {details}. '
    'Remove the reference section(s) from those Types first.'
)

# One '<section> <- referenced by <types>' entry of the message above
REFERENCED_SECTION_DEPENDENT_FORMAT: str = "'{section_name}' is referenced by {dependents}"

# How a single dependent CmdbType is named inside that entry
REFERENCED_SECTION_DEPENDENT_TYPE_FORMAT: str = "'{label}' (ID:{public_id})"

# Refusal returned (HTTP 400) when an update would leave a referenced section with nothing to show:
# every field a dependent's reference section pulls has left that section. The dependent keeps a valid
# reference, but its block renders empty - the same blank area as a deleted section, from the field
# side. A reduction that still leaves the dependent at least one field is allowed: losing the column
# of a field that was deleted is the direct consequence of deleting it
REFERENCED_SECTION_EMPTIED_MESSAGE: str = (
    'Cannot leave section(s) that other Types reference with nothing to show: {details}. '
    'Keep at least one of the referenced fields in the section, or remove the reference section(s) '
    'from those Types first.'
)

# One '<section> would show nothing in <types>' entry of the message above
REFERENCED_SECTION_EMPTIED_DETAIL_FORMAT: str = "'{section_name}' would show nothing in {dependents}"


# Refusal returned (HTTP 400) when a CmdbType may not be deleted because another CmdbType's
# reference section points at it. Same dangling reference as above, one level up
REFERENCED_TYPE_DELETE_MESSAGE: str = (
    'Delete not possible if other Types reference this Type in a reference section: {dependents}!'
)


# Refusal (HTTP 400) when an update would turn 'uses_ports' off while ports of that Type exist. The
# ports live in framework.ports keyed on their owner CmdbObject, so a Type whose flag is off renders no
# ports panel and its objects' ports become rows nothing in the UI can reach
USES_PORTS_DISABLE_MESSAGE: str = (
    "Cannot disable 'uses ports': {port_count} Port(s) still exist on {object_count} Object(s) of "
    'this Type. Delete those Ports first.'
)


class UsesPortsUsageKey(BaseStrEnum):
    """
    Response keys of the ``/types/uses_ports_usage/<public_id>`` pre-check

    Counts only, never an id list: the equivalent location payload returns every matching public_id
    and is unbounded for a large Type (discussion backlog #187). The type builder needs to know
    WHETHER it may clear the flag, not which ports stand in the way
    """
    IN_USE = 'in_use'
    PORT_COUNT = 'port_count'
    OBJECT_COUNT = 'object_count'


class ReferencedSectionUsageKey(BaseStrEnum):
    """
    Response keys of the ``/types/referenced_section_usage/<public_id>`` pre-check

    IN_USE and REFERENCING_TYPE_IDS answer "may this Type be deleted"; SECTIONS answers it per
    section, so the type builder can disable the delete action on exactly the sections another Type
    depends on
    """
    IN_USE = 'in_use'
    COUNT = 'count'
    REFERENCING_TYPE_IDS = 'referencing_type_ids'
    SECTIONS = 'sections'


class TypeOverviewKey(BaseStrEnum):
    """
    Keys of a single item in the ``/rest/types/overview`` response

    TYPE_DATA holds the CmdbType document and USER_DATA the resolved author/editor block (see
    TypeUserDataKey).
    """
    TYPE_DATA = 'type_data'
    USER_DATA = 'user_data'


class TypeUserDataKey(BaseStrEnum):
    """
    Keys of the resolved author / editor block returned alongside a CmdbType

    Each holds the display name or profile image of the type's author / last editor, or None when
    the referenced CmdbUser could not be resolved.
    """
    AUTHOR = 'author'
    AUTHOR_IMAGE = 'author_image'
    LAST_EDITOR = 'last_editor'
    LAST_EDITOR_IMAGE = 'last_editor_image'
