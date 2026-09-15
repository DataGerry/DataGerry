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
Which Cable CIs a CmdbPortConnection may still claim, and how they are shown in the picker

One positive marker and one exclusion decide it:

  1. **the CmdbObject's type must carry the CABLE marker** - only a Cable CI can be a connection's
     ``cable_ci_id``, and that is a SpecialType question, not a naming one
  2. **a cable another connection already uses is out** - `cable_ci_id` carries a partial unique index
     filtered on its presence, so one cable belongs to at most one connection; offering a claimed one
     would produce a refusal the picker could have avoided

The connection being EDITED is the exception to rule 2: its own cable has to stay in the list, or an
edit form has nothing to preselect. The route resolves that id and drops it from the exclusion, so the
answer depends on which connection is being filled - the same shape as the Rack picker, where an object
held by a different rack is offered as a move.

Pure: the reads happen in the route and their results are passed in, so both the criteria and the row
projection are unit-testable without a database. The criteria are appended as '$match' stages onto the
caller's own ``?filter=`` (`routes_helper.append_criteria_to_filter`), which means a caller-supplied
filter narrows the candidates and can never widen them past the two rules
"""
import re
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model.port_connection_constants import AssignableCableKey
from cmdb.models.special_type_model.cable_constants import CableField

from cmdb.framework.port.connection_cable_view import coerce_cable_text
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The Cable CI field answering each cable key of a picker row. The CmdbType keys are absent: they
# describe the object, not its cable, and are resolved from the type lookup instead
CI_FIELD_BY_ROW_KEY: dict[AssignableCableKey, CableField] = {
    AssignableCableKey.NAME: CableField.NAME,
    AssignableCableKey.CABLE_TYPE: CableField.TYPE,
    AssignableCableKey.LENGTH: CableField.LENGTH,
    AssignableCableKey.COLOR: CableField.COLOR,
    AssignableCableKey.DESCRIPTION: CableField.DESCRIPTION,
}

# -------------------------------------------------------------------------------------------------------------------- #

def build_unassigned_cable_criteria(
        cable_type_ids: list[int],
        assigned_cable_ci_ids: list[int]) -> dict[str, Any]:
    """
    Builds the criteria that keep only the Cable CIs no connection has claimed

    The type marker is always applied, including when the list is empty: an installation whose types
    carry no CABLE marker has no cable to assign at all, so a '$in': [] matching nothing is the right
    answer rather than a rule to skip. The exclusion is omitted when it would exclude nothing, so a
    database without a single cabled connection does not get a '$nin' against an empty list

    Args:
        cable_type_ids (list[int]): public_ids of the CmdbTypes carrying the CABLE marker
        assigned_cable_ci_ids (list[int]): public_ids of the Cable CIs already used by a connection,
            minus the one belonging to the connection being edited

    Returns:
        dict[str, Any]: The Mongo criteria
    """
    criteria: dict[str, Any] = {CmdbObjectKey.TYPE_ID.value: {'$in': cable_type_ids}}

    if assigned_cable_ci_ids:
        criteria[CmdbObjectKey.PUBLIC_ID.value] = {'$nin': assigned_cable_ci_ids}

    return criteria


def build_cable_name_search_criteria(search: str | None) -> dict[str, Any]:
    """
    Builds the criteria of the picker's ``?search=`` - a substring match on the cable's name

    The name is a value inside the object's ``fields`` array, so the match is an '$elemMatch' on the
    element carrying `dg-cable-name` rather than a dotted path: a dotted path would match a document
    where ANY field is named that and ANY field holds the searched value, which is not the same
    question. The term is escaped to a literal, case-insensitive substring, exactly like the location
    tree search - a picker's search box is not a regex box. A blank or whitespace-only term adds no
    criteria at all rather than matching everything through an empty pattern

    Args:
        search (str | None): The raw ``?search=`` value

    Returns:
        dict[str, Any]: The Mongo criteria, empty when there is nothing to search for
    """
    if not search or not search.strip():
        return {}

    return {
        CmdbObjectKey.FIELDS.value: {
            '$elemMatch': {
                'name': CableField.NAME.value,
                'value': {'$regex': re.escape(search), '$options': 'i'},
            }
        }
    }


def build_unassigned_cable_row(
        object_doc: dict[str, Any],
        type_labels: dict[int, str]) -> dict[str, Any]:
    """
    Projects one Cable CI into the row the picker draws

    The five cable values are read out of the document's ``fields`` triples and reported as text, the
    same treatment the resolved `cable` block gives them - so an imported numeric cable name renders
    rather than breaking the page. A cable whose CmdbType no longer resolves keeps its row with a null
    `type_label`: it is still assignable, and hiding it would leave no way to notice the broken type

    Args:
        object_doc (dict[str, Any]): The candidate Cable CI document
        type_labels (dict[int, str]): {type_id: label} of the types present on this page

    Returns:
        dict[str, Any]: The picker row
    """
    type_id: Any = object_doc.get(CmdbObjectKey.TYPE_ID.value)

    row: dict[str, Any] = {
        AssignableCableKey.PUBLIC_ID.value: object_doc.get(CmdbObjectKey.PUBLIC_ID.value),
    }

    for row_key, ci_field in CI_FIELD_BY_ROW_KEY.items():
        row[row_key.value] = coerce_cable_text(extract_field_value(object_doc, ci_field.value))

    row[AssignableCableKey.TYPE_ID.value] = type_id
    row[AssignableCableKey.TYPE_LABEL.value] = type_labels.get(type_id) if isinstance(type_id, int) else None
    row[AssignableCableKey.ACTIVE.value] = object_doc.get(CmdbObjectKey.ACTIVE.value)

    return row


def build_unassigned_cable_rows(
        object_docs: list[dict[str, Any]],
        type_labels: dict[int, str]) -> list[dict[str, Any]]:
    """
    Projects a whole page of candidates, preserving the order the database returned

    The order is the caller's ``?sort=`` / ``?order=`` (the cable name by default), applied by the
    aggregation, so it is not re-sorted here

    Args:
        object_docs (list[dict[str, Any]]): The candidate Cable CI documents of one page
        type_labels (dict[int, str]): {type_id: label} of the types present on this page

    Returns:
        list[dict[str, Any]]: One row per document, in input order
    """
    return [build_unassigned_cable_row(object_doc, type_labels) for object_doc in object_docs]
