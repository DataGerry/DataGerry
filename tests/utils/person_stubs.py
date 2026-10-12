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
In-memory stand-ins for the ObjectsManager / TypesManager calls the Persons feature makes

Pure unit tests of cmdb.framework.person and its callers need a manager pair that answers
``get_type_ids_of_special_type``, ``get_type`` and the projected ``find`` of ``resolve_person_kinds`` from a
handful of documents. The ``find`` here understands equality and ``$in`` on top-level keys only - enough
for the id lookups - and refuses anything else, so a test cannot silently pass over a query it does not
evaluate
"""
from typing import Any

from cmdb.models.special_type_model.person_constants import (
    PersonField,
    PersonGroupField,
    PersonValueKey,
)
from cmdb.models.special_type_model.schemas.person_schema import get_person_group_schema, get_person_schema
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 501
PERSON_GROUP_TYPE_ID: int = 502


def plain(value: Any) -> Any:
    """Recursively turns the enum members of a schema blueprint into their plain string values"""
    if isinstance(value, dict):
        return {plain(key): plain(item) for key, item in value.items()}

    if isinstance(value, list):
        return [plain(item) for item in value]

    return getattr(value, 'value', value)


def person_type_doc(type_id: int = PERSON_TYPE_ID) -> dict[str, Any]:
    """A CmdbType document carrying the PERSON blueprint (only the keys the person code reads)"""
    schema: dict[str, Any] = plain(get_person_schema())

    return {'public_id': type_id, 'name': 'dg_person', 'label': 'Person', **schema}


def person_group_type_doc(type_id: int = PERSON_GROUP_TYPE_ID) -> dict[str, Any]:
    """A CmdbType document carrying the PERSON_GROUP blueprint (only the keys the person code reads)"""
    schema: dict[str, Any] = plain(get_person_group_schema())

    return {'public_id': type_id, 'name': 'dg_person_group', 'label': 'Person Group', **schema}


def person_field(name: str, label: str | None = None, ref_kind: str | None = None,
                 multiple: bool | None = None) -> dict[str, Any]:
    """A person field definition of a CmdbType"""
    field: dict[str, Any] = {'type': 'person', 'name': name, 'label': label or name}

    if ref_kind is not None:
        field['person_ref_kind'] = ref_kind

    if multiple is not None:
        field['multiple'] = multiple

    return field


def selection(ref_type: str, object_id: Any) -> dict[str, Any]:
    """One stored {'ref_type', 'id'} pair"""
    return {PersonValueKey.REF_TYPE.value: ref_type, PersonValueKey.ID.value: object_id}


def person_object(public_id: int, display_name: str, type_id: int = PERSON_TYPE_ID, **values: Any) -> dict[str, Any]:
    """A PERSON object document"""
    fields: list[dict[str, Any]] = [{'name': PersonField.DISPLAY_NAME.value, 'value': display_name}]
    fields.extend({'name': name, 'value': value} for name, value in values.items())

    return {'public_id': public_id, 'type_id': type_id, 'fields': fields}


def group_object(public_id: int, name: str, member_ids: list[int] | None = None,
                 type_id: int = PERSON_GROUP_TYPE_ID, email: str = '') -> dict[str, Any]:
    """A PERSON_GROUP object document listing the given members"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'fields': [
            {'name': PersonGroupField.NAME.value, 'value': name},
            {'name': PersonGroupField.EMAIL.value, 'value': email},
            {
                'name': PersonGroupField.MEMBERS.value,
                'type': 'person',
                'value': [selection(SpecialType.PERSON.value, member_id) for member_id in member_ids or []],
            },
        ],
    }


def _matches(document: dict[str, Any], criteria: dict[str, Any]) -> bool:
    for key, condition in criteria.items():
        if isinstance(condition, dict):
            if set(condition) != {'$in'}:
                raise NotImplementedError(f"StubObjectsManager cannot evaluate {condition!r}")

            if document.get(key) not in condition['$in']:
                return False
        elif key.startswith('$'):
            raise NotImplementedError(f"StubObjectsManager cannot evaluate {key!r}")
        elif document.get(key) != condition:
            return False

    return True


class StubTypesManager:
    """Answers the TypesManager calls of the Persons feature from a list of type documents"""

    def __init__(self, type_docs: list[dict[str, Any]] | None = None) -> None:
        self.type_docs: dict[int, dict[str, Any]] = {doc['public_id']: doc for doc in type_docs or []}
        self.special_type_calls: list[Any] = []

    def get_type_ids_of_special_type(self, special_type: Any) -> list[int]:
        self.special_type_calls.append(special_type)
        value: str = getattr(special_type, 'value', special_type)

        return [type_id for type_id, doc in self.type_docs.items() if doc.get('special_type') == value]

    def get_type(self, public_id: int) -> dict[str, Any] | None:
        return self.type_docs.get(public_id)


class StubObjectsManager:
    """Answers ``find`` from a list of object documents (top-level equality and '$in' only)"""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents: list[dict[str, Any]] = list(documents or [])
        self.find_calls: list[dict[str, Any]] = []

    def find(self, criteria: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        self.find_calls.append(criteria or {})
        projection: dict[str, int] | None = kwargs.get('projection')
        found: list[dict[str, Any]] = [doc for doc in self.documents if _matches(doc, criteria or {})]

        if projection:
            kept: list[str] = [key for key, flag in projection.items() if flag and key != '_id']
            found = [{key: doc[key] for key in kept if key in doc} for doc in found]

        return found


def person_managers(*documents: dict[str, Any]) -> tuple[StubObjectsManager, StubTypesManager]:
    """A manager pair knowing the PERSON and PERSON_GROUP types and the given objects"""
    return (
        StubObjectsManager(list(documents)),
        StubTypesManager([person_type_doc(), person_group_type_doc()]),
    )
