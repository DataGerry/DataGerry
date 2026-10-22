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
Unit tests for ``start_assistant_routes.best_practice_helper`` - a model's card and details as the routes answer them

The fixture model (``tests.utils.best_practice_model_fixture``) is loaded by the real catalogue from ``tmp_path``; the
licence predicate ``feature_locked`` is patched, so what is pinned is how the answer reads it: the required features
from the file, the locked ones as ``missing_features``, ``applicable`` when none is missing
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from werkzeug.exceptions import Forbidden

from cmdb.framework.configuration_transfer import BestPracticeModel, build_model_preview, load_catalogue
from cmdb.framework.configuration_transfer.best_practice_constants import BestPracticeMetaKey
from cmdb.framework.configuration_transfer.best_practice_preview import PreviewCounts
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import (
    abort_if_model_unlicensed,
    apply_best_practice_model,
    build_model_card,
    build_model_details,
    missing_features,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    BestPracticeApplyKey,
    BestPracticeModelKey,
    StartAssistantDecision,
    StartAssistantKey,
)
from tests.utils.best_practice_model_fixture import (
    COMPANY_NAME,
    CONTACT_DESCRIPTION,
    CUSTOMER_NAME,
    EMPLOYER_FIELD,
    RELATION_NAME,
    SUPERNET_NAME,
    model_document,
    model_meta,
    write_model_pair,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper'
MODEL_ID: str = 'fixture'
IPAM: str = LicenseFeature.IPAM.value

# The detail tree's keys are the preview dataclasses' field names
NAME, LABEL, TYPES, SECTIONS, FIELDS = 'name', 'label', 'types', 'sections', 'fields'
DESCRIPTION, TARGETS, PARENT_TYPES, CHILD_TYPES = 'description', 'targets', 'parent_types', 'child_types'
COMPANY_REF: dict[str, str] = {NAME: COMPANY_NAME, LABEL: COMPANY_NAME}
CUSTOMER_REF: dict[str, str] = {NAME: CUSTOMER_NAME, LABEL: CUSTOMER_NAME}


def _model(tmp_path: Path, with_supernet: bool = True) -> BestPracticeModel:
    """The fixture model, read by the real catalogue"""
    write_model_pair(tmp_path, MODEL_ID, document=model_document(with_supernet))

    return load_catalogue(tmp_path).get(MODEL_ID)


@pytest.fixture(name='locked')
def fixture_locked() -> Any:
    """`feature_locked` answering True: every licensed feature is missing"""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=True) as locked:
        yield locked


@pytest.fixture(name='licensed')
def fixture_licensed() -> Any:
    """`feature_locked` answering False: nothing is missing"""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=False) as locked:
        yield locked


class TestMissingFeatures:
    """The required features the installation may not use"""

    def test_a_locked_feature_is_missing(self, locked: MagicMock) -> None:
        """Asked as the LicenseFeature, for the caller"""
        user = MagicMock()

        assert missing_features((IPAM,), user) == [IPAM]
        locked.assert_called_once_with(LicenseFeature.IPAM, user)

    def test_a_licensed_feature_is_not(self, licensed: MagicMock) -> None:
        """Nothing missing"""
        del licensed

        assert not missing_features((IPAM,), MagicMock())

    def test_no_required_feature_asks_nothing(self, locked: MagicMock) -> None:
        """No licence read for a model that needs none"""
        assert not missing_features((), MagicMock())
        locked.assert_not_called()


class TestTheCard:
    """One model's card in the selection"""

    @pytest.mark.usefixtures('locked')
    def test_the_card_carries_the_description_and_the_computed_values(self, tmp_path: Path) -> None:
        """Texts from the description file, numbers and chips from the model file"""
        model = _model(tmp_path)
        meta = model_meta()

        assert build_model_card(model, build_model_preview(model.document, model.meta), MagicMock()) == {
            BestPracticeModelKey.MODEL_ID.value: MODEL_ID,
            BestPracticeModelKey.TITLE.value: meta[BestPracticeMetaKey.TITLE.value],
            BestPracticeModelKey.BADGE.value: meta[BestPracticeMetaKey.BADGE.value],
            BestPracticeModelKey.SUMMARY.value: meta[BestPracticeMetaKey.SUMMARY.value],
            BestPracticeModelKey.COUNTS.value: asdict(PreviewCounts(categories=1, types=3, fields=4, relations=1)),
            BestPracticeModelKey.CATEGORY_LABELS.value: ['Contact'],
            BestPracticeModelKey.REQUIRED_FEATURES.value: [IPAM],
            BestPracticeModelKey.MISSING_FEATURES.value: [IPAM],
            BestPracticeModelKey.APPLICABLE.value: False,
        }

    @pytest.mark.usefixtures('licensed')
    def test_a_licensed_installation_may_apply_it(self, tmp_path: Path) -> None:
        """Required, but not missing"""
        model = _model(tmp_path)
        card = build_model_card(model, build_model_preview(model.document, model.meta), MagicMock())

        assert (card[BestPracticeModelKey.MISSING_FEATURES.value], card[BestPracticeModelKey.APPLICABLE.value]) == (
            [], True)

    @pytest.mark.usefixtures('locked')
    def test_a_model_without_licensed_types_is_always_applicable(self, tmp_path: Path) -> None:
        """Nothing required, so nothing can be missing"""
        model = _model(tmp_path, with_supernet=False)
        card = build_model_card(model, build_model_preview(model.document, model.meta), MagicMock())

        assert not card[BestPracticeModelKey.REQUIRED_FEATURES.value]
        assert card[BestPracticeModelKey.APPLICABLE.value] is True


@pytest.mark.usefixtures('locked')
class TestTheDetails:
    """The card plus the texts, the tree and the relations"""

    def test_the_details_extend_the_card(self, tmp_path: Path) -> None:
        """Every card key stays, the texts are added"""
        model = _model(tmp_path)
        details = build_model_details(model, MagicMock())
        meta = model_meta()

        assert set(build_model_card(model, build_model_preview(model.document, model.meta), MagicMock())) <= set(
            details)
        assert (details[BestPracticeModelKey.DESCRIPTION.value], details[BestPracticeModelKey.SUITED_FOR.value],
                details[BestPracticeModelKey.PROFILES.value]) == (
                    meta[BestPracticeMetaKey.DESCRIPTION.value], meta[BestPracticeMetaKey.SUITED_FOR.value],
                    meta[BestPracticeMetaKey.PROFILES.value])

    def test_the_tree_names_every_reference_target(self, tmp_path: Path) -> None:
        """The category with its description, its types, the customer's employer field targeting the company"""
        details = build_model_details(_model(tmp_path), MagicMock())
        category = details[BestPracticeModelKey.CATEGORIES.value][0]
        customer = next(type_ for type_ in category[TYPES] if type_[NAME] == CUSTOMER_NAME)
        employer = next(field for field in customer[SECTIONS][0][FIELDS] if field[NAME] == EMPLOYER_FIELD)

        assert category[DESCRIPTION] == CONTACT_DESCRIPTION
        assert [type_[NAME] for type_ in category[TYPES]] == [COMPANY_NAME, CUSTOMER_NAME]
        assert employer[TARGETS] == (COMPANY_REF,)

    def test_the_uncategorized_types_and_the_relations(self, tmp_path: Path) -> None:
        """The Supernet no category holds; the relation with both sides"""
        details = build_model_details(_model(tmp_path), MagicMock())
        relation = details[BestPracticeModelKey.RELATIONS.value][0]

        assert [type_[NAME] for type_ in details[BestPracticeModelKey.UNCATEGORIZED.value]] == [SUPERNET_NAME]
        assert (relation[NAME], relation[PARENT_TYPES], relation[CHILD_TYPES]) == (
            RELATION_NAME, (COMPANY_REF,), (CUSTOMER_REF,))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  applying a model                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
IMPORTED: dict[str, int] = {'types': 3, 'categories': 1}
DECIDER_ID: int = 1


def test_every_required_feature_is_asked_through_the_licence_gate() -> None:
    """The gates' own 403, per feature, for the caller"""
    user = MagicMock()

    with patch(f'{HELPER_PATH}.abort_if_feature_locked') as gate:
        abort_if_model_unlicensed((IPAM,), user)
        abort_if_model_unlicensed((), user)

    assert gate.call_args_list == [call(LicenseFeature.IPAM, user)]


class TestApplyBestPracticeModel:
    """The licence, the import, then the recorded decision - in that order"""

    @pytest.fixture(name='steps')
    def fixture_steps(self) -> Any:
        """The gate, the import and the settings manager under one parent mock"""
        parent = MagicMock()
        parent.import_transfer_document.return_value = IMPORTED

        with patch(f'{HELPER_PATH}.abort_if_feature_locked', parent.abort_if_feature_locked), \
             patch(f'{HELPER_PATH}.import_transfer_document', parent.import_transfer_document), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=parent.settings_manager):
            yield parent

    @staticmethod
    def _user() -> MagicMock:
        """The administrator account"""
        user = MagicMock()
        user.get_public_id.return_value = DECIDER_ID

        return user

    def test_the_model_is_imported_then_recorded(self, tmp_path: Path, steps: MagicMock) -> None:
        """Licence first, the import on a copy of the file, the decision naming the model last"""
        model, user = _model(tmp_path), self._user()

        answer = apply_best_practice_model(model, user)

        assert [entry[0] for entry in steps.mock_calls] == [
            'abort_if_feature_locked', 'import_transfer_document', 'settings_manager.write']
        imported_document = steps.import_transfer_document.call_args.args[0]
        assert imported_document == model.document and imported_document is not model.document
        section, decision = steps.settings_manager.write.call_args.args
        assert section == START_ASSISTANT_SETTINGS_SECTION
        assert (decision[StartAssistantKey.DECISION.value], decision[StartAssistantKey.MODEL.value],
                decision[StartAssistantKey.DECIDED_BY.value]) == (
                    StartAssistantDecision.BEST_PRACTICE_MODEL.value, MODEL_ID, DECIDER_ID)
        assert answer == {BestPracticeApplyKey.MODEL_ID.value: MODEL_ID, BestPracticeApplyKey.IMPORTED.value: IMPORTED,
                          BestPracticeApplyKey.DECISION.value: decision}

    def test_the_catalogue_keeps_its_document_whatever_the_import_does(self, tmp_path: Path,
                                                                       steps: MagicMock) -> None:
        """The import may change what it is handed; the cached model stays as loaded"""
        model = _model(tmp_path)
        loaded = deepcopy(model.document)
        steps.import_transfer_document.side_effect = lambda document, _user: document.clear() or IMPORTED

        apply_best_practice_model(model, self._user())

        assert model.document == loaded

    def test_an_unlicensed_model_is_neither_imported_nor_recorded(self, tmp_path: Path, steps: MagicMock) -> None:
        """The 403 stops it before anything is read or written"""
        steps.abort_if_feature_locked.side_effect = Forbidden()

        with pytest.raises(Forbidden):
            apply_best_practice_model(_model(tmp_path), self._user())

        steps.import_transfer_document.assert_not_called()
        steps.settings_manager.write.assert_not_called()

    def test_a_refused_import_records_nothing(self, tmp_path: Path, steps: MagicMock) -> None:
        """A system that is not reset, a file the import refuses: no decision"""
        steps.import_transfer_document.side_effect = Forbidden()

        with pytest.raises(Forbidden):
            apply_best_practice_model(_model(tmp_path), self._user())

        steps.settings_manager.write.assert_not_called()

    def test_a_model_without_licensed_types_asks_no_licence(self, tmp_path: Path, steps: MagicMock) -> None:
        """Nothing required, nothing asked"""
        apply_best_practice_model(_model(tmp_path, with_supernet=False), self._user())

        steps.abort_if_feature_locked.assert_not_called()
