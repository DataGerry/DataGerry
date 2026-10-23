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
Integration tests for ``import_transfer_document`` and ``preview_transfer_document`` against a real MongoDB - the
pipeline a best-practice model takes, and its preview

The managers' tenant resolver is pointed at a scratch target holding only its database version, so the real pipeline
writes there and nowhere else. The document is the best-practice fixture model (``tests.utils.best_practice_model_
fixture``), so what is pinned is also that such a file is one the real import accepts: imported, every document
stored under its id with its references intact; a second import refused because the system is no longer reset - which
is what keeps the assistant to one model; and a file the import's checks refuse writing nothing. A file whose
`information` counts do not match its entries is refused like any other problem. The preview answers what the import
would say on the same target - importable on a reset system, the blockers once it is not, the problems of a refused
file - without writing anything
"""
from copy import deepcopy
from http import HTTPStatus
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    COUNT_MISMATCH,
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
)
from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.category_model import CmdbCategory
from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner import (
    import_transfer_document,
    preview_transfer_document,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    PreviewResponseKey,
)
from tests.utils.best_practice_model_fixture import (
    COMPANY_TYPE_ID,
    CONTACT_CATEGORY_ID,
    CUSTOMER_TYPE_ID,
    EMPLOYER_FIELD,
    MODEL_DB_VERSION,
    WORKS_FOR_RELATION_ID,
    model_document,
)
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TARGET_SUFFIX: str = '-import-runner-target'
PUBLIC_ID: str = CmdbType.PUBLIC_ID_KEY
UNKNOWN_TYPE_ID: int = 9999
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)


@pytest.fixture(name='target')
def fixture_target(database_manager: MongoDatabaseManager, database_name: str,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A reset target that records the model file's version; the managers routed to it"""
    name: str = f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    SettingsManager(database_manager, name).write(UpdaterSetting.SECTION.value,
                                                  {UpdaterSetting.VERSION.value: MODEL_DB_VERSION})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: name))

    yield client[name]

    client.drop_database(name)


def _ids(target: Any, collection: str) -> list[int]:
    """The public_ids stored in a collection of the target"""
    return sorted(document[PUBLIC_ID] for document in target[collection].find({}, {PUBLIC_ID: 1}))


def test_the_model_is_imported_under_its_ids(target: Any) -> None:
    """Every document as exported, the reference field still targeting the company"""
    imported: dict[str, int] = import_transfer_document(model_document(with_supernet=False), ADMINISTRATOR)

    assert imported[TransferComponentName.TYPES.value] == 2
    assert _ids(target, CmdbType.COLLECTION) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
    assert _ids(target, CmdbCategory.COLLECTION) == [CONTACT_CATEGORY_ID]
    assert _ids(target, CmdbRelation.COLLECTION) == [WORKS_FOR_RELATION_ID]
    customer: dict[str, Any] = target[CmdbType.COLLECTION].find_one({PUBLIC_ID: CUSTOMER_TYPE_ID})
    employer = next(field for field in customer[TypeSchemaKey.FIELDS.value]
                    if field[FieldKey.NAME.value] == EMPLOYER_FIELD)
    assert employer[FieldKey.REF_TYPES.value] == [COMPANY_TYPE_ID]


def test_a_second_import_is_refused_because_the_system_is_no_longer_reset(target: Any) -> None:
    """400 naming what blocks it; the first import stays as it was - one model per installation"""
    import_transfer_document(model_document(with_supernet=False), ADMINISTRATOR)

    with pytest.raises(HTTPException) as exc_info:
        import_transfer_document(model_document(with_supernet=False), ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert CmdbType.COLLECTION in exc_info.value.description
    assert _ids(target, CmdbType.COLLECTION) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]


def test_a_refused_file_writes_nothing(target: Any) -> None:
    """A category naming a type the file does not hold is a problem of the import's checks: 400, the target empty"""
    document: dict[str, Any] = deepcopy(model_document(with_supernet=False))
    categories: dict[str, Any] = document[TransferFileKey.COMPONENTS.value][TransferComponentName.CATEGORIES.value]
    contact: dict[str, Any] = categories[TransferSectionKey.ITEMS.value][0]
    contact[CategoryKey.TYPES.value].append(UNKNOWN_TYPE_ID)

    with pytest.raises(HTTPException) as exc_info:
        import_transfer_document(document, ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert not _ids(target, CmdbType.COLLECTION)
    assert not _ids(target, CmdbCategory.COLLECTION)


def _miscounted() -> dict[str, Any]:
    """The model with one type too many in its information counts"""
    document: dict[str, Any] = deepcopy(model_document(with_supernet=False))
    document[TransferFileKey.INFORMATION.value][TransferInformationKey.COUNTS.value][
        TransferComponentName.TYPES.value] += 1

    return document


def test_counts_that_do_not_match_refuse_the_import(target: Any) -> None:
    """A hand-edited file: 400 naming the mismatch, the target empty"""
    with pytest.raises(HTTPException) as exc_info:
        import_transfer_document(_miscounted(), ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert COUNT_MISMATCH.format(section=TransferFileKey.INFORMATION.value, name=TransferComponentName.TYPES.value,
                                 count=3, actual=2) in exc_info.value.description
    assert not _ids(target, CmdbType.COLLECTION)


def test_the_preview_of_a_reset_system_is_importable_and_writes_nothing(target: Any) -> None:
    """The model's information as written, nothing in the way, the target still empty"""
    document: dict[str, Any] = model_document(with_supernet=False)

    assert preview_transfer_document(document, ADMINISTRATOR) == {
        PreviewResponseKey.INFORMATION.value: document[TransferFileKey.INFORMATION.value],
        PreviewResponseKey.RESET_BLOCKERS.value: [],
        PreviewResponseKey.PROBLEMS.value: [],
        PreviewResponseKey.IMPORTABLE.value: True,
    }
    assert not _ids(target, CmdbType.COLLECTION)
    assert not _ids(target, CmdbCategory.COLLECTION)


def test_the_preview_after_an_import_names_what_blocks_the_next(target: Any) -> None:
    """The stored types block it - and the file's types clash with them by name; the first import untouched"""
    import_transfer_document(model_document(with_supernet=False), ADMINISTRATOR)

    preview: dict[str, Any] = preview_transfer_document(model_document(with_supernet=False), ADMINISTRATOR)

    assert CmdbType.COLLECTION in preview[PreviewResponseKey.RESET_BLOCKERS.value]
    assert [problem.split(':')[0] for problem in preview[PreviewResponseKey.PROBLEMS.value]] == [
        f'types {COMPANY_TYPE_ID}', f'types {CUSTOMER_TYPE_ID}',
    ]
    assert preview[PreviewResponseKey.IMPORTABLE.value] is False
    assert _ids(target, CmdbType.COLLECTION) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]


def test_the_preview_names_the_problems_the_import_refuses(target: Any) -> None:
    """The same mismatch the import refuses, answered - its counts not shown"""
    preview: dict[str, Any] = preview_transfer_document(_miscounted(), ADMINISTRATOR)

    assert preview[PreviewResponseKey.PROBLEMS.value] == [
        COUNT_MISMATCH.format(section=TransferFileKey.INFORMATION.value, name=TransferComponentName.TYPES.value,
                              count=3, actual=2),
    ]
    assert preview[PreviewResponseKey.INFORMATION.value] is None
    assert not _ids(target, CmdbType.COLLECTION)
