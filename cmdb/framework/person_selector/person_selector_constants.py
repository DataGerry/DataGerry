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
Constants of the person selector on CmdbObjects: refusal wording, the keys of a rendered selection and of the picker
answer, which base field labels a person or a group, and the picker's page bounds
"""
from cmdb.utils import BaseStrEnum
from cmdb.framework.exporter.exporter_constants import LIST_CELL_SEPARATOR
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonSelectorWriteError',
    'PersonSelectionKey',
    'PersonPickerParam',
    'PersonPickerKey',
    'LABEL_FIELD_BY_KIND',
    'DEFAULT_PICKER_LIMIT',
    'MAX_PICKER_LIMIT',
    'SELECTOR_DELETE_OBJECT_ID_LIMIT',
    'PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE',
    'PersonPickerError',
    'SELECTOR_CELL_SEPARATOR',
    'SELECTOR_LABEL_SEPARATOR',
    'PERSON_SELECTOR_CELL_ERROR',
]

# How a text export (CSV / XLSX / XML) spells the ids of a selector holding several, and the import reads them back -
# the exporter's list spelling, so the two cannot drift
SELECTOR_CELL_SEPARATOR: str = LIST_CELL_SEPARATOR

# How a human-readable export joins the labels of a selector holding several
SELECTOR_LABEL_SEPARATOR: str = ', '

# Why an imported selector value is refused. Formatted with the value
PERSON_SELECTOR_CELL_ERROR: str = "'{value}' is no object id, nor ids separated by commas"



class PersonSelectorWriteError(BaseStrEnum):
    """Why an object write's person selector value is refused - 400, except NOT_READABLE (403)"""
    SHAPE_SINGLE = "The person selector '{name}' holds one object id or nothing"
    SHAPE_MULTIPLE = "The person selector '{name}' holds a list of object ids, each at most once"
    UNKNOWN = "The person selector '{name}' names objects that do not exist: {ids}"
    NOT_READABLE = "You may not read the objects the person selector '{name}' names: {ids}"
    NOT_SELECTABLE = "The person selector '{name}' may only select {kinds}, which these objects are not: {ids}"


class PersonSelectionKey(BaseStrEnum):
    """Keys of one rendered selection (``RenderedFieldKey.PERSONS``) and of one picker result"""
    OBJECT_ID = 'object_id'
    TYPE_ID = 'type_id'
    TYPE_LABEL = 'type_label'
    KIND = 'kind'
    LABEL = 'label'


class PersonPickerParam(BaseStrEnum):
    """Query parameters of the person picker route"""
    KINDS = 'kinds'
    SEARCH = 'search'
    IDS = 'ids'
    PAGE = 'page'
    LIMIT = 'limit'


class PersonPickerKey(BaseStrEnum):
    """Keys of the person picker's answer"""
    RESULTS = 'results'
    TOTAL = 'total'
    PAGE = 'page'
    LIMIT = 'limit'


# The base field whose value labels a selected object, per kind - kept by every Type with the marker
LABEL_FIELD_BY_KIND: dict[SpecialType, str] = {
    SpecialType.PERSON: PersonField.DISPLAY_NAME.value,
    SpecialType.PERSON_GROUP: PersonGroupField.NAME.value,
}

# The picker's page size when none is asked for, and the most it answers in one page
DEFAULT_PICKER_LIMIT: int = 25
MAX_PICKER_LIMIT: int = 100

# How many objects a refused delete names at most
SELECTOR_DELETE_OBJECT_ID_LIMIT: int = 20

# Refusal (HTTP 400) of a delete that would leave a required person selector empty. Formatted with the objects the
# caller may read and how many it may not
PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE: str = (
    "Delete not possible: a required person selection of these Objects holds nothing else: {object_ids}"
    " ({hidden} more you may not read)"
)


class PersonPickerError(BaseStrEnum):
    """Why the person picker refuses its parameters (HTTP 400)"""
    KINDS = "'kinds' lists PERSON and / or PERSON_GROUP, separated by commas"
    IDS = "'ids' lists object ids, separated by commas"
    PAGE = "'page' is a whole number from 1"
    LIMIT = "'limit' is a whole number from 1 to {maximum}"
