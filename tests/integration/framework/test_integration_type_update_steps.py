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
Integration tests for the steps of the Type update, against a real MongoDB

The change guards judge the stored Objects through the real managers, and the write stores the Type once - the
dropped template already out of it - then aligns its Objects and clears the marker. A Type deleted since its read
is not written back
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import TYPE_GONE_BEFORE_UPDATE_MESSAGE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import compute_removed_global_templates
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_update_helper import (
    guard_type_update_changes,
    write_type_update,
)
from tests.utils import type_alignment_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

RENAMED_FIELD: str = 'renamed-drop'
HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The alignment seed with its global template: a Type, its Objects, their Locations and a Report"""
    seed.seed(database_manager, database_name, with_template=True)

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


def _stored(database_manager: MongoDatabaseManager, database_name: str) -> CmdbType:
    """The stored Type"""
    return CmdbType.from_data(seed.stored_type(database_manager, database_name))


def _renamed(stored: dict[str, Any]) -> dict[str, Any]:
    """The stored Type with DROP renamed - one removal plus one addition while Objects exist"""
    payload: dict[str, Any] = seed.updated_payload(stored, adding=False)
    payload[TypeSchemaKey.FIELDS.value].append({
        FieldKey.TYPE.value: FieldType.TEXT.value,
        FieldKey.NAME.value: RENAMED_FIELD,
        FieldKey.LABEL.value: RENAMED_FIELD,
    })
    payload[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value][0][SectionKey.FIELDS.value].append(
        RENAMED_FIELD,
    )

    return payload


class TestGuardTypeUpdateChanges:
    """The guards read the stored Objects"""

    def test_a_rename_while_objects_exist_is_refused(self, full_access_user, database_manager, database_name) -> None:
        """Every Object stores its value under the old name"""
        old_type = _stored(database_manager, database_name)
        new_type = CmdbType.from_data(_renamed(seed.stored_type(database_manager, database_name)))

        with pytest.raises(HTTPException) as exc_info:
            guard_type_update_changes(full_access_user, old_type, new_type, old_type.special_type)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert RENAMED_FIELD in exc_info.value.description

    def test_an_unchanged_type_passes(self, full_access_user, database_manager, database_name) -> None:
        """Nothing to refuse"""
        old_type = _stored(database_manager, database_name)

        guard_type_update_changes(full_access_user, old_type, old_type, old_type.special_type)


class TestWriteTypeUpdate:
    """One write, then the alignment"""

    def test_the_dropped_template_leaves_the_type_and_the_objects(
        self, full_access_user, database_manager, database_name,
    ) -> None:
        """The stored Type no longer claims it, its Objects no longer hold its field, the marker is cleared"""
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, full_access_user)
        old_type = _stored(database_manager, database_name)
        payload: dict[str, Any] = seed.updated_payload(
            seed.stored_type(database_manager, database_name), drop_template=True,
        )
        removed = compute_removed_global_templates(old_type, set(payload[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value]))

        write_type_update(full_access_user, types_manager, old_type, CmdbType.from_data(payload), removed)

        stored: dict[str, Any] = seed.stored_type(database_manager, database_name)
        assert stored[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] == []
        stored_field_names: set[str] = {field[FieldKey.NAME.value] for field in stored[TypeSchemaKey.FIELDS.value]}
        assert seed.TEMPLATE_FIELD not in stored_field_names
        assert stored[TypeSchemaKey.LABEL.value] == seed.AFTER_LABEL
        assert not stored.get(TypeSchemaKey.ALIGNMENT_PENDING.value)
        assert all(seed.TEMPLATE_FIELD not in names
                   for names in seed.object_field_names(database_manager, database_name))

    def test_a_type_deleted_since_its_read_is_not_written_back(
        self, full_access_user, database_manager, database_name,
    ) -> None:
        """404, and no document is created"""
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, full_access_user)
        old_type = _stored(database_manager, database_name)
        database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one(
            {TypeSchemaKey.PUBLIC_ID.value: seed.TYPE_ID},
        )

        with pytest.raises(HTTPException) as exc_info:
            write_type_update(full_access_user, types_manager, old_type, old_type, (set(), {}))

        assert exc_info.value.code == HTTP_NOT_FOUND
        assert exc_info.value.description == TYPE_GONE_BEFORE_UPDATE_MESSAGE.format(public_id=seed.TYPE_ID)
        assert seed.stored_type(database_manager, database_name) is None
