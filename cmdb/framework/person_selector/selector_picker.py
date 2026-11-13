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
The person picker: the persons and person groups a person selector may offer the caller

The objects of every type carrying one of the asked markers, of the types the caller may READ - so the frontend never
works the types out itself. Two uses: browsing (active objects only, a case-insensitive ``search`` on the label - a
person's ``display_name``, a group's ``name``, the text taken literally), and resolving given ``ids`` to their labels
(also an inactive object a selector still holds). Paged in ``public_id`` order; one projected read of the types, one
count and one page of objects
"""
import re
from typing import Any, NamedTuple

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.person_selector.person_selector_constants import LABEL_FIELD_BY_KIND
from cmdb.framework.person_selector.selector_render import selection_entry
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['PickerQuery', 'find_person_choices']

MONGO_ID: str = '_id'
CASE_INSENSITIVE: str = 'i'


class PickerQuery(NamedTuple):
    """What the picker is asked: which kinds, a label search or ids to resolve, and the page"""
    kinds: list[SpecialType]
    search: str | None
    ids: list[int] | None
    page: int
    limit: int


def _label_matches(type_ids_by_kind: dict[SpecialType, list[int]], search: str) -> dict[str, Any]:
    """The condition matching an object whose label holds the search text - each kind by its own label field"""
    return {'$or': [
        {CmdbObjectKey.TYPE_ID.value: {'$in': type_ids},
         CmdbObjectKey.FIELDS.value: {'$elemMatch': {
             CmdbObjectFieldKey.NAME.value: LABEL_FIELD_BY_KIND[kind],
             CmdbObjectFieldKey.VALUE.value: {'$regex': re.escape(search), '$options': CASE_INSENSITIVE},
         }}}
        for kind, type_ids in type_ids_by_kind.items()
    ]}


def find_person_choices(objects_manager: ObjectsManager,
                        types_manager: TypesManager,
                        hidden_types: HiddenTypeIds,
                        query: PickerQuery) -> tuple[list[dict[str, Any]], int]:
    """
    One page of the persons and groups the caller may select

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The caller's denied Types
        query (PickerQuery): The kinds, the search or the ids, and the page

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        tuple[list[dict[str, Any]], int]: The page's selections (``PersonSelectionKey``) and how many there are
    """
    types: dict[int, dict[str, Any]] = {
        document[TypeSchemaKey.PUBLIC_ID.value]: document
        for document in types_manager.find(
            {TypeSchemaKey.SPECIAL_TYPE.value: {'$in': [kind.value for kind in query.kinds]}},
            projection={MONGO_ID: 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.LABEL.value: 1,
                        TypeSchemaKey.SPECIAL_TYPE.value: 1},
        )
        if document[TypeSchemaKey.PUBLIC_ID.value] not in hidden_types()
    }

    if not types:
        return [], 0

    type_ids_by_kind: dict[SpecialType, list[int]] = {}

    for type_id, document in sorted(types.items()):
        type_ids_by_kind.setdefault(SpecialType(document[TypeSchemaKey.SPECIAL_TYPE.value]), []).append(type_id)

    criteria: dict[str, Any] = {CmdbObjectKey.TYPE_ID.value: {'$in': sorted(types)}}

    if query.ids is not None:
        criteria[CmdbObjectKey.PUBLIC_ID.value] = {'$in': sorted(set(query.ids))}
    else:
        criteria[CmdbObjectKey.ACTIVE.value] = True

        if query.search:
            criteria.update(_label_matches(type_ids_by_kind, query.search))

    total: int = objects_manager.count_documents(criteria)
    documents: list[dict[str, Any]] = objects_manager.find(
        criteria,
        projection={MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1,
                    CmdbObjectKey.FIELDS.value: 1},
        sort=[(CmdbObjectKey.PUBLIC_ID.value, 1)],
        skip=(query.page - 1) * query.limit,
        limit=query.limit,
    )

    return [selection_entry(document, types[document[CmdbObjectKey.TYPE_ID.value]]) for document in documents], total
