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
Database update 20260824: retires the 'dg-rackmounting' predefined section template

The Rack View feature (the RACK SpecialType plus the ``framework.rackMounts`` collection) records
where an object sits in a rack in the mount document itself - ``height``, ``start_slot``, ``area``
and ``position``. The 'dg-rackmounting' section recorded the same three facts as free-text /select
fields on the object, and nothing in the backend ever read them: they were a parallel, purely
informational copy that the Rack View ignores and that could silently drift from the real mounts.
With the Rack View reachable from the start assistant the section is obsolete, so it is removed from
the shipped templates (see SectionTemplateCreator) and this migration takes it out of every database.

What it removes, per consuming CmdbType: the template claim in ``global_template_ids``, the
'dg-rackmounting' section from the layout, the three field definitions from ``fields`` and from the
summary, the stored values from every CmdbObject of the type, and the three field names from the
type's CmdbReports (whose stored query is rebuilt). Finally the section-template document itself.

Two passes are needed. The first drives the shared
``SectionTemplatesManager.cleanup_global_section_templates``, which finds consumers through
``global_template_ids``. The second is a safety net for a type that carries the inlined section
WITHOUT the claim: re-importing an exported type after the template is gone leaves exactly that state
(the type importer drops a claim naming a template it cannot resolve, deliberately without running
the destructive cleanup), and a claim can also have been edited away by hand.

Removing the template from SectionTemplateCreator is what stops it coming back: CollectionValidator
re-seeds every creator template whose name is absent on each start, so deleting the document alone
would have been undone by the next restart.

Both passes and the document deletion are individually idempotent and the version is bumped only
after all three complete, so an interrupted run simply starts over.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.manager.section_templates_manager import SectionTemplatesManager

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType, SectionKey, TypeSchemaKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Name of the retired predefined section template. Hard-coded here rather than imported: the
# definition is gone from the codebase, and a migration has to keep naming the historical shape it
# migrates away from even after every other reference is deleted
RACK_MOUNTING_TEMPLATE: str = 'dg-rackmounting'

# The three field names the retired template contributed, in its declared order. Same reasoning as
# above - this is the frozen historical record of what has to be cleaned out
RACK_MOUNTING_FIELDS: frozenset[str] = frozenset({
    'dg-rackmounting-ru',
    'dg-rackmounting-position',
    'dg-rackmounting-orientation',
})

# Dotted path selecting a stored CmdbType by the name of one of its render_meta sections
TYPE_SECTION_NAME_PATH: str = (
    f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}.{SectionKey.NAME.value}'
)
# -------------------------------------------------------------------------------------------------------------------- #

def find_types_with_inlined_section(section_templates_manager: SectionTemplatesManager) -> list[CmdbType]:
    """
    Finds the CmdbTypes still carrying the retired section in their layout

    Matches on the render_meta section name rather than on ``global_template_ids``, so it also
    returns a type whose template claim was lost while the inlined section survived - the state an
    old type import leaves behind. Types that still hold the claim are returned too; cleaning them a
    second time is a no-op because the first pass already took the section off them

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates

    Returns:
        list[CmdbType]: Every CmdbType whose layout still holds the retired section
    """
    return section_templates_manager.types_manager.find_types({TYPE_SECTION_NAME_PATH: RACK_MOUNTING_TEMPLATE})


def cleanup_claimed_types(section_templates_manager: SectionTemplatesManager) -> None:
    """
    Removes the retired template from every CmdbType that claims it in 'global_template_ids'

    Delegates to the shared removal used when an administrator deletes a global template in the UI,
    so the type schema, the objects and the reports are cleaned exactly the same way here

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates
    """
    section_templates_manager.cleanup_global_section_templates(RACK_MOUNTING_TEMPLATE)


def cleanup_orphaned_types(section_templates_manager: SectionTemplatesManager) -> int:
    """
    Removes the retired section from CmdbTypes that carry it without claiming the template

    The per-type removal resolves the section from the type itself, so it works without a claim. It
    does not touch reports (its route caller re-aligns those itself), so the report cleanup is
    applied here against the re-read, already-cleaned type

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates

    Returns:
        int: Number of CmdbTypes cleaned in this pass
    """
    orphans: list[CmdbType] = find_types_with_inlined_section(section_templates_manager)

    for a_type in orphans:
        section_templates_manager.cleanup_global_section_from_type(a_type.public_id, RACK_MOUNTING_TEMPLATE)

        cleaned_type: CmdbType = section_templates_manager.types_manager.get_type_instance(a_type.public_id)

        if cleaned_type is not None:
            section_templates_manager.cleanup_global_section_reports(cleaned_type, set(RACK_MOUNTING_FIELDS))

    return len(orphans)


def delete_template_document(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Deletes the retired section-template document

    Args:
        dbm (MongoDatabaseManager): Database manager used for the delete
        db_name (str): Name of the database to clean

    Returns:
        bool: True when a document was deleted, False when it was already gone
    """
    criteria: dict[str, Any] = {SectionTemplateKey.NAME.value: RACK_MOUNTING_TEMPLATE}

    existing: dict[str, Any] | None = dbm.find_one_by(CmdbSectionTemplate.COLLECTION, db_name, criteria)

    if existing is None:
        return False

    dbm.delete(CmdbSectionTemplate.COLLECTION, db_name, criteria)

    return True

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260824 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260824(BaseDatabaseUpdate):
    """
    Retires the 'dg-rackmounting' predefined section template and cleans every trace of it
    """
    def creation_date(self) -> int:
        return 20260824


    def description(self) -> str:
        return "Removes the obsolete 'dg-rackmounting' section template from all Types, Objects and Reports"


    def start_update(self) -> None:
        """
        Cleans the claiming types, then the orphaned ones, then deletes the template document

        The document is deleted last so an interrupted run is still discoverable from the template
        collection. Every step is idempotent and the version is bumped only at the end, so a crash
        anywhere leaves the migration re-runnable from the top

        Raises:
            UpdaterException: If any step of the removal fails
        """
        try:
            section_templates_manager: SectionTemplatesManager = SectionTemplatesManager(self.dbm, self.db_name)

            cleanup_claimed_types(section_templates_manager)

            orphans: int = cleanup_orphaned_types(section_templates_manager)

            if orphans:
                LOGGER.info(
                    "[updater_20260824] Cleaned %s Type(s) carrying '%s' without the template claim",
                    orphans, RACK_MOUNTING_TEMPLATE,
                )

            if delete_template_document(self.dbm, self.db_name):
                LOGGER.info("[updater_20260824] Deleted the '%s' section template", RACK_MOUNTING_TEMPLATE)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
