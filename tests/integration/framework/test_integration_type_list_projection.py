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
Integration tests: the type list reads a keep-only projection from MongoDB, against a real collection

For each projection the frontend sends to ``GET /types/``, the page read with ``build_type_list_projection``:

  - returns from MongoDB only the top-level keys the projection reaches, the keys ``CmdbType.from_data`` needs, and no
    ``_id`` - the fields, the ACL and the rest of a type stay in the database
  - still builds every type, and once serialised and projected it is the SAME answer as a whole read projected in
    memory - the shape a client gets does not change
  - a projection that drops a key reads whole documents
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import build_type_list_projection
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_TYPE_ID: int = 93701
TYPE_COUNT: int = 3
TYPE_IDS: list[int] = list(range(FIRST_TYPE_ID, FIRST_TYPE_ID + TYPE_COUNT))
SEEDED: dict[str, Any] = {'public_id': {'$in': TYPE_IDS}}
MONGO_ID: str = '_id'
# The projections the frontend sends to GET /types/ (type builder, object groups / risk duplicate, graph profile,
# port type catalog) and a nested one
FRONTEND_PROJECTIONS: dict[str, Any] = {
    'type-builder': {'public_id': 1, 'name': 1, 'label': 1, 'render_meta': 1},
    'object-groups': ['public_id', 'label', 'name'],
    'graph-profile': {'public_id': 1, 'label': 1, 'name': 1},
    'port-type-catalog': {'public_id': 1},
    'nested': {'public_id': 1, 'render_meta.icon': 1, 'render_meta.sections.name': 1},
}


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[TypesManager]:
    """Three seeded types with fields and sections; removed again after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many(SEEDED)
    types.insert_many([
        make_type_doc(public_id, f'projection-type-{public_id}',
                      fields=[{'type': 'text', 'name': f'text-{public_id}-{index}', 'label': f'Text {index}'}
                              for index in range(3)])
        for public_id in TYPE_IDS
    ])

    yield TypesManager(database_manager, database_name)

    types.delete_many(SEEDED)


def _page(types_manager: TypesManager, read_projection: dict[str, int] | None) -> list[CmdbType]:
    """The seeded types as the list route reads them, with the given read projection"""
    return types_manager.iterate(BuilderParameters(dict(SEEDED), projection=read_projection)).results


def _answer(types: list[CmdbType], projection: Any) -> list[dict[str, Any]]:
    """What the response answers for the types: serialised, then projected"""
    return APIProjector([CmdbType.to_json(a_type) for a_type in types], APIProjection(projection)).project


@pytest.mark.parametrize('projection', list(FRONTEND_PROJECTIONS.values()), ids=list(FRONTEND_PROJECTIONS))
def test_the_answer_is_the_same_as_a_whole_read(types_manager: TypesManager, projection: Any) -> None:
    """Only what is read changes, never what is answered"""
    projected_read = _page(types_manager, build_type_list_projection(projection))
    whole_read = _page(types_manager, None)

    assert _answer(projected_read, projection) == _answer(whole_read, projection)
    assert len(projected_read) == TYPE_COUNT


@pytest.mark.parametrize('projection', list(FRONTEND_PROJECTIONS.values()), ids=list(FRONTEND_PROJECTIONS))
def test_mongodb_returns_only_the_keys_the_answer_needs(types_manager: TypesManager, projection: Any) -> None:
    """The fields and the ACL stay in the database unless asked for"""
    read_projection = build_type_list_projection(projection)

    documents, total = types_manager.iterate_query(BuilderParameters(dict(SEEDED), projection=read_projection))

    expected_keys = APIProjection(projection).include_roots | set(CmdbType.FROM_DATA_REQUIRED_KEYS)
    assert total == TYPE_COUNT
    for document in documents:
        assert set(document) == expected_keys
        assert MONGO_ID not in document


def test_a_projection_that_drops_a_key_reads_whole_documents(types_manager: TypesManager) -> None:
    """No $project: the response's projector applies a drop as it always did"""
    projection: dict[str, int] = {'fields': 0}

    assert build_type_list_projection(projection) is None
    documents, _ = types_manager.iterate_query(BuilderParameters(dict(SEEDED)))
    assert all('fields' in document for document in documents)
