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
The configuration transfer: export the user-defined configuration to one JSON file and import it with every
public_id and counter preserved

    configuration_transfer_constants.py     the file's keys, the component names and order, the problem messages
    transfer_file.py                        builds a transfer file and judges the envelope of an uploaded one
    transfer_component.py                   the contract every component fulfils + the check of their order
    transfer_components.py                  the four components and their import order - THE registry
    configuration_export.py                 the strict database-version read + building an export
    configuration_import.py                 writing a checked file into a reset system, every write on one ledger
    configuration_staging.py                migrating a file of an older version with the real updaters, in a
                                            temporary database
    reset_scope.py                          what a reset clears - the one list the reset and the import's
                                            precondition both read
    reset_runner.py                         runs a reset: deletes each target in list order, sets its counter back
"""
from .configuration_transfer_constants import (
    TRANSFER_FORMAT_VERSION,
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
)
from .transfer_file import (
    build_component_section,
    build_transfer_file,
    db_version_mismatch,
    db_version_too_new,
    find_transfer_file_problems,
)
from .transfer_component import TransferComponent, component_order_problems
from .reset_scope import RESET_TARGETS, ResetTarget, find_import_blockers, find_non_empty_targets, has_import_blockers
from .reset_runner import clear_target, run_reset
from .transfer_components import (
    TRANSFER_COMPONENTS,
    TRANSFER_COMPONENT_NAMES,
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TypeComponent,
)
from .configuration_export import export_configuration, read_database_version
from .configuration_import import import_configuration
from .configuration_staging import migrate_transfer_file
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'TRANSFER_FORMAT_VERSION',
    'TransferComponentName',
    'TransferFileKey',
    'TransferSectionKey',
    'build_component_section',
    'build_transfer_file',
    'db_version_mismatch',
    'db_version_too_new',
    'find_transfer_file_problems',
    'TransferComponent',
    'component_order_problems',
    'RESET_TARGETS',
    'ResetTarget',
    'find_import_blockers',
    'find_non_empty_targets',
    'has_import_blockers',
    'clear_target',
    'run_reset',
    'TRANSFER_COMPONENTS',
    'TRANSFER_COMPONENT_NAMES',
    'CategoryComponent',
    'RelationComponent',
    'SectionTemplateComponent',
    'TypeComponent',
    'export_configuration',
    'read_database_version',
    'import_configuration',
    'migrate_transfer_file',
]
