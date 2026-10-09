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
Database update 20261003: stores every CmdbType's ``acl`` as the complete block

Every write path stores a complete ``{'activated': <bool>, 'groups': {'includes': {...}}}`` - the type create through
``normalize_type_acl``, the update and the import through the model, the start assistant through
``AccessControlList.default_json``. A CmdbType stored before that may still carry an older shape: no ``acl`` at all,
an ``acl`` without ``activated`` (or a null one), or one without ``groups`` - typically ``{'activated': False}``, what
the type builder sent before the create normalised it. A shape that is no document at all, or a null ``groups`` /
``includes``, is covered too.

All of them already read as "grants" in both readers (``acl/helpers.acl_grants_access`` and
``acl/builder.build_denied_types_criteria``), so this is housekeeping: each is rewritten to
``AccessControlList.normalize_stored`` - the block the readers take it for - and no access decision changes. What it
buys is one shape in the collection, so a query, a document read during a support call and ``GET /types/<id>``
(which answers the stored document) all see the same structure.

Idempotent by construction: the selection matches only a document that is not the complete block, and every write
stores the complete block, so a second run selects nothing
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ACL_FIELD: str = TypeSchemaKey.ACL.value
ACTIVATED_PATH: str = f'{ACL_FIELD}.{AclKey.ACTIVATED.value}'
GROUPS_PATH: str = f'{ACL_FIELD}.{AclKey.GROUPS.value}'
INCLUDES_PATH: str = f'{GROUPS_PATH}.{AclKey.INCLUDES.value}'

# The BSON types of a complete block: its innermost document, and its switch
DOCUMENT_TYPE: str = 'object'
BOOLEAN_TYPE: str = 'bool'

# A stored ``acl`` that is not the complete block. Two clauses are enough, because a path through a missing, null or
# non-document level is itself missing: an ``acl`` that is absent or no document has no boolean switch, and a
# ``groups`` that is absent, null or no document has no ``includes`` document
INCOMPLETE_ACL_CRITERIA: dict[str, Any] = {
    '$or': [
        {ACTIVATED_PATH: {'$not': {'$type': BOOLEAN_TYPE}}},
        {INCLUDES_PATH: {'$not': {'$type': DOCUMENT_TYPE}}},
    ],
}

# Only what the rewrite needs to know
ACL_PROJECTION: dict[str, int] = {TypeSchemaKey.PUBLIC_ID.value: 1, ACL_FIELD: 1, '_id': 0}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261003 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261003(BaseDatabaseUpdate):
    """
    Rewrites every CmdbType's incomplete ``acl`` to the complete block it already reads as

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261003


    def description(self) -> str:
        return "Stores every Type's 'acl' as the complete block"


    def start_update(self) -> None:
        """
        Reads the types whose ``acl`` is incomplete, writes each one's complete block back, then bumps the version

        Raises:
            UpdaterException: If the read or the rewrite failed
        """
        try:
            documents: list[dict[str, Any]] = list(self.dbm.find(
                collection=CmdbType.COLLECTION,
                db_name=self.db_name,
                filter=INCOMPLETE_ACL_CRITERIA,
                projection=ACL_PROJECTION,
            ))

            operations: list[UpdateOne] = [
                UpdateOne(
                    {TypeSchemaKey.PUBLIC_ID.value: document[TypeSchemaKey.PUBLIC_ID.value], **INCOMPLETE_ACL_CRITERIA},
                    {'$set': {ACL_FIELD: AccessControlList.normalize_stored(document.get(ACL_FIELD))}},
                )
                for document in documents
            ]

            if operations:
                self.dbm.bulk_write(CmdbType.COLLECTION, self.db_name, operations)

            LOGGER.info("[Update20261003] Stored the complete 'acl' block on %s Type(s)", len(operations))

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
