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
Unit tests for ``start_assistant_routes.best_practice_helper`` - the cards, the details and a selection of models

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
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from cmdb.errors.database import DocumentUpdateError

from cmdb.framework.configuration_transfer import (
    BestPracticeCatalogue,
    BestPracticeModel,
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
    build_model_preview,
    load_catalogue,
)
from cmdb.framework.configuration_transfer.best_practice_catalogue import build_meta
from cmdb.framework.configuration_transfer.best_practice_constants import BestPracticeMetaKey, MODEL_PROBLEM
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.configuration_transfer.best_practice_preview import PreviewCounts
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import (
    abort_if_model_unlicensed,
    apply_best_practice_models,
    build_model_card,
    build_model_details,
    build_selection_preview,
    combine_selection,
    migrate_models,
    missing_features,
    read_model_selection,
    required_features_of,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    MODEL_NOT_FOUND_MESSAGE,
    SELECTION_CONFLICTS_MESSAGE,
    SELECTION_EMPTY_MESSAGE,
    SELECTION_NOT_IDS_MESSAGE,
    SELECTION_PAYLOAD_INVALID_MESSAGE,
    SELECTION_REPEATED_MESSAGE,
    START_ASSISTANT_SETTINGS_SECTION,
    BestPracticeApplyKey,
    BestPracticeModelKey,
    BestPracticeSelectionKey,
    StartAssistantDecision,
    StartAssistantKey,
)
from tests.utils.best_practice_model_fixture import (
    COMPANY_NAME,
    CONTACT_DESCRIPTION,
    CONTACT_NAME,
    CUSTOMER_NAME,
    EMPLOYER_FIELD,
    MODEL_DB_VERSION,
    RELATION_NAME,
    SUPERNET_NAME,
    SUPPLIER_NAME,
    model_document,
    model_meta,
    second_model_document,
    second_model_meta,
    write_model_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper'
MODEL_ID: str = 'fixture'
SECOND_MODEL_ID: str = 'second'
MODEL_IDS: str = BestPracticeSelectionKey.MODEL_IDS.value
TARGET_VERSION: int = MODEL_DB_VERSION
TOO_NEW: str = 'the file is newer than this installation'
IPAM: str = LicenseFeature.IPAM.value

# The detail tree's keys are the preview dataclasses' field names
NAME, LABEL, TYPES, SECTIONS, FIELDS = 'name', 'label', 'types', 'sections', 'fields'
DESCRIPTION, TARGETS, PARENT_TYPES, CHILD_TYPES = 'description', 'targets', 'parent_types', 'child_types'
COMPANY_REF: dict[str, str] = {NAME: COMPANY_NAME, LABEL: COMPANY_NAME}
CUSTOMER_REF: dict[str, str] = {NAME: CUSTOMER_NAME, LABEL: CUSTOMER_NAME}


def _model(tmp_path: Path, with_supernet: bool = True) -> BestPracticeModel:
    """The fixture model, read by the real catalogue"""
    write_model_file(tmp_path, MODEL_ID, document=model_document(with_supernet))

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
        """Texts from the meta section, numbers and chips from the rest of the model file"""
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


class TestReadModelSelection:
    """The body names offered models, each once; the answer is in card order"""

    @staticmethod
    def _catalogue(tmp_path: Path) -> BestPracticeCatalogue:
        """Both fixture models, the second ordered after the first"""
        _write_both(tmp_path)

        return load_catalogue(tmp_path)

    def test_the_models_in_card_order(self, tmp_path: Path) -> None:
        """Whatever order the body names them in"""
        models = read_model_selection({MODEL_IDS: [SECOND_MODEL_ID, MODEL_ID]}, self._catalogue(tmp_path))

        assert [model.model_id for model in models] == [MODEL_ID, SECOND_MODEL_ID]

    @pytest.mark.parametrize('body', [None, [], {}, {MODEL_IDS: [MODEL_ID], 'extra': 1}, {'model_id': MODEL_ID}],
                             ids=['none', 'list', 'empty-object', 'extra-key', 'wrong-key'])
    def test_a_body_that_is_not_the_one_key(self, tmp_path: Path, body: Any) -> None:
        """Exactly `model_ids`"""
        with pytest.raises(BadRequest) as refusal:
            read_model_selection(body, self._catalogue(tmp_path))

        assert refusal.value.description == SELECTION_PAYLOAD_INVALID_MESSAGE

    @pytest.mark.parametrize('value', [MODEL_ID, [MODEL_ID, 1], [None]], ids=['string', 'number', 'null'])
    def test_a_value_that_is_not_a_list_of_strings(self, tmp_path: Path, value: Any) -> None:
        """Named in the message"""
        with pytest.raises(BadRequest) as refusal:
            read_model_selection({MODEL_IDS: value}, self._catalogue(tmp_path))

        assert refusal.value.description == SELECTION_NOT_IDS_MESSAGE.format(values=value)

    def test_an_empty_list(self, tmp_path: Path) -> None:
        """At least one model"""
        with pytest.raises(BadRequest) as refusal:
            read_model_selection({MODEL_IDS: []}, self._catalogue(tmp_path))

        assert refusal.value.description == SELECTION_EMPTY_MESSAGE

    def test_a_repeated_id(self, tmp_path: Path) -> None:
        """Each model once"""
        with pytest.raises(BadRequest) as refusal:
            read_model_selection({MODEL_IDS: [MODEL_ID, SECOND_MODEL_ID, MODEL_ID]}, self._catalogue(tmp_path))

        assert refusal.value.description == SELECTION_REPEATED_MESSAGE.format(model_ids=[MODEL_ID])

    def test_an_unknown_id_is_a_404(self, tmp_path: Path) -> None:
        """The first unknown one is named"""
        with pytest.raises(NotFound) as refusal:
            read_model_selection({MODEL_IDS: [MODEL_ID, 'nope', 'gone']}, self._catalogue(tmp_path))

        assert refusal.value.description == MODEL_NOT_FOUND_MESSAGE.format(model_id='nope')


def test_the_required_features_are_every_models() -> None:
    """The union, sorted - one model needing IPAM is enough"""
    with_ipam = BestPracticeModel(MODEL_ID, build_meta(model_meta()), model_document())
    without = BestPracticeModel(SECOND_MODEL_ID, build_meta(second_model_meta()), second_model_document())

    assert required_features_of([without, with_ipam]) == (IPAM,)
    assert not required_features_of([without])


def _both(tmp_path: Path) -> list[BestPracticeModel]:
    """Both fixture models, read by the real catalogue, in card order"""
    _write_both(tmp_path)

    return list(load_catalogue(tmp_path).models)


def _write_both(tmp_path: Path) -> None:
    """Writes both fixture models"""
    write_model_file(tmp_path, MODEL_ID, document=model_document())
    write_model_file(tmp_path, SECOND_MODEL_ID, document=second_model_document(), meta=second_model_meta())


class TestMigrateModels:
    """Each model's file brought to the installation's version, on a copy"""

    def test_each_model_is_migrated_on_a_copy(self, tmp_path: Path) -> None:
        """The catalogue keeps its documents; the answer carries the migrated ones"""
        models = _both(tmp_path)
        migrated_documents = [{'migrated': model.model_id} for model in models]

        with patch(f'{HELPER_PATH}.migrate_to_version', side_effect=[(document, []) for document in
                                                                     migrated_documents]) as migrate:
            migrated, problems = migrate_models(models, TARGET_VERSION)

        assert [model.document for model in migrated] == migrated_documents and not problems
        assert [model.model_id for model in migrated] == [MODEL_ID, SECOND_MODEL_ID]
        for model, sent in zip(models, migrate.call_args_list):
            assert sent.args == (model.document, TARGET_VERSION) and sent.args[0] is not model.document

    def test_a_refused_file_is_named_with_its_model_and_left_out(self, tmp_path: Path) -> None:
        """A model exported by a newer DataGerry, say"""
        models = _both(tmp_path)

        with patch(f'{HELPER_PATH}.migrate_to_version', side_effect=[(None, [TOO_NEW]), ({}, [])]):
            migrated, problems = migrate_models(models, TARGET_VERSION)

        assert [model.model_id for model in migrated] == [SECOND_MODEL_ID]
        assert problems == [MODEL_PROBLEM.format(model_id=MODEL_ID, problem=TOO_NEW)]


@pytest.fixture(name='same_version')
def fixture_same_version() -> Any:
    """The installation's version read as the fixture's, every file answered as it is"""
    with patch(f'{HELPER_PATH}.read_target_version', return_value=TARGET_VERSION), \
         patch(f'{HELPER_PATH}.migrate_to_version', side_effect=lambda document, _version: (document, [])):
        yield


@pytest.mark.usefixtures('same_version')
class TestCombineSelection:
    """The selection migrated, then combined"""

    def test_the_models_are_combined(self, tmp_path: Path) -> None:
        """The shared company once"""
        combined = combine_selection(_both(tmp_path), MagicMock())

        assert combined.merged[TransferComponentName.TYPES.value] == (COMPANY_NAME,) and not combined.conflicts

    def test_a_refused_file_combines_nothing(self, tmp_path: Path) -> None:
        """Its problem is the only conflict; no file"""
        with patch(f'{HELPER_PATH}.migrate_to_version', side_effect=[(None, [TOO_NEW]), ({}, [])]):
            combined = combine_selection(_both(tmp_path), MagicMock())

        assert (combined.document, combined.conflicts, combined.merged) == (
            {}, (MODEL_PROBLEM.format(model_id=MODEL_ID, problem=TOO_NEW),), {})


@pytest.mark.usefixtures('same_version')
class TestBuildSelectionPreview:
    """What applying the selection would create, and what stands in its way"""

    @pytest.fixture(name='system')
    def fixture_system(self) -> Any:
        """The reset blockers, the import's judgement and the licence under one parent mock"""
        parent = MagicMock()
        parent.find_import_blockers.return_value = []
        parent.judge_transfer_document.return_value = (None, [])
        parent.feature_locked.return_value = False

        with patch(f'{HELPER_PATH}.find_import_blockers', parent.find_import_blockers), \
             patch(f'{HELPER_PATH}.judge_transfer_document', parent.judge_transfer_document), \
             patch(f'{HELPER_PATH}.feature_locked', parent.feature_locked), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager'):
            yield parent

    def test_an_applicable_selection(self, tmp_path: Path, system: MagicMock) -> None:
        """The combination's counts and labels; nothing in the way"""
        user = MagicMock()

        preview = build_selection_preview(_both(tmp_path), user)

        assert preview == {
            BestPracticeSelectionKey.MODEL_IDS.value: [MODEL_ID, SECOND_MODEL_ID],
            BestPracticeSelectionKey.COUNTS.value: asdict(PreviewCounts(categories=1, types=4, fields=5,
                                                                        relations=2)),
            BestPracticeSelectionKey.CATEGORY_LABELS.value: ['Contact'],
            BestPracticeSelectionKey.REQUIRED_FEATURES.value: [IPAM],
            BestPracticeSelectionKey.MISSING_FEATURES.value: [],
            BestPracticeSelectionKey.CONFLICTS.value: [],
            BestPracticeSelectionKey.MERGED.value: {TransferComponentName.TYPES.value: [COMPANY_NAME],
                                                    TransferComponentName.CATEGORIES.value: [CONTACT_NAME]},
            BestPracticeSelectionKey.PROBLEMS.value: [],
            BestPracticeSelectionKey.RESET_BLOCKERS.value: [],
            BestPracticeSelectionKey.APPLICABLE.value: True,
        }
        judged = system.judge_transfer_document.call_args.args
        assert judged[1:] == (user, TARGET_VERSION)
        assert len(judged[0][TransferFileKey.COMPONENTS.value][TransferComponentName.TYPES.value][
            TransferSectionKey.ITEMS.value]) == 4

    @pytest.mark.parametrize('key, setup', [
        (BestPracticeSelectionKey.MISSING_FEATURES, lambda system: setattr(system.feature_locked, 'return_value',
                                                                           True)),
        (BestPracticeSelectionKey.RESET_BLOCKERS, lambda system: setattr(system.find_import_blockers, 'return_value',
                                                                         ['framework.types'])),
        (BestPracticeSelectionKey.PROBLEMS, lambda system: setattr(system.judge_transfer_document, 'return_value',
                                                                   (None, ['a problem']))),
    ], ids=['licence', 'reset', 'import'])
    def test_each_obstacle_makes_it_not_applicable(self, tmp_path: Path, system: MagicMock,
                                                   key: BestPracticeSelectionKey, setup: Any) -> None:
        """Answered, and applicable false"""
        setup(system)

        preview = build_selection_preview(_both(tmp_path), MagicMock())

        assert preview[key.value] and preview[BestPracticeSelectionKey.APPLICABLE.value] is False

    def test_conflicts_skip_the_import_judgement(self, tmp_path: Path, system: MagicMock) -> None:
        """A file that cannot be combined is not judged"""
        write_model_file(tmp_path, MODEL_ID, document=model_document())
        write_model_file(tmp_path, SECOND_MODEL_ID, meta=second_model_meta(),
                         document=second_model_document(company_field_label='Company name'))

        preview = build_selection_preview(list(load_catalogue(tmp_path).models), MagicMock())

        assert len(preview[BestPracticeSelectionKey.CONFLICTS.value]) == 1
        assert preview[BestPracticeSelectionKey.APPLICABLE.value] is False
        system.judge_transfer_document.assert_not_called()


@pytest.mark.usefixtures('same_version')
class TestApplyBestPracticeModels:
    """The licence, the combination, the import, then the recorded decision - in that order"""

    @pytest.fixture(name='steps')
    def fixture_steps(self) -> Any:
        """The gate, the import and the settings manager under one parent mock - the import runs the final write on
        its ledger, as the real one does"""
        parent = MagicMock()
        parent.settings_manager.get_section.return_value = None

        def _import(_document: dict[str, Any], _user: Any, final_write: Any = None) -> dict[str, int]:
            parent.import_transfer_document(_document, _user, final_write=final_write)
            final_write(parent.ledger)
            return IMPORTED

        with patch(f'{HELPER_PATH}.abort_if_feature_locked', parent.abort_if_feature_locked), \
             patch(f'{HELPER_PATH}.import_transfer_document', side_effect=_import), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=parent.settings_manager):
            yield parent

    @staticmethod
    def _user() -> MagicMock:
        """The administrator account"""
        user = MagicMock()
        user.get_public_id.return_value = DECIDER_ID

        return user

    def test_the_combination_is_imported_then_recorded(self, tmp_path: Path, steps: MagicMock) -> None:
        """Licence first, the combined file imported, the decision naming the models as the import's last write"""
        answer = apply_best_practice_models(_both(tmp_path), self._user())

        assert [entry[0] for entry in steps.mock_calls] == [
            'abort_if_feature_locked', 'import_transfer_document', 'settings_manager.get_section',
            'ledger.compensated', 'settings_manager.write']
        imported_document = steps.import_transfer_document.call_args.args[0]
        assert [item[TypeSchemaKey.NAME.value] for item in imported_document[TransferFileKey.COMPONENTS.value][
            TransferComponentName.TYPES.value][TransferSectionKey.ITEMS.value]] == [
                COMPANY_NAME, CUSTOMER_NAME, SUPERNET_NAME, SUPPLIER_NAME]
        section, decision = steps.settings_manager.write.call_args.args
        assert section == START_ASSISTANT_SETTINGS_SECTION
        assert (decision[StartAssistantKey.DECISION.value], decision[StartAssistantKey.MODELS.value],
                decision[StartAssistantKey.DECIDED_BY.value]) == (
                    StartAssistantDecision.BEST_PRACTICE_MODEL.value, [MODEL_ID, SECOND_MODEL_ID], DECIDER_ID)
        assert answer == {BestPracticeApplyKey.MODEL_IDS.value: [MODEL_ID, SECOND_MODEL_ID],
                          BestPracticeApplyKey.IMPORTED.value: IMPORTED,
                          BestPracticeApplyKey.DECISION.value: decision}

    def test_the_catalogue_keeps_its_documents_whatever_the_import_does(self, tmp_path: Path,
                                                                        steps: MagicMock) -> None:
        """The import may change what it is handed; the cached models stay as loaded"""
        models = [_model(tmp_path)]
        loaded = deepcopy(models[0].document)
        steps.import_transfer_document.side_effect = lambda document, _user, **_kwargs: document.clear()

        apply_best_practice_models(models, self._user())

        assert models[0].document == loaded

    def test_a_failed_decision_write_fails_the_import(self, tmp_path: Path, steps: MagicMock) -> None:
        """Raised inside the import - whose ledger then undoes it - with nothing answered as applied"""
        failure = DocumentUpdateError('settings unavailable')
        steps.settings_manager.write.side_effect = failure

        with pytest.raises(DocumentUpdateError) as raised:
            apply_best_practice_models(_both(tmp_path), self._user())

        assert raised.value is failure
        steps.ledger.compensated.assert_called_once()

    def test_an_unlicensed_selection_is_neither_combined_imported_nor_recorded(
            self, tmp_path: Path, steps: MagicMock) -> None:
        """The 403 stops it before any file is migrated"""
        steps.abort_if_feature_locked.side_effect = Forbidden()

        with patch(f'{HELPER_PATH}.combine_selection') as combine, pytest.raises(Forbidden):
            apply_best_practice_models(_both(tmp_path), self._user())

        combine.assert_not_called()
        steps.import_transfer_document.assert_not_called()
        steps.settings_manager.write.assert_not_called()

    def test_conflicting_models_are_refused_with_every_conflict(self, tmp_path: Path, steps: MagicMock) -> None:
        """400 naming them; nothing imported, nothing recorded"""
        write_model_file(tmp_path, MODEL_ID, document=model_document())
        write_model_file(tmp_path, SECOND_MODEL_ID, meta=second_model_meta(),
                         document=second_model_document(company_field_label='Company name'))

        with pytest.raises(BadRequest) as refusal:
            apply_best_practice_models(list(load_catalogue(tmp_path).models), self._user())

        assert refusal.value.description.startswith(SELECTION_CONFLICTS_MESSAGE.format(conflicts=''))
        assert COMPANY_NAME in refusal.value.description
        steps.import_transfer_document.assert_not_called()
        steps.settings_manager.write.assert_not_called()

    def test_a_refused_import_records_nothing(self, tmp_path: Path, steps: MagicMock) -> None:
        """A system that is not reset, a file the import refuses: no decision"""
        steps.import_transfer_document.side_effect = Forbidden()

        with pytest.raises(Forbidden):
            apply_best_practice_models(_both(tmp_path), self._user())

        steps.settings_manager.write.assert_not_called()

    def test_a_selection_without_licensed_types_asks_no_licence(self, tmp_path: Path, steps: MagicMock) -> None:
        """Nothing required, nothing asked"""
        apply_best_practice_models([_model(tmp_path, with_supernet=False)], self._user())

        steps.abort_if_feature_locked.assert_not_called()
