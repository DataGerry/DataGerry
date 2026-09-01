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
Implementation of all API routes for Isms Imports

One route, ``POST /isms/importer/<target>``, imports IsmsThreats, IsmsVulnerabilities, IsmsRisks or
IsmsControlMeasures from a CSV upload. Each target has its own handler; they share the same three
phases, in this order:

1. **read + validate** every row on its own. A row that breaks a rule is collected in
   ``invalid_objects`` and takes no further part - nothing about it is written, not even the
   referenced master data it mentions. A row that is short (fewer cells than the header) is a normal
   invalid row, not a failed import.
2. **resolve the references of the surviving rows in batches**: the distinct
   CmdbExtendableOption values / IsmsThreat / IsmsVulnerability / IsmsProtectionGoal names are looked
   up with one query per collection, and the ones that do not exist yet are created. Creating missing
   master data by name is intended behaviour - but only for rows that are actually being imported.
3. **insert what is new**. "Already existing" means a stored document that matches the candidate in
   **every** field the import writes (whole-row equality, by design): a row differing only in its
   description is a new entity, not a duplicate.

The result dict reports ``total_rows`` (data rows read), ``imported_objects`` (rows accepted for
import = created + existing), ``created_objects``, ``existing_objects`` and ``invalid_objects``.
"""
import io
from csv import DictReader, Sniffer, Error
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException
from werkzeug.datastructures import FileStorage

from cmdb.manager import (
    ThreatManager,
    ExtendableOptionsManager,
    VulnerabilityManager,
    RiskManager,
    ControlMeasureManager,
    ProtectionGoalManager,
)
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsImportType, ControlMeasureType, RiskType
from cmdb.models.extendable_option_model import OptionType
from cmdb.utils import parse_import_bool

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

isms_importer_blueprint = APIBlueprint('isms_importer', __name__)

REQUEST_FILE = "file"

# Encoding of an uploaded CSV. 'utf-8-sig' so a file saved by Excel (which prefixes a BOM) does not
# turn its first header into '\ufeffname' and get reported as a missing header
CSV_ENCODING: str = 'utf-8-sig'

# Header sets each target requires; also the contract with the CSV templates offered in the frontend
THREAT_HEADERS: set[str] = {"name", "source", "identifier", "description"}
VULNERABILITY_HEADERS: set[str] = {"name", "source", "identifier", "description"}
RISK_HEADERS: set[str] = {
    "name",
    "risk_type",
    "protection_goals",
    "threats",
    "vulnerabilities",
    "identifier",
    "consequences",
    "description",
}
CONTROL_MEASURE_HEADERS: set[str] = {
    "title",
    "control_measure_type",
    "source",
    "implementation_state",
    "identifier",
    "chapter",
    "description",
    "is_applicable",
    "reason",
}

# Keys of the per-target result dict
RESULT_TOTAL_ROWS: str = 'total_rows'
RESULT_IMPORTED: str = 'imported_objects'
RESULT_CREATED: str = 'created_objects'
RESULT_EXISTING: str = 'existing_objects'
RESULT_INVALID: str = 'invalid_objects'

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@isms_importer_blueprint.route('/<string:target>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_importer_blueprint.protect(auth=True, right='base.isms.import.add')
def import_isms_objects(target: str, request_user: CmdbUser) -> Response:
    """
    Import IsmsThreats, IsmsMeasureControls, IsmsVulnerabilities and IsmsRisks

    Args:
        target (str): The ISMS object which should be imported (see IsmsImportType)
        request_user (CmdbUser): CmdbUser requesting the import
    """
    try:
        if not IsmsImportType.is_valid(target):
            abort(400, f"'{target}' is not a valid ImportType for ISMS!")

        if REQUEST_FILE not in request.files:
            LOGGER.error("[import_isms_objects] No import file!")
            abort(400, "No import file was provided!")

        csv_file: FileStorage = request.files.get(REQUEST_FILE)

        target_enum = IsmsImportType(target)
        results = handle_isms_import(csv_file, target_enum, request_user)

        return DefaultResponse(results).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[import_isms_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while trying to import ISMS Objects!")

# -------------------------------------------------- ISMS Importers -------------------------------------------------- #

def handle_isms_import(csv_file: FileStorage, target: IsmsImportType, request_user: CmdbUser) -> dict:
    """
    Selects the handler for the provided csv file and starts the import workflow for it

    Args:
        csv_file (FileStorage): The file containing the data which should be imported
        target (IsmsImportType): The ISMS object which should be imported (see IsmsImportType)
        request_user (CmdbUser): CmdbUser requesting the import

    Returns:
        dict: The results of the import
    """
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(ManagerType.EXTENDABLE_OPTIONS,
                                                                                       request_user)

    handlers = {
        IsmsImportType.THREAT: handle_threats_import,
        IsmsImportType.VULNERABILITY: handle_vulnerabilities_import,
        IsmsImportType.RISK: handle_risks_import,
        IsmsImportType.CONTROL_MEASURE: handle_control_measures_import,
    }

    handler = handlers.get(target)

    if not handler:
        abort(400, f"No handler implemented for target: {target}!")

    if target == IsmsImportType.RISK:
        return handler(csv_file, request_user)

    return handler(csv_file, request_user, extendable_options_manager)


def import_threat_like_entities(
        csv_file: FileStorage,
        expected_headers: set[str],
        manager: GenericManager,
        extendable_options_manager: ExtendableOptionsManager) -> dict:
    """
    Imports IsmsThreats or IsmsVulnerabilities - identical CSV shape, identical rules

    Both carry name / source / identifier / description, require a name, and resolve 'source' to a
    CmdbExtendableOption of the THREAT_VULNERABILITY type. Rows are validated first, so a nameless row
    does not create the option it mentions

    Args:
        csv_file (FileStorage): The uploaded CSV
        expected_headers (set[str]): The headers the file must carry
        manager (GenericManager): ThreatManager or VulnerabilityManager
        extendable_options_manager (ExtendableOptionsManager): Manager for CmdbExtendableOptions

    Returns:
        dict: The import result (see build_import_result)
    """
    reader = read_csv_file(csv_file, expected_headers)

    total_rows = 0
    invalid_rows: list[dict] = []
    accepted_rows: list[dict] = []

    for row in reader:
        total_rows += 1
        candidate = {
            "name": stripped_cell(row, "name"),
            "source": stripped_cell(row, "source"),
            "identifier": stripped_cell(row, "identifier"),
            "description": stripped_cell(row, "description"),
        }

        # 'name' is the only required field
        if not candidate["name"]:
            invalid_rows.append(candidate)
            continue

        accepted_rows.append(candidate)

    # Only now, for the rows that are really being imported, are the referenced options resolved
    source_ids = resolve_extendable_options(
        {row["source"] for row in accepted_rows if row["source"]},
        extendable_options_manager,
        OptionType.THREAT_VULNERABILITY,
    )

    for candidate in accepted_rows:
        candidate["source"] = source_ids.get(candidate["source"]) if candidate["source"] else None

    created, existing = insert_new_items(accepted_rows, manager, "name")

    return build_import_result(total_rows, created, existing, invalid_rows)


def handle_threats_import(
        csv_file: FileStorage,
        request_user: CmdbUser,
        extendable_options_manager: ExtendableOptionsManager) -> dict:
    """
    Handles the import of IsmsThreats

    Args:
        csv_file (FileStorage): The file containing the data which should be imported
        request_user (CmdbUser): CmdbUser requesting the import
        extendable_options_manager (ExtendableOptionsManager): Manager for CmdbExtendableOptions

    Returns:
        dict: Results of IsmsThreat imports
    """
    threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

    return import_threat_like_entities(csv_file, THREAT_HEADERS, threat_manager, extendable_options_manager)


def handle_vulnerabilities_import(
        csv_file: FileStorage,
        request_user: CmdbUser,
        extendable_options_manager: ExtendableOptionsManager) -> dict:
    """
    Handles the import of IsmsVulnerabilities

    Args:
        csv_file (FileStorage): The file containing the data which should be imported
        request_user (CmdbUser): CmdbUser requesting the import
        extendable_options_manager (ExtendableOptionsManager): Manager for CmdbExtendableOptions

    Returns:
        dict: Results of IsmsVulnerabilities imports
    """
    vulnerability_manager: VulnerabilityManager = ManagerProvider.get_manager(ManagerType.VULNERABILITY, request_user)

    return import_threat_like_entities(
        csv_file, VULNERABILITY_HEADERS, vulnerability_manager, extendable_options_manager,
    )


def risk_row_is_valid(risk_type: str, consequences: str | None, description: str | None,
                      threats: list[str], vulnerabilities: list[str]) -> bool:
    """
    Reports whether one risk row satisfies the rules of its RiskType

    THREAT_X_VULNERABILITY needs threats AND vulnerabilities and no consequences; THREAT needs threats
    and neither vulnerabilities nor consequences; EVENT needs consequences and a description and
    neither threats nor vulnerabilities. An unknown RiskType is invalid

    Args:
        risk_type (str): The normalised RiskType value of the row
        consequences (str | None): The row's consequences cell
        description (str | None): The row's description cell
        threats (list[str]): The threat names the row references
        vulnerabilities (list[str]): The vulnerability names the row references

    Returns:
        bool: True when the row satisfies its RiskType's rules
    """
    if not RiskType.is_valid(risk_type):
        return False

    if risk_type == RiskType.THREAT_X_VULNERABILITY:
        return not consequences and bool(threats) and bool(vulnerabilities)

    if risk_type == RiskType.THREAT:
        return not consequences and not vulnerabilities and bool(threats)

    if risk_type == RiskType.EVENT:
        return bool(consequences) and bool(description) and not vulnerabilities and not threats

    return True


def read_risk_rows(csv_file: FileStorage) -> tuple[int, list[dict], list[dict]]:
    """
    Reads and validates every risk row, without touching the database

    Args:
        csv_file (FileStorage): The uploaded CSV

    Returns:
        tuple[int, list[dict], list[dict]]: (rows read, accepted candidates, rejected rows). The
            accepted candidates still carry their references as NAMES
    """
    reader = read_csv_file(csv_file, RISK_HEADERS)

    total_rows = 0
    invalid_rows: list[dict] = []
    accepted_rows: list[dict] = []

    for row in reader:
        total_rows += 1
        risk_type = (stripped_cell(row, "risk_type") or '').upper()
        consequences = stripped_cell(row, "consequences")
        description = stripped_cell(row, "description")
        threats = parse_list_of_strings("threats", row)
        vulnerabilities = parse_list_of_strings("vulnerabilities", row)
        protection_goals = parse_list_of_strings("protection_goals", row)

        candidate = {
            "name": stripped_cell(row, "name"),
            "risk_type": risk_type,
            "identifier": stripped_cell(row, "identifier"),
            "protection_goals": protection_goals,
            "threats": threats,
            "vulnerabilities": vulnerabilities,
            "consequences": consequences,
            "description": description,
        }

        if not candidate["name"] or not risk_row_is_valid(
            risk_type, consequences, description, threats, vulnerabilities,
        ):
            # Reported with the raw names, so the caller sees what the row actually said
            invalid_rows.append(candidate)
            continue

        accepted_rows.append(candidate)

    return total_rows, accepted_rows, invalid_rows


def resolve_risk_references(accepted_rows: list[dict], request_user: CmdbUser) -> None:
    """
    Replaces the threat / vulnerability / protection-goal NAMES of the accepted rows with public_ids

    One query per referenced collection resolves the whole batch, and a name nobody knows yet becomes a
    new (non-predefined) entity. Runs only for rows that are actually being imported, so a rejected row
    never leaves master data behind. The rows are updated in place

    Args:
        accepted_rows (list[dict]): The validated risk candidates, references still as names
        request_user (CmdbUser): CmdbUser requesting the import (manager scoping)
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(ManagerType.PROTECTION_GOAL,
                                                                                request_user)
    threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)
    vulnerability_manager: VulnerabilityManager = ManagerProvider.get_manager(ManagerType.VULNERABILITY,
                                                                             request_user)

    bare_entity_defaults = {"source": None, "identifier": None, "description": None}
    threat_ids = resolve_named_items(
        {name for row in accepted_rows for name in row["threats"]}, threat_manager, bare_entity_defaults,
    )
    vulnerability_ids = resolve_named_items(
        {name for row in accepted_rows for name in row["vulnerabilities"]},
        vulnerability_manager,
        bare_entity_defaults,
    )
    protection_goal_ids = resolve_named_items(
        {name for row in accepted_rows for name in row["protection_goals"]},
        protection_goal_manager,
        {"predefined": False},
    )

    for candidate in accepted_rows:
        candidate["threats"] = [threat_ids[name] for name in candidate["threats"]]
        candidate["vulnerabilities"] = [vulnerability_ids[name] for name in candidate["vulnerabilities"]]
        candidate["protection_goals"] = [protection_goal_ids[name] for name in candidate["protection_goals"]]


def handle_risks_import(csv_file: FileStorage, request_user: CmdbUser) -> dict:
    """
    Handles the import of IsmsRisks

    A risk references its IsmsThreats / IsmsVulnerabilities / IsmsProtectionGoals **by name**; the
    names are resolved to public_ids after validation, and a name nobody knows yet becomes a new
    entity - so a rejected row never creates one

    Args:
        csv_file (FileStorage): The file containing the data which should be imported
        request_user (CmdbUser): CmdbUser requesting the import

    Returns:
        dict: Results of IsmsRisks imports
    """
    total_rows, accepted_rows, invalid_rows = read_risk_rows(csv_file)

    resolve_risk_references(accepted_rows, request_user)

    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)
    created, existing = insert_new_items(accepted_rows, risk_manager, "name")

    return build_import_result(total_rows, created, existing, invalid_rows)


def read_control_measure_rows(csv_file: FileStorage) -> tuple[int, list[dict], list[dict]]:
    """
    Reads and validates every control-measure row, without touching the database

    An 'is_applicable' cell that carries an unrecognised value rejects the row; an empty cell keeps the
    historical default of False

    Args:
        csv_file (FileStorage): The uploaded CSV

    Returns:
        tuple[int, list[dict], list[dict]]: (rows read, accepted candidates, rejected rows). The
            accepted candidates still carry 'source' / 'implementation_state' as raw strings
    """
    reader = read_csv_file(csv_file, CONTROL_MEASURE_HEADERS)

    total_rows = 0
    invalid_rows: list[dict] = []
    accepted_rows: list[dict] = []

    for row in reader:
        total_rows += 1
        control_measure_type = (stripped_cell(row, "control_measure_type") or '').upper()
        raw_is_applicable = stripped_cell(row, "is_applicable")
        # An empty cell keeps the historical default (False); a value that means nothing is a reject
        is_applicable = False if raw_is_applicable is None else parse_import_bool(raw_is_applicable)

        candidate = {
            "title": stripped_cell(row, "title"),
            "control_measure_type": control_measure_type,
            "source": stripped_cell(row, "source"),
            "implementation_state": stripped_cell(row, "implementation_state"),
            "identifier": stripped_cell(row, "identifier"),
            "chapter": stripped_cell(row, "chapter"),
            "description": stripped_cell(row, "description"),
            "is_applicable": is_applicable,
            "reason": stripped_cell(row, "reason"),
        }

        if (not candidate["title"]
                or not ControlMeasureType.is_valid(control_measure_type)
                or is_applicable is None):
            invalid_rows.append(candidate)
            continue

        accepted_rows.append(candidate)

    return total_rows, accepted_rows, invalid_rows


def handle_control_measures_import(
        csv_file: FileStorage,
        request_user: CmdbUser,
        extendable_options_manager: ExtendableOptionsManager) -> dict:
    """
    Handles the import of IsmsControlMeasures

    'source' and 'implementation_state' are resolved to CmdbExtendableOptions after validation, so a
    row rejected for a missing title or an unknown ControlMeasureType creates neither

    Args:
        csv_file (FileStorage): The file containing the data which should be imported
        request_user (CmdbUser): CmdbUser requesting the import
        extendable_options_manager (ExtendableOptionsManager): Manager for CmdbExtendableOptions

    Returns:
        dict: Results of IsmsControlMeasures imports
    """
    total_rows, accepted_rows, invalid_rows = read_control_measure_rows(csv_file)

    source_ids = resolve_extendable_options(
        {row["source"] for row in accepted_rows if row["source"]},
        extendable_options_manager,
        OptionType.CONTROL_MEASURE,
    )
    implementation_state_ids = resolve_extendable_options(
        {row["implementation_state"] for row in accepted_rows if row["implementation_state"]},
        extendable_options_manager,
        OptionType.IMPLEMENTATION_STATE,
    )

    for candidate in accepted_rows:
        candidate["source"] = source_ids.get(candidate["source"]) if candidate["source"] else None
        candidate["implementation_state"] = (
            implementation_state_ids.get(candidate["implementation_state"])
            if candidate["implementation_state"] else None
        )

    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                request_user)
    created, existing = insert_new_items(accepted_rows, control_measure_manager, "title")

    return build_import_result(total_rows, created, existing, invalid_rows)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def stripped_cell(row: dict, field: str) -> str | None:
    """
    Reads one CSV cell as a stripped string, tolerating a missing or short row

    ``DictReader`` fills the trailing cells of a row that carries fewer values than the header with
    None, so a bare ``row[field].strip()`` raises AttributeError and would take the whole import down
    with a 500. This returns None for an absent, empty or whitespace-only cell instead

    Args:
        row (dict): The CSV row
        field (str): The column to read

    Returns:
        str | None: The stripped value, or None when the cell is absent or empty
    """
    value = row.get(field)

    if value is None:
        return None

    stripped_value = str(value).strip()

    return stripped_value or None


def resolve_extendable_options(
        values: set[str],
        extendable_options_manager: ExtendableOptionsManager,
        option_type: OptionType) -> dict[str, int]:
    """
    Maps CmdbExtendableOption values to their public_ids, creating the ones that do not exist yet

    One query resolves every value of the batch instead of one query per row; only the genuinely new
    values cost an insert. Called once per import, after the rows have been validated, so a rejected
    row never leaves an option behind

    Args:
        values (set[str]): The distinct option values referenced by the rows being imported
        extendable_options_manager (ExtendableOptionsManager): Manager for CmdbExtendableOptions
        option_type (OptionType): The OptionType the values belong to

    Returns:
        dict[str, int]: {option value: public_id of the existing or created CmdbExtendableOption}
    """
    if not values:
        return {}

    existing_options: list[dict] = extendable_options_manager.find(
        criteria={'value': {'$in': sorted(values)}, 'option_type': option_type},
    )
    resolved: dict[str, int] = {
        option['value']: option['public_id'] for option in existing_options if option.get('value')
    }

    for value in sorted(values - set(resolved)):
        resolved[value] = extendable_options_manager.insert_item({
            'value': value,
            'option_type': option_type,
            'predefined': False,
        })

    return resolved


def resolve_named_items(
        names: set[str],
        manager: GenericManager,
        new_item_defaults: dict) -> dict[str, int]:
    """
    Maps ISMS entity names to their public_ids, creating the ones that do not exist yet

    Shared by the IsmsThreat / IsmsVulnerability / IsmsProtectionGoal resolution a risk import needs:
    the risk CSV references them by name, and a name nobody knows yet becomes a new (non-predefined)
    entity. One query per collection resolves the whole batch

    Args:
        names (set[str]): The distinct names referenced by the rows being imported
        manager (GenericManager): Manager of the referenced ISMS entity
        new_item_defaults (dict): The document to insert for a missing name, minus its 'name'

    Returns:
        dict[str, int]: {name: public_id of the existing or created entity}
    """
    if not names:
        return {}

    existing_items: list[dict] = manager.find(criteria={'name': {'$in': sorted(names)}})
    resolved: dict[str, int] = {item['name']: item['public_id'] for item in existing_items if item.get('name')}

    for name in sorted(names - set(resolved)):
        resolved[name] = manager.insert_item({'name': name, **new_item_defaults})

    return resolved


def insert_new_items(candidates: list[dict], manager: GenericManager, identity_field: str) -> tuple[int, int]:
    """
    Inserts the candidates that are not stored yet and counts the ones that already are

    "Already stored" is whole-row equality on the fields the import writes (by design - a row that
    differs only in one field is a new entity). The candidates' identity values are resolved in ONE
    query; the stored documents carrying such a value are then compared field by field, so the check
    costs one query per import instead of one per row

    Args:
        candidates (list[dict]): The documents to import (already validated and reference-resolved)
        manager (GenericManager): Manager of the ISMS entity being imported
        identity_field (str): The field whose value pre-selects the comparison candidates ('name' /
            'title')

    Returns:
        tuple[int, int]: (created count, already existing count)
    """
    if not candidates:
        return 0, 0

    identity_values: set[str] = {
        candidate[identity_field] for candidate in candidates if candidate.get(identity_field)
    }
    stored_by_identity: dict[str, list[dict]] = {}

    for stored_item in manager.find(criteria={identity_field: {'$in': sorted(identity_values)}}):
        stored_by_identity.setdefault(stored_item.get(identity_field), []).append(stored_item)

    created_count = 0
    existing_count = 0

    for candidate in candidates:
        already_stored = any(
            all(stored_item.get(key) == value for key, value in candidate.items())
            for stored_item in stored_by_identity.get(candidate.get(identity_field), [])
        )

        if already_stored:
            existing_count += 1
            continue

        manager.insert_item(candidate)
        created_count += 1

    return created_count, existing_count


def build_import_result(total_rows: int, created: int, existing: int, invalid: list[dict]) -> dict:
    """
    Builds the per-target result dict every ISMS importer returns

    Args:
        total_rows (int): Data rows read from the CSV (valid and invalid)
        created (int): Newly inserted entities
        existing (int): Rows whose entity was already stored
        invalid (list[dict]): The rejected rows, as far as they could be parsed

    Returns:
        dict: total_rows / imported_objects (= created + existing) / created_objects /
            existing_objects / invalid_objects
    """
    return {
        RESULT_TOTAL_ROWS: total_rows,
        RESULT_IMPORTED: created + existing,
        RESULT_CREATED: created,
        RESULT_EXISTING: existing,
        RESULT_INVALID: invalid,
    }



def read_csv_file(csv_file: FileStorage, expected_headers: set) -> DictReader:
    """
    Extracts the data from the given csv file and checks that all required headers are present

    The file is decoded as 'utf-8-sig', so a CSV saved by Excel (which writes a BOM) keeps a usable
    first header instead of being reported as missing it. A file that is not UTF-8 at all is the
    caller's problem, not a server error, and is answered with a 400. The delimiter is sniffed
    (',' / ';') with a fallback that tries both

    Args:
        csv_file (FileStorage): The csv-file containing the data
        expected_headers (set): The required headers in the csv-file

    Raises:
        werkzeug.exceptions.BadRequest: 400 when the file is not UTF-8, when no delimiter can be
            determined, or when a required header is missing

    Returns:
        DictReader: The extracted data
    """
    try:
        decoded_file = csv_file.stream.read().decode(CSV_ENCODING)
    except UnicodeDecodeError:
        abort(400, f"The CSV file could not be decoded - it has to be {CSV_ENCODING.upper()} encoded!")

    stream = io.StringIO(decoded_file)

    # Read a sample for sniffing
    sample = stream.read(1024)
    stream.seek(0)

    try:
        dialect = Sniffer().sniff(sample, delimiters=";,")
        delimiter = dialect.delimiter
    except Error:
        dialect = None
        delimiter = None

    if delimiter is None:
        # Try semicolon first
        reader = DictReader(stream, delimiter=';')
        if len(reader.fieldnames or []) <= 1:
            # Probably not semicolon, try comma
            stream.seek(0)
            reader = DictReader(stream, delimiter=',')
            if len(reader.fieldnames or []) <= 1:
                abort(400, "Could not determine CSV delimiter or invalid CSV format.")
    else:
        # Sniffer succeeded, use detected dialect
        stream.seek(0)
        reader = DictReader(stream, dialect=dialect)

    # Validate headers
    file_headers = set(reader.fieldnames or [])
    missing_headers = expected_headers - file_headers

    if missing_headers:
        abort(400, f"The following required headers are missing in the CSV: {', '.join(missing_headers)}")

    return reader


def parse_list_of_strings(field: str, row: dict) -> list[str]:
    """
    Safely parses a CSV field expected to be a stringified list of strings

    Args:
        field (str): The CSV field name
        row (dict): The CSV row as a dict

    Returns:
        list[str]: Parsed list of strings
    """
    raw = row.get(field)

    if not raw:
        return []

    # Strip spaces and split by comma
    items = [item.strip() for item in raw.split(",") if item.strip()]

    return items
