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
The seed of the DocAPI reference fan-out tests: a tree of references three hops deep, and a cycle

* one type, FAN_TYPE_ID, with a name and REFERENCE_COUNT reference fields pointing at its own type
* a tree: ROOT_ID references REFERENCE_COUNT objects, each of them as many more, down to the leaves at
  DEFAULT_REFERENCE_DEPTH hops - 1 + 3 + 9 + 27 objects; a leaf references nothing
* a cycle: CYCLE_A_ID references CYCLE_B_ID, which references CYCLE_A_ID back
* an OBJECT (legacy) template reading the name at the end of the deepest path

Resolved one reference at a time, the tree costs 3 + 9 + 27 renders; one level at a time, three. Everything is
written straight into the collections
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.docapi_model.docapi_reference_constants import DEFAULT_REFERENCE_DEPTH
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

FAN_TYPE_ID: int = 89701
ROOT_ID: int = 89710
CYCLE_A_ID: int = 89800
CYCLE_B_ID: int = 89801
TEMPLATE_ID: int = 89721

REFERENCE_COUNT: int = 3
NAME_FIELD: str = 'dg_name'
REFERENCE_FIELDS: list[str] = [f'fan-{index}' for index in range(1, REFERENCE_COUNT + 1)]
LAST_REFERENCE: str = REFERENCE_FIELDS[-1]

#: The deepest path: the last reference of every object, DEFAULT_REFERENCE_DEPTH hops down
TEMPLATE_BODY: str = (
    "<p>DEEP[{{ fields"
    + "".join(f"['{LAST_REFERENCE}'].fields" for _ in range(DEFAULT_REFERENCE_DEPTH))
    + f".{NAME_FIELD} }}}}]</p>"
)


def name_of(public_id: int) -> str:
    """The name the seed gives an object"""
    return f'docfan-{public_id}'


def tree_levels() -> list[list[int]]:
    """The tree's ids, level by level: the root, then each hop"""
    levels: list[list[int]] = [[ROOT_ID]]
    next_id: int = ROOT_ID + 1

    for _ in range(DEFAULT_REFERENCE_DEPTH):
        size: int = len(levels[-1]) * REFERENCE_COUNT
        levels.append(list(range(next_id, next_id + size)))
        next_id += size

    return levels


def deepest_id() -> int:
    """The object at the end of the template's path - the last leaf"""
    return tree_levels()[-1][-1]


def _object_doc(public_id: int, referenced: list[int]) -> dict[str, Any]:
    """A complete CmdbObject of the fan type, referencing `referenced` in order"""
    references: list[dict[str, Any]] = [
        {'type': FieldType.REFERENCE.value, 'name': name, 'value': target}
        for name, target in zip(REFERENCE_FIELDS, referenced)
    ]

    return {
        'public_id': public_id, 'type_id': FAN_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': name_of(public_id)}, *references],
    }


def _object_docs() -> list[dict[str, Any]]:
    """The tree and the cycle"""
    levels: list[list[int]] = tree_levels()
    docs: list[dict[str, Any]] = []

    for depth, level in enumerate(levels):
        children: list[int] = levels[depth + 1] if depth + 1 < len(levels) else []

        for index, public_id in enumerate(level):
            docs.append(_object_doc(public_id, children[index * REFERENCE_COUNT:(index + 1) * REFERENCE_COUNT]))

    docs.append(_object_doc(CYCLE_A_ID, [CYCLE_B_ID]))
    docs.append(_object_doc(CYCLE_B_ID, [CYCLE_A_ID]))

    return docs


def all_object_ids() -> list[int]:
    """Every object the seed writes"""
    return [public_id for level in tree_levels() for public_id in level] + [CYCLE_A_ID, CYCLE_B_ID]


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes the type, the objects and the template"""
    purge(database_manager, database_name)
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}] + [
        {'type': FieldType.REFERENCE.value, 'name': name, 'label': name, 'ref_types': [FAN_TYPE_ID]}
        for name in REFERENCE_FIELDS
    ]
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(
        make_type_doc(FAN_TYPE_ID, 'docfan', fields=fields))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many(_object_docs())
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).insert_one({
        'public_id': TEMPLATE_ID, 'name': 'docfan', 'label': 'Doc fan-out', 'active': True, 'author_id': 1,
        'template_type': DocapiTemplateType.OBJECT.value, 'template_data': TEMPLATE_BODY, 'template_style': '',
    })


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote"""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many({'public_id': FAN_TYPE_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': all_object_ids()}})
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).delete_many({'public_id': TEMPLATE_ID})
