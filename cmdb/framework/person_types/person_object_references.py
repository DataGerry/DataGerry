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
References to persons and person groups, which are objects of a Type carrying PERSON or PERSON_GROUP

An ISMS document names a person or a group by its object id and says which with the marker (its ``*_ref_type``). An
object counts as a person when its stored ``special_type`` is PERSON - an object carries its Type's marker, so no Type
is read to tell. What a caller may see of one is decided by the READ ACL of its Type:

  - ``resolve_marked_objects``: which of the named ids are objects of the marker, and which of those the caller may not
    read - the write check of an ISMS document
  - ``marked_object_names``: the display name (``LABEL_FIELD_BY_KIND``) of each named object the reader may read - the
    risk-assessment naming
  - ``marked_object_lookup``: the same as a ``$lookup`` stage, the name projected under the label field's own key - the
    ISMS reports
"""
from typing import Any, Iterable, NamedTuple

from cmdb.utils import Builder
from cmdb.manager import ObjectsManager
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.person_selector.person_selector_constants import LABEL_FIELD_BY_KIND
from cmdb.framework.person_types.person_records import field_value_expression
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MarkedObjects',
    'marked_object_lookup',
    'marked_object_names',
    'resolve_marked_objects',
]

MONGO_ID: str = '_id'


class MarkedObjects(NamedTuple):
    """
    What a set of ids of one marker resolves to

    Attributes:
        unknown (list[int]): The ids naming no object of the marker, sorted
        unreadable (list[int]): The ids naming one the caller may not read, sorted
    """
    unknown: list[int]
    unreadable: list[int]


def _marked_documents(objects_manager: ObjectsManager, marker: SpecialType, ids: Iterable[int],
                      projection: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The objects of the marker among the ids - one projected ``$in`` read on the public_id index

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        marker (SpecialType): PERSON or PERSON_GROUP
        ids (Iterable[int]): The ids
        projection (dict[str, Any]): What to read of each

    Raises:
        BaseManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The objects found
    """
    return objects_manager.find(
        {CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(set(ids))}, CmdbObjectKey.SPECIAL_TYPE.value: marker.value},
        projection={MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1, **projection},
    )


def resolve_marked_objects(objects_manager: ObjectsManager, marker: SpecialType, ids: Iterable[int],
                           hidden_types: HiddenTypeIds) -> MarkedObjects:
    """
    Which ids name no object of the marker, and which name one the caller may not read

    Nothing is read for no ids; the hidden Types are asked only when an object was found

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        marker (SpecialType): PERSON or PERSON_GROUP
        ids (Iterable[int]): The ids
        hidden_types (HiddenTypeIds): The caller's denied Types

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        MarkedObjects: The unknown and the unreadable ids
    """
    wanted: set[int] = set(ids)

    if not wanted:
        return MarkedObjects([], [])

    found: dict[int, int] = {
        document[CmdbObjectKey.PUBLIC_ID.value]: document.get(CmdbObjectKey.TYPE_ID.value)
        for document in _marked_documents(objects_manager, marker, wanted, {})
    }

    return MarkedObjects(
        unknown=sorted(wanted - found.keys()),
        unreadable=sorted(object_id for object_id, type_id in found.items() if type_id in hidden_types()),
    )


def label_of(document: dict[str, Any], marker: SpecialType) -> Any:
    """
    The display name of a person or group object - the value of its marker's label field

    Args:
        document (dict[str, Any]): The object, at least its fields
        marker (SpecialType): PERSON or PERSON_GROUP

    Returns:
        Any: The value, None without the field
    """
    label_field: str = LABEL_FIELD_BY_KIND[marker]

    return next((entry.get(CmdbObjectFieldKey.VALUE.value)
                 for entry in document.get(CmdbObjectKey.FIELDS.value) or []
                 if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) == label_field), None)


def marked_object_names(objects_manager: ObjectsManager, marker: SpecialType, ids: Iterable[int],
                        denied_type_ids: Iterable[int]) -> dict[int, Any]:
    """
    The display name of each named object of the marker the reader may read

    An object of a denied Type is left out - the reader sees no name for it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        marker (SpecialType): PERSON or PERSON_GROUP
        ids (Iterable[int]): The ids
        denied_type_ids (Iterable[int]): The Types the reader may not READ

    Raises:
        BaseManagerGetError: When the read fails

    Returns:
        dict[int, Any]: Name by id
    """
    wanted: set[int] = set(ids)

    if not wanted:
        return {}

    denied: set[int] = set(denied_type_ids)

    return {
        document[CmdbObjectKey.PUBLIC_ID.value]: label_of(document, marker)
        for document in _marked_documents(objects_manager, marker, wanted, {CmdbObjectKey.FIELDS.value: 1})
        if document.get(CmdbObjectKey.TYPE_ID.value) not in denied
    }


def marked_object_lookup(local_field: str, alias: str, marker: SpecialType,
                         denied_type_ids: Iterable[int]) -> dict[str, Any]:
    """
    A ``$lookup`` joining the objects of the marker a field names, each as ``{public_id, <label field>: name}``

    The join is the index-backed equality on ``public_id`` (a list field joins every entry); the sub-pipeline keeps the
    objects of the marker whose Type the reader may READ and projects the name under the label field's own key
    (``display_name`` / ``name``), so the stages reading the joined document read it as they read a person record

    Args:
        local_field (str): The field naming the ids
        alias (str): Where the joined objects go
        marker (SpecialType): PERSON or PERSON_GROUP
        denied_type_ids (Iterable[int]): The Types the reader may not READ

    Returns:
        dict[str, Any]: The stage
    """
    label_field: str = LABEL_FIELD_BY_KIND[marker]

    return Builder.lookup_(
        CmdbObject.COLLECTION, local_field, CmdbObjectKey.PUBLIC_ID.value, alias,
        pipeline=[
            Builder.match_({
                CmdbObjectKey.SPECIAL_TYPE.value: marker.value,
                CmdbObjectKey.TYPE_ID.value: {'$nin': sorted(set(denied_type_ids))},
            }),
            Builder.project_({
                MONGO_ID: 0,
                CmdbObjectKey.PUBLIC_ID.value: 1,
                label_field: field_value_expression(label_field),
            }),
        ],
    )
