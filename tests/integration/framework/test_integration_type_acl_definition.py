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
Integration tests, against a real MongoDB: the readers that hide a Type the caller's group may not READ

The category tree and the reference-section pre-check judge the ACL inside their one query (the tree's type read is
filtered by the permitted-types criteria; the pre-check projects ``acl`` and judges each dependent), and the import
update judges the STORED type it reads before it writes. Each runs here on real documents with real managers
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CategoriesManager, SectionTemplatesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.category_model import CategoryTree, CmdbCategory
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import ReferencedSectionUsageKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    build_referenced_section_usage_payload,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import update_type_from_entry
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

HIDDEN_TYPE_ID: int = 9741
OPEN_TYPE_ID: int = 9742
HIDDEN_DEPENDENT_ID: int = 9743
TYPE_IDS: list[int] = [HIDDEN_TYPE_ID, OPEN_TYPE_ID, HIDDEN_DEPENDENT_ID]
CATEGORY_ID: int = 9751

READER_GROUP_ID: int = 9761
OTHER_GROUP_ID: int = 9762
REFERENCED_SECTION: str = 'information'
ACL_KEY: str = TypeSchemaKey.ACL.value

READER: CmdbUser = CmdbUser(public_id=9771, user_name='type-acl-reader', active=True, group_id=READER_GROUP_ID)


def _acl(group_id: int) -> dict[str, Any]:
    """An activated ACL granting READ to that group alone."""
    return {'activated': True, 'groups': {'includes': {str(group_id): ['READ']}}}


def _type(public_id: int, group_id: int) -> dict[str, Any]:
    """A stored type readable by that group alone."""
    doc = make_type_doc(public_id, f'integration-type-acl-{public_id}')
    doc[ACL_KEY] = _acl(group_id)

    return doc


def _hidden_dependent() -> dict[str, Any]:
    """A type the reader may not read, pulling the open type's section through a reference section."""
    doc = _type(HIDDEN_DEPENDENT_ID, OTHER_GROUP_ID)
    doc['render_meta']['sections'].append({
        'type': SectionType.REF_SECTION.value, 'name': 'the-ref', 'label': 'The ref', 'fields': [],
        'reference': {'type_id': OPEN_TYPE_ID, 'section_name': REFERENCED_SECTION, 'selected_fields': []},
    })

    return doc


@pytest.fixture(name='types')
def fixture_types(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The hidden, the open and the hidden dependent type, and a category holding the first two."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        categories.delete_many({'public_id': CATEGORY_ID})

    _purge()
    types.insert_many([_type(HIDDEN_TYPE_ID, OTHER_GROUP_ID), _type(OPEN_TYPE_ID, READER_GROUP_ID),
                       _hidden_dependent()])
    categories.insert_one({'public_id': CATEGORY_ID, 'name': 'integration-type-acl', 'label': 'Type ACL',
                           'parent': None, 'types': [HIDDEN_TYPE_ID, OPEN_TYPE_ID],
                           'meta': {'icon': '', 'order': None}})
    with rest_api.application.app_context():
        yield types
    _purge()


def test_the_category_tree_holds_only_the_readable_type(types: Any) -> None:
    """The hidden type is assigned to the category and is never read into it"""
    del types
    manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, READER)

    tree: CategoryTree = manager.get_tree(READER)

    node = next(node for node in tree.tree if node.category.get_public_id() == CATEGORY_ID)
    assert [a_type.public_id for a_type in node.types] == [OPEN_TYPE_ID]


def test_the_reference_pre_check_counts_the_hidden_dependent_without_naming_it(types: Any) -> None:
    """The projected acl is judged per dependent: counted, not named, the section kept with an empty list"""
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, READER)
    del types

    payload = build_referenced_section_usage_payload(READER, types_manager.get_type_instance(OPEN_TYPE_ID))

    assert payload[ReferencedSectionUsageKey.COUNT.value] == 1
    assert payload[ReferencedSectionUsageKey.REFERENCING_TYPE_IDS.value] == []
    assert payload[ReferencedSectionUsageKey.SECTIONS.value] == {REFERENCED_SECTION: []}


def test_the_import_update_leaves_the_hidden_type_untouched(types: Any) -> None:
    """Refused on the stored ACL, though the upload grants the reader; nothing is written"""
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, READER)
    templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES, READER)
    before: dict[str, Any] = types.find_one({'public_id': HIDDEN_TYPE_ID}, {'_id': 0})
    upload: dict[str, Any] = {**before, ACL_KEY: _acl(READER_GROUP_ID), 'label': 'rewritten'}

    result = update_type_from_entry(upload, types_manager, templates_manager, READER)

    assert result == TypeImportError.TYPE_ACCESS_DENIED.format(public_id=HIDDEN_TYPE_ID)
    assert types.find_one({'public_id': HIDDEN_TYPE_ID}, {'_id': 0}) == before
