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
A best-practice model file pair for tests: written into a folder the way a bundle is, read by the real catalogue

``model_document`` is a transfer file of three types - a company, a customer user whose reference field targets the
company, and an IPAM Supernet (so the model needs ``LicenseFeature.IPAM``) - one category holding the first two and
one relation between them. ``write_model_pair`` writes it and its description file; ``model_meta`` is the description
"""
import json
from pathlib import Path
from typing import Any

from cmdb.database.json_codec import default
from cmdb.framework.configuration_transfer.best_practice_constants import (
    META_FILE_SUFFIX,
    MODEL_FILE_ENCODING,
    MODEL_FILE_SUFFIX,
    BestPracticeMetaKey,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import TransferComponentName
from cmdb.framework.configuration_transfer.transfer_components import TRANSFER_COMPONENT_NAMES
from cmdb.framework.configuration_transfer.transfer_file import build_component_section, build_transfer_file
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MODEL_DB_VERSION: int = 20261021

COMPANY_TYPE_ID: int = 41
CUSTOMER_TYPE_ID: int = 42
SUPERNET_TYPE_ID: int = 43
CONTACT_CATEGORY_ID: int = 51
WORKS_FOR_RELATION_ID: int = 61

COMPANY_NAME: str = 'bp-company'
CUSTOMER_NAME: str = 'bp-customer'
SUPERNET_NAME: str = 'bp-supernet'
CONTACT_NAME: str = 'bp-contact'
RELATION_NAME: str = 'bp_works_for'
EMPLOYER_FIELD: str = 'employer'
CONTACT_DESCRIPTION: str = 'People and organizations that use or own assets'


def model_types(with_supernet: bool = True) -> list[dict[str, Any]]:
    """The model's types; without the Supernet the model needs no licence"""
    company: dict[str, Any] = make_type_doc(COMPANY_TYPE_ID, COMPANY_NAME)
    customer: dict[str, Any] = make_type_doc(CUSTOMER_TYPE_ID, CUSTOMER_NAME, fields=[
        {FieldKey.TYPE.value: FieldType.TEXT.value, FieldKey.NAME.value: 'dg-name', FieldKey.LABEL.value: 'Name'},
        {FieldKey.TYPE.value: FieldType.REFERENCE.value, FieldKey.NAME.value: EMPLOYER_FIELD,
         FieldKey.LABEL.value: 'Company', FieldKey.REF_TYPES.value: [COMPANY_TYPE_ID]},
    ])
    types: list[dict[str, Any]] = [company, customer]

    if with_supernet:
        types.append(make_type_doc(SUPERNET_TYPE_ID, SUPERNET_NAME, special_type=SpecialType.SUPERNET.value))

    return types


def model_document(with_supernet: bool = True) -> dict[str, Any]:
    """The model's transfer file"""
    types: list[dict[str, Any]] = model_types(with_supernet)
    items: dict[str, list[dict[str, Any]]] = {
        TransferComponentName.SECTION_TEMPLATES.value: [],
        TransferComponentName.TYPES.value: types,
        TransferComponentName.CATEGORIES.value: [{
            CategoryKey.PUBLIC_ID.value: CONTACT_CATEGORY_ID, CategoryKey.NAME.value: CONTACT_NAME,
            CategoryKey.LABEL.value: 'Contact', CategoryKey.META.value: {CategoryMetaKey.ICON.value: '',
                                                                         CategoryMetaKey.ORDER.value: 1},
            CategoryKey.PARENT.value: None, CategoryKey.TYPES.value: [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID],
        }],
        TransferComponentName.RELATIONS.value: [{
            RelationKey.PUBLIC_ID.value: WORKS_FOR_RELATION_ID, RelationKey.RELATION_NAME.value: RELATION_NAME,
            RelationKey.RELATION_NAME_PARENT.value: 'employs', RelationKey.RELATION_NAME_CHILD.value: 'works for',
            RelationKey.PARENT_TYPE_IDS.value: [COMPANY_TYPE_ID], RelationKey.CHILD_TYPE_IDS.value: [CUSTOMER_TYPE_ID],
        }],
    }

    return build_transfer_file(MODEL_DB_VERSION, {
        name: build_component_section(
            max((item.get(CategoryKey.PUBLIC_ID.value, 0) for item in items[name]), default=0), items[name],
        )
        for name in TRANSFER_COMPONENT_NAMES
    })


def model_meta(title: str = 'Fixture model', order: int = 0) -> dict[str, Any]:
    """The model's description file"""
    return {
        BestPracticeMetaKey.TITLE.value: title,
        BestPracticeMetaKey.BADGE.value: 'Clients & users',
        BestPracticeMetaKey.SUMMARY.value: 'Companies and the people working for them.',
        BestPracticeMetaKey.DESCRIPTION.value: 'A small model for tests.',
        BestPracticeMetaKey.SUITED_FOR.value: ['Tests'],
        BestPracticeMetaKey.PROFILES.value: ['client-management'],
        BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: {CONTACT_NAME: CONTACT_DESCRIPTION},
        BestPracticeMetaKey.ORDER.value: order,
    }


def write_model_pair(folder: Path, model_id: str, document: dict[str, Any] | None = None,
                     meta: dict[str, Any] | None = None) -> None:
    """Writes `<model_id>.json` and `<model_id>.meta.json` into `folder`, dates as the export writes them"""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{model_id}{MODEL_FILE_SUFFIX}').write_text(
        json.dumps(model_document() if document is None else document, default=default), encoding=MODEL_FILE_ENCODING,
    )
    (folder / f'{model_id}{META_FILE_SUFFIX}').write_text(
        json.dumps(model_meta() if meta is None else meta), encoding=MODEL_FILE_ENCODING,
    )
