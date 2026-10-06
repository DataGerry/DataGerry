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
Integration tests for the two rights the DocAPI render requires, against real groups in MongoDB

`user_has_right` - the check behind each `.protect` - reads the caller's group from the database. For a group
per combination of the two rights it answers each right as the group holds it, so the render's stacked gate
passes exactly the group holding both. The seeded default `user` group holds both, which is why the frontend's
users notice no change
"""
from datetime import datetime, timezone

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_RIGHT,
    DocapiTemplateRight,
)
# -------------------------------------------------------------------------------------------------------------------- #

RENDER_RIGHTS: list[str] = [RENDER_OBJECT_RIGHT, DocapiTemplateRight.VIEW.value]

# (group id, rights, whether the render gate passes)
GROUPS: list[tuple[int, list[str], bool]] = [
    (89431, [ObjectRightName.VIEW.value], False),
    (89432, [DocapiTemplateRight.VIEW.value], False),
    (89433, [ObjectRightName.VIEW.value, DocapiTemplateRight.VIEW.value], True),
    (89434, [ObjectRightName.ALL.value, DocapiTemplateRight.VIEW.value], True),
    (89435, [right.value for right in DocapiTemplateRight], False),
]
GROUP_IDS: list[int] = [group[0] for group in GROUPS]


@pytest.fixture(autouse=True)
def _groups(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """One group per combination, inside the request context ManagerProvider resolves through"""
    collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': GROUP_IDS}})
    collection.insert_many([{'public_id': group_id, 'name': f'render-gate-{group_id}',
                             'label': f'Render gate {group_id}', 'rights': rights}
                            for group_id, rights, _ in GROUPS])

    with rest_api.application.test_request_context():
        yield

    collection.delete_many({'public_id': {'$in': GROUP_IDS}})


def _member(group_id: int) -> CmdbUser:
    """A member of `group_id` - the check reads the group, not the user"""
    return CmdbUser(public_id=group_id, user_name=f'render-gate-{group_id}', active=True, group_id=group_id,
                    registration_time=datetime.now(timezone.utc))


@pytest.mark.parametrize(('group_id', 'rights', 'passes'), GROUPS, ids=[str(group[0]) for group in GROUPS])
def test_the_gate_passes_exactly_the_groups_holding_both(group_id: int, rights: list[str], passes: bool) -> None:
    """Both stacked checks hold only for a group with the object right (or its wildcard) and template view"""
    del rights

    assert all(user_has_right(right, _member(group_id)) for right in RENDER_RIGHTS) is passes


def test_the_seeded_user_group_holds_both() -> None:
    """The default group's members render as before"""
    assert all(user_has_right(right, _member(USER_GROUP_ID)) for right in RENDER_RIGHTS)
