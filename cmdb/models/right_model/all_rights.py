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
Implementation of all DataGerry rights

Every right in the product is declared here, once, as a nested tuple tree: a branch is a tuple whose
first element is the wildcard right of that branch and whose remaining elements are its children (each
in turn a right or a nested tuple). `ALL_RIGHTS` is the root, and the nesting is what
`CmdbUserGroup.has_extended_right` mirrors at check time - holding a branch's '*' right grants
everything below it.

The tree is built at import time and never mutated, so adding a right means adding a line here and
nothing else; it is flattened once, at import, into `ALL_RIGHTS_FLAT` / `ALL_RIGHT_NAMES`, which
`RightsManager` and `GroupsManager` share for lookup, and
`RightsManager.tree_to_json` serialises it with the nesting preserved for the frontend's rights picker.
"""
from typing import Any

from cmdb.models.right_model.import_rights import ImportRight, ImportObjectRight, ImportTypeRight
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.system_rights import SystemRight
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER
from cmdb.models.right_model.user_management_rights import (
    UserManagementRight,
    UserRight,
    GroupRight,
)
from cmdb.models.right_model.framework_rights import (
    FrameworkRight,
    ObjectRight,
    TypeRight,
    CategoryRight,
    LogRight,
    SectionTemplateRight,
    WebhookRight,
    RelationRight,
    ObjectRelationRight,
    ObjectRelationLogRight,
    ExtendableOptionRight,
    ObjectGroupRight,
    CiExplorerRight,
    ReportRight,
    IpamRight,
    LocationRight,
    RackRight,
    PortRight,
    ConnectionRight,
)
from cmdb.models.right_model.isms_rights import (
    IsmsRight,
    RiskClassRight,
    LikelihoodRight,
    ImpactRight,
    ImpactCategoryRight,
    ProtectionGoalRight,
    RiskMatrixRight,
    ThreatRight,
    VulnerabilityRight,
    RiskRight,
    ControlMeasureRight,
    RiskAssessmentRight,
    ControlMeasureAssignmentRight,
    IsmsReportRight,
    IsmsImportRight,
)
from cmdb.models.right_model.oc_rights import (
    OpenCeliumRight,
    OcConnectorRight,
    OcConnectionRight,
)
from cmdb.models.right_model.license_rights import (
    LicenseRight,
    LicenseActivationRight,
)
from cmdb.models.right_model.export_rights import ExportRight, ExportObjectRight, ExportTypeRight
from cmdb.models.right_model.docapi_rights import DocapiRight, DocapiTemplateRight
# -------------------------------------------------------------------------------------------------------------------- #

BASE_RIGHT = (
    BaseRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'Every right in DataGerry, including rights added later. Also needed to reset, import and preview a '
            'configuration transfer and to apply a best-practice model'
        ),
    ),
)

SYSTEM_RIGHTS = (
    SystemRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'All system rights: view and change the system settings and export the configuration'
        ),
    ),
    (
        SystemRight(
            'view',
            description=(
                'View the system settings and information: authentication settings and providers, system details and '
                'the configuration file'
            ),
        ),
        SystemRight(
            'edit',
            description=(
                'Change the system settings: authentication (local login and LDAP) and the date and time format'
            ),
        ),
        SystemRight(
            'export',
            description=(
                'Export the configuration - types, categories, section templates and relations - as a transfer file'
            ),
        )
    )
)


FRAMEWORK_RIGHTS = (
    FrameworkRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'All framework rights: objects, types, categories, section templates, relations, reports, IPAM, locations, '
            'racks, ports and more'
        ),
    ),
    (
        ObjectRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All object rights: view, add, edit, delete and activate objects'
            ),
        ),
        (
            ObjectRight(
                'view',
                description=(
                    'View objects: lists, details, counts, references, the search, persons and person groups, media '
                    "files and rendered DocAPI documents. A type's ACL can still hide its objects"
                ),
            ),
            ObjectRight(
                'add',
                description=(
                    "Create objects, persons and person groups. A type's ACL can still refuse it"
                ),
            ),
            ObjectRight(
                'edit',
                description=(
                    "Change objects, persons and person groups, and upload, change and delete media files. A type's ACL"
                    ' can still refuse it'
                ),
            ),
            ObjectRight(
                'delete',
                description=(
                    "Delete objects (one or several at once), persons and person groups. A type's ACL can still refuse "
                    'it'
                ),
            ),
            ObjectRight(
                'activation',
                description=(
                    'Activate and deactivate objects, and read whether an object is active'
                ),
            )
        )
    ),
    (
        TypeRight(GLOBAL_RIGHT_IDENTIFIER, description='All type rights: view, add, edit and delete types'),
        (
            TypeRight(
                'view',
                description=(
                    'View types and their definitions, and the checks shown before a type is changed or deleted. A type'
                    " whose ACL denies the user's groups stays hidden"
                ),
            ),
            TypeRight('add', description='Create types - also with the start assistant, together with Add categories'),
            TypeRight(
                'edit',
                description=(
                    'Change types: fields, sections, ACL and settings. Changes reach every object of the type'
                ),
            ),
            TypeRight('delete', description='Delete types that no longer have any objects')
        )
    ),
    (
        CategoryRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All category rights: view, add, edit and delete categories'
            ),
        ),
        (
            CategoryRight('view', description='View the categories and the category tree'),
            CategoryRight(
                'add',
                description=(
                    'Create categories - also with the start assistant, together with Add types'
                ),
            ),
            CategoryRight('edit', description='Change categories: name, label, parent and the types they hold'),
            CategoryRight('delete', description='Delete categories')
        )
    ),
    (
        SectionTemplateRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All section template rights: view, add, edit and delete section templates'
            ),
        ),
        (
            SectionTemplateRight('view', description='View section templates and how many types use each of them'),
            SectionTemplateRight('add', description='Create section templates'),
            SectionTemplateRight(
                'edit',
                description=(
                    'Change section templates. Changes to a global template reach every type that uses it'
                ),
            ),
            SectionTemplateRight('delete', description='Delete section templates'),
        )
    ),
    (
        WebhookRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All webhook rights: view, add, edit and delete webhooks and their delivery log'
            ),
        ),
        (
            WebhookRight('view', description='View webhooks and their delivery log'),
            WebhookRight(
                'add',
                description=(
                    'Create webhooks. The creator becomes the owner, and only changes to objects the owner may read are'
                    ' delivered'
                ),
            ),
            WebhookRight('edit', description='Change webhooks. Whoever saves a webhook becomes its owner'),
            WebhookRight('delete', description='Delete webhooks and entries of their delivery log'),
        )
    ),
    (
        LogRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All object log rights: view and delete the change history of objects'
            ),
        ),
        (
            LogRight(
                'view',
                description=(
                    'View the change history (logs) of objects, including the logs of deleted objects'
                ),
            ),
            LogRight('delete', description='Delete entries from the change history of objects')
        )
    ),
    (
        RelationRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All relation rights: view, add, edit and delete relation definitions'
            ),
        ),
        (
            RelationRight(
                'view',
                description=(
                    'View relation definitions - which types can be related to each other, and how'
                ),
            ),
            RelationRight('add', description='Create relation definitions'),
            RelationRight('edit', description='Change relation definitions'),
            RelationRight('delete', description='Delete relation definitions'),
        )
    ),
    (
        ObjectRelationRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All object relation rights: view, add, edit and delete relations between objects'
            ),
        ),
        (
            ObjectRelationRight(
                'view',
                description=(
                    "View the relations between objects, such as an object's relation tabs. Both objects must be "
                    'readable'
                ),
            ),
            ObjectRelationRight('add', description='Relate two objects to each other'),
            ObjectRelationRight('edit', description='Change relations between objects'),
            ObjectRelationRight('delete', description='Remove relations between objects, one or several at once'),
        )
    ),
    (
        ObjectRelationLogRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All rights on the change history of object relations: view and delete it'
            ),
        ),
        (
            ObjectRelationLogRight('view', description='View the change history of relations between objects'),
            ObjectRelationLogRight(
                'delete',
                description=(
                    'Delete entries from the change history of relations between objects'
                ),
            ),
        )
    ),
        ExtendableOptionRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All rights on extendable options - the option lists users can add values to'
            ),
        ),
        (
            ExtendableOptionRight('view', description='View extendable options'),
            ExtendableOptionRight('add', description='Create extendable options'),
            ExtendableOptionRight('edit', description='Change extendable options'),
            ExtendableOptionRight('delete', description='Delete extendable options'),
        ),
        ObjectGroupRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All object group rights: view, add, edit and delete object groups'
            ),
        ),
        (
            ObjectGroupRight('view', description='View object groups'),
            ObjectGroupRight('add', description='Create object groups'),
            ObjectGroupRight('edit', description='Change object groups and their members'),
            ObjectGroupRight('delete', description='Delete object groups'),
        ),
        CiExplorerRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All CI Explorer rights: use the explorer and manage its profiles'
            ),
        ),
        (
            CiExplorerRight(
                'view',
                description=(
                    'Use the CI Explorer - browse objects and their connections as a graph - and load saved profiles'
                ),
            ),
            CiExplorerRight(
                'edit',
                description=(
                    "Save, change and delete CI Explorer profiles and set a type's label field"
                ),
            ),
        ),
        ReportRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All report rights: view, run, add, edit and delete reports and report categories'
            ),
        ),
        (
            ReportRight('view', description='View and run reports, and view report categories'),
            ReportRight('add', description='Create reports and report categories'),
            ReportRight('edit', description='Change reports and report categories'),
            ReportRight('delete', description='Delete reports and report categories'),
        ),
        IpamRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All IPAM rights: view IP address management and unassign entries'
            ),
        ),
        (
            IpamRight(
                'view',
                description=(
                    'View IPAM: supernets, subnets, the network tree, the overviews and their exports, and check '
                    'entries before they are saved'
                ),
            ),
            IpamRight(
                'edit',
                description=(
                    'Unassign subnets and IP addresses in IPAM. Creating and deleting IPAM entries needs the object '
                    'rights'
                ),
            ),
        ),
        LocationRight(GLOBAL_RIGHT_IDENTIFIER, description='All location rights: view and move locations'),
        (
            LocationRight('view', description="View the location tree and an object's location, parent and children"),
            LocationRight(
                'edit',
                description=(
                    'Move objects within the location tree. Creating and deleting locations needs the object rights'
                ),
            ),
        ),
        RackRight(GLOBAL_RIGHT_IDENTIFIER, description='All rack rights: view racks and mount objects in them'),
        (
            RackRight(
                'view',
                description=(
                    'View racks: what is mounted where, the overview, height conflicts and the objects that can be '
                    'mounted'
                ),
            ),
            RackRight('edit', description='Mount, move and unmount objects in racks'),
        ),
        PortRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All port rights: view, add, edit and delete ports and their interface links'
            ),
        ),
        (
            PortRight('view', description='View ports, their cabling and their interface links'),
            PortRight(
                'add',
                description=(
                    "Create ports, one or many at once. Also needed to copy an object's ports when the object is cloned"
                ),
            ),
            PortRight('edit', description='Change ports and their interface links'),
            PortRight('delete', description='Delete ports and interface links'),
        ),
        ConnectionRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All port connection rights: view, add, edit and delete connections between ports'
            ),
        ),
        (
            ConnectionRight('view', description='View connections between ports and which cables are in use'),
            ConnectionRight('add', description='Connect ports with each other'),
            ConnectionRight('edit', description='Change connections between ports'),
            ConnectionRight('delete', description="Remove connections between ports - one, or all of an object's"),
        ),
)

ISMS_RIGHTS = (
    IsmsRight(GLOBAL_RIGHT_IDENTIFIER, description='All ISMS rights'),
    (
        RiskClassRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS risk classes'),
        (
            RiskClassRight('view', description='View ISMS risk classes'),
            RiskClassRight('add', description='Create ISMS risk classes'),
            RiskClassRight('edit', description='Change ISMS risk classes, also several at once'),
            RiskClassRight('delete', description='Delete ISMS risk classes'),
        ),
        LikelihoodRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS likelihoods'),
        (
            LikelihoodRight('view', description='View ISMS likelihoods'),
            LikelihoodRight('add', description='Create ISMS likelihoods'),
            LikelihoodRight('edit', description='Change ISMS likelihoods'),
            LikelihoodRight('delete', description='Delete ISMS likelihoods'),
        ),
        ImpactRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS impacts'),
        (
            ImpactRight('view', description='View ISMS impacts'),
            ImpactRight('add', description='Create ISMS impacts'),
            ImpactRight('edit', description='Change ISMS impacts'),
            ImpactRight('delete', description='Delete ISMS impacts'),
        ),
        ImpactCategoryRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS impact categories'),
        (
            ImpactCategoryRight('view', description='View ISMS impact categories'),
            ImpactCategoryRight('add', description='Create ISMS impact categories'),
            ImpactCategoryRight('edit', description='Change ISMS impact categories, also several at once'),
            ImpactCategoryRight('delete', description='Delete ISMS impact categories'),
        ),
        ProtectionGoalRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS protection goals'),
        (
            ProtectionGoalRight('view', description='View ISMS protection goals'),
            ProtectionGoalRight('add', description='Create ISMS protection goals'),
            ProtectionGoalRight('edit', description='Change ISMS protection goals'),
            ProtectionGoalRight('delete', description='Delete ISMS protection goals'),
        ),
        RiskMatrixRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on the ISMS risk matrix'),
        (
            RiskMatrixRight('view', description='View the ISMS risk matrix'),
            RiskMatrixRight('edit', description='Change the ISMS risk matrix'),
        ),
        ThreatRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS threats'),
        (
            ThreatRight('view', description='View ISMS threats'),
            ThreatRight('add', description='Create ISMS threats'),
            ThreatRight('edit', description='Change ISMS threats'),
            ThreatRight('delete', description='Delete ISMS threats, one or several at once'),
        ),
        VulnerabilityRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS vulnerabilities'),
        (
            VulnerabilityRight('view', description='View ISMS vulnerabilities'),
            VulnerabilityRight('add', description='Create ISMS vulnerabilities'),
            VulnerabilityRight('edit', description='Change ISMS vulnerabilities'),
            VulnerabilityRight('delete', description='Delete ISMS vulnerabilities, one or several at once'),
        ),
        RiskRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS risks'),
        (
            RiskRight('view', description='View ISMS risks'),
            RiskRight('add', description='Create ISMS risks'),
            RiskRight('edit', description='Change ISMS risks'),
            RiskRight('delete', description='Delete ISMS risks, one or several at once'),
        ),
        ControlMeasureRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All rights on ISMS control measures and control catalogs'
            ),
        ),
        (
            ControlMeasureRight(
                'view',
                description=(
                    'View ISMS control measures and which control catalogs are imported'
                ),
            ),
            ControlMeasureRight(
                'add',
                description=(
                    'Create ISMS control measures and import them from a control catalog'
                ),
            ),
            ControlMeasureRight('edit', description='Change ISMS control measures'),
            ControlMeasureRight(
                'delete',
                description=(
                    'Delete ISMS control measures, one or several at once, and remove an imported control catalog'
                ),
            ),
        ),
        RiskAssessmentRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on ISMS risk assessments'),
        (
            RiskAssessmentRight('view', description='View ISMS risk assessments'),
            RiskAssessmentRight('add', description='Create and duplicate ISMS risk assessments'),
            RiskAssessmentRight('edit', description='Change ISMS risk assessments'),
            RiskAssessmentRight('delete', description='Delete ISMS risk assessments'),
        ),
        ControlMeasureAssignmentRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All rights on assigning ISMS control measures'
            ),
        ),
        (
            ControlMeasureAssignmentRight('view', description='View which control measures are assigned to what'),
            ControlMeasureAssignmentRight('add', description='Assign control measures'),
            ControlMeasureAssignmentRight('edit', description='Change control measure assignments'),
            ControlMeasureAssignmentRight('delete', description='Remove control measure assignments'),
        ),
        IsmsReportRight(GLOBAL_RIGHT_IDENTIFIER, description='All ISMS report rights'),
        (
            IsmsReportRight(
                'view',
                description=(
                    'View the ISMS reports: risk matrix, risk treatment plan, statement of applicability (SoA) and risk'
                    ' assessments'
                ),
            ),
        ),
        IsmsImportRight(GLOBAL_RIGHT_IDENTIFIER, description='All ISMS import rights'),
        (
            IsmsImportRight('add', description='Import ISMS data from a file'),
        ),
    ),
)

OC_RIGHTS = (
    OpenCeliumRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'All OpenCelium rights: connectors, connections, schedulers and templates'
        ),
    ),
    (
        OcConnectorRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on OpenCelium connectors'),
        (
            OcConnectorRight(
                'view',
                description=(
                    'View OpenCelium connectors and invokers, and check the master password'
                ),
            ),
            OcConnectorRight('add', description='Create OpenCelium connectors and test whether they can connect'),
            OcConnectorRight('edit', description='Change OpenCelium connectors'),
            OcConnectorRight('delete', description='Delete OpenCelium connectors'),
        ),
        OcConnectionRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All rights on OpenCelium connections, schedulers and templates'
            ),
        ),
        (
            OcConnectionRight(
                'view',
                description=(
                    'View OpenCelium connections and their logs, schedulers, templates and the OpenCelium license'
                ),
            ),
            OcConnectionRight(
                'add',
                description=(
                    'Create OpenCelium connections, schedulers and templates, and test connections'
                ),
            ),
            OcConnectionRight(
                'edit',
                description=(
                    'Change OpenCelium connections and schedulers, and run a scheduler right away'
                ),
            ),
            OcConnectionRight('delete', description='Delete OpenCelium schedulers and connection logs'),
        )
    )
)

LICENSE_RIGHTS = (
    LicenseRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'All license rights: view, activate and remove the license and create activation requests'
        ),
    ),
    (
        LicenseRight('view', description='View the active license and the subscription license'),
        LicenseRight('edit', description='Activate or upload a license'),
        LicenseRight('delete', description='Remove the active license'),
        LicenseActivationRight(GLOBAL_RIGHT_IDENTIFIER, description='All rights on license activation requests'),
        (
            LicenseActivationRight('view', description='Create a license activation request'),
        )
    )
)

EXPORT_RIGHTS = (
    ExportRight(GLOBAL_RIGHT_IDENTIFIER, description='All export rights: export objects and types'),
    (
        ExportObjectRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                "Export objects to a file and download a type's import template"
            ),
        )
    ),
    (
        ExportTypeRight(GLOBAL_RIGHT_IDENTIFIER, description='Export types to a file')
    )
)


IMPORT_RIGHTS = (
    ImportRight(GLOBAL_RIGHT_IDENTIFIER, description='All import rights: import objects and types'),
    (
        ImportObjectRight(GLOBAL_RIGHT_IDENTIFIER, description='Import objects from a file')
    ),
    (
        ImportTypeRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'Import types from a file - create new types or update existing ones'
            ),
        )
    )
)


USER_MANAGEMENT_RIGHTS = (
    UserManagementRight(GLOBAL_RIGHT_IDENTIFIER, description='All user management rights: users and user groups'),
    (
        UserRight(GLOBAL_RIGHT_IDENTIFIER, description='All user rights: view, add, edit and delete users'),
        (
            UserRight('view', description='View users and their rights. Every user can always view their own record'),
            UserRight(
                'add',
                description=(
                    'Create users. Only an administrator can put a user into the administrator group'
                ),
            ),
            UserRight(
                'edit',
                description=(
                    'Change users, their passwords and settings. Every user can change their own profile; only an '
                    'administrator can change an administrator'
                ),
            ),
            UserRight(
                'delete',
                description=(
                    'Delete users. Only an administrator can delete an administrator, and the initial administrator can'
                    ' never be deleted'
                ),
            )
        ),
        GroupRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All user group rights: view, add, edit and delete user groups'
            ),
        ),
        (
            GroupRight('view', description='View user groups, where they are used, and the list of all rights'),
            GroupRight('add', description='Create user groups and choose their rights'),
            GroupRight('edit', description='Change user groups and their rights'),
            GroupRight(
                'delete',
                description=(
                    'Delete user groups. Members whose only group it is are moved to another group or deleted'
                ),
            )
        ),
    )
)


DOCAPI_RIGHTS = (
    DocapiRight(
        GLOBAL_RIGHT_IDENTIFIER,
        description=(
            'All DocAPI rights: view, add, edit and delete document templates'
        ),
    ),
    (
        DocapiTemplateRight(
            GLOBAL_RIGHT_IDENTIFIER,
            description=(
                'All DocAPI template rights: view, add, edit and delete document templates'
            ),
        ),
        (
            DocapiTemplateRight(
                'view',
                description=(
                    'View document templates and render documents from them. Rendering also needs View objects'
                ),
            ),
            DocapiTemplateRight('add', description='Create document templates'),
            DocapiTemplateRight('edit', description='Change document templates'),
            DocapiTemplateRight('delete', description='Delete document templates'),
        ),
    )
)

ALL_RIGHTS = (
    BASE_RIGHT,
    SYSTEM_RIGHTS,
    FRAMEWORK_RIGHTS,
    EXPORT_RIGHTS,
    IMPORT_RIGHTS,
    USER_MANAGEMENT_RIGHTS,
    DOCAPI_RIGHTS,
    ISMS_RIGHTS,
    OC_RIGHTS,
    LICENSE_RIGHTS,
)

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

def flat_rights_tree(right_tree: tuple[Any, ...] | list[Any]) -> list[BaseRight]:
    """
    Flattens a nested right tree into a flat list of rights

    Recurses into nested tuples/lists and collects every leaf `BaseRight` into a single flat list,
    discarding the grouping structure. One list is filled in tree order, so the cost is linear in the
    size of the tree. This is the one implementation of the flattening; `ALL_RIGHTS_FLAT` holds its
    result for the catalogue

    Args:
        right_tree (tuple[Any, ...] | list[Any]): A nested structure containing rights

    Returns:
        list[BaseRight]: A flat list containing all rights
    """
    rights: list[BaseRight] = []
    _collect_rights(right_tree, rights)

    return rights


def _collect_rights(right_tree: tuple[Any, ...] | list[Any], rights: list[BaseRight]) -> None:
    """
    Appends every leaf right of a nested right tree to a list, in tree order

    Args:
        right_tree (tuple[Any, ...] | list[Any]): A nested structure containing rights
        rights (list[BaseRight]): The list the leaves are appended to, in place
    """
    for node in right_tree:
        if isinstance(node, (tuple, list)):
            _collect_rights(node, rights)
        else:
            rights.append(node)

# --------------------------------------------- FLATTENED CATALOGUE CACHE -------------------------------------------- #

# The catalogue flattened once at import - the tree is static, so every manager shares this list instead of
# flattening it again per instance (a GroupsManager is built on every protected request). Read-only by contract
ALL_RIGHTS_FLAT: list[BaseRight] = flat_rights_tree(ALL_RIGHTS)

# Every qualified right name the catalogue knows - what a group's `rights` may carry
ALL_RIGHT_NAMES: frozenset[str] = frozenset(right.name for right in ALL_RIGHTS_FLAT)
