#!/usr/bin/env python3
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
Generates the OpenCelium invoker definitions for DataGerry from the sources that already describe
the REST API, so the invokers cannot drift away from the API the way a hand-written XML does.

Three sources are combined, each used for what it alone knows:

    openapi.yaml            which routes are public API, whether a route exists in the Cloud
                            variant, the OnPremise variant or both, and the JSON schema of every
                            request body and of every payload that is returned unwrapped
    the route modules       the URL a route is really served under and which response class wraps
                            its payload - the OpenAPI paths are documentation and disagree with
                            the code in a handful of places (see ROUTE_ID_ALIASES)
    the response classes    the envelope each response class puts around the payload, including
                            the pager and pagination blocks that drive paging in OpenCelium

Run it after changing the REST API or the OpenAPI spec:

    python3 cmdb/open_celium/invokers/generate_invokers.py

It rewrites dg_invoker.xml and dg_cloud_invoker.xml in place and reports what changed. Import the
result into OpenCelium afterwards, it is not read by DataGerry at runtime.
"""
import argparse
import ast
import os
import sys
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       PATHS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
DOCS_ROOT = os.path.join(REPO_ROOT, 'cmdb', 'interface', 'docs', 'static')
OPENAPI_FILE = os.path.join(DOCS_ROOT, 'openapi.yaml')
ROUTES_ROOT = os.path.join(REPO_ROOT, 'cmdb', 'interface', 'rest_api', 'routes')
INIT_REST_API = os.path.join(REPO_ROOT, 'cmdb', 'interface', 'rest_api', 'init_rest_api.py')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     INVOKERS                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

DESCRIPTION = ("DATAGERRY is an Open Source CMDB &amp; Asset Management Tool, which completely leaves the definition "
               "of a data model to the user.")
DOCS_LINK = "https://docs.datagerry.com/en/latest/rest_api/overview.html"


@dataclass(frozen=True)
class Variant:
    """One invoker flavour: which deployment it targets and how it authenticates."""
    name: str
    file_name: str
    # File name this invoker has inside OpenCelium's invoker folder. Uploading under a different
    # name adds a second invoker declaring the same <name> instead of replacing the existing one.
    oc_file_name: str
    scope_tag: str
    # Whether this is the cloud deployment, where API-locked routes cannot be called at all.
    cloud: bool
    hint: str
    # Header items every request carries, as (name, value) pairs.
    headers: tuple[tuple[str, str], ...]
    required_data: tuple[str, ...]


COMMON_HEADERS = (("Authorization", "{token}"), ("Content-Type", "application/json"))

VARIANTS = (
    Variant(
        name="DataGerry",
        file_name="dg_invoker.xml",
        oc_file_name="datagerry.xml",
        scope_tag="OnPremise",
        cloud=False,
        hint=f"This interface provides a basic auth. Read here the api documentation {DOCS_LINK}",
        headers=COMMON_HEADERS,
        required_data=("url", "username", "password"),
    ),
    Variant(
        name="DataGerryCloud",
        file_name="dg_cloud_invoker.xml",
        oc_file_name="dg_cloud_invoker.xml",
        scope_tag="Cloud",
        cloud=True,
        # The cloud API additionally demands the subscription's API key on every call.
        hint=("This interface provides a basic auth and requires the x-api-key of the subscription. "
              f"Read here the api documentation {DOCS_LINK}"),
        headers=COMMON_HEADERS + (("x-api-key", "{x-api-key}"),),
        required_data=("url", "username", "password", "x-api-key"),
    ),
)

# The operation OpenCelium calls to verify a connector's credentials. Cheap and readable for everyone.
TEST_OPERATION_ID = 'get_cmdb_categories'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    PAGINATION                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

# Default query string put on every paginated collection route.
#
# OpenCelium has no separate element for query parameters: a method's parameters live in the query
# string of its endpoint, and the connection editor parses them back out into its own key/value
# editor. Declaring them here is therefore the only way they show up in OpenCelium at all - without
# them a connection silently reads the API default of 10 records and never sees page two.
#
# The values are literal rather than {placeholders}: OpenCelium substitutes placeholders only from
# requiredData, so an unbound one would be sent verbatim and make DataGerry answer 400.
#
# 'filter' is deliberately absent. An empty filter= is not valid JSON and DataGerry rejects the whole
# request, so a filter has to be added per connection - which is exactly what the connection editor
# is for. Note that limit=0 turns paging off and returns every record in one response.
PAGINATION_QUERY = (
    ("limit", "100"),
    ("page", "1"),
    ("sort", "public_id"),
    ("order", "1"),
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     NAMING                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

# Operation names already published in dg_cloud_invoker.xml.
#
# An OpenCelium connection stores the operation name, so renaming one breaks every connection built
# on it. These names are kept verbatim even where they break the naming convention below
# ('Update object'), and new operations follow the convention.
LEGACY_NAMES = {
    'insert_cmdb_category': 'Create new Category',
    'get_cmdb_categories': 'Get Categories',
    'get_cmdb_category': 'Get Category by public_id',
    'update_cmdb_category': 'Update Category by public_id',
    'delete_cmdb_category': 'Delete Category by public_id',
    'insert_cmdb_type': 'Create new Type',
    'get_cmdb_types': 'Get Types',
    'get_cmdb_type': 'Get Type by public_id',
    'count_objects_of_cmdb_type': 'Get Object count for Type',
    'update_cmdb_type': 'Update Type by public_id',
    'delete_cmdb_type': 'Delete Type by public_id',
    'insert_cmdb_object': 'Create new Object',
    'get_cmdb_object': 'Get Object by public_id',
    'get_native_cmdb_object': 'Get native Object by public_id',
    'get_cmdb_object_count': 'Get count of all Objects',
    'get_cmdb_object_state': 'Get Object state',
    'get_cmdb_objects': 'Get Objects',
    'get_cmdb_object_references': 'Get Object references',
    'update_cmdb_object_state': 'Update Object state',
    'update_cmdb_object': 'Update object',
    'delete_cmdb_object': 'Delete Object by public_id',
    'delete_many_cmdb_objects': 'Delete multiple Objects',
    'insert_cmdb_object_group': 'Create new ObjectGroup',
    'get_cmdb_object_groups': 'Get ObjectGroups',
    'get_cmdb_object_group': 'Get ObjectGroup by public_id',
    'update_cmdb_object_group': 'Update ObjectGroup by public_id',
    'delete_cmdb_object_group': 'Delete ObjectGroup by public_id',
    'create_section_template': 'Create new SectionTemplate',
    'get_all_section_templates': 'Get SectionTemplates',
    'get_section_template': 'Get SectionTemplate by public_id',
    'update_section_template': 'Update SectionTemplate by public_id',
    'delete_section_template': 'Delete SectionTemplate by public_id',
    'insert_cmdb_user': 'Create new User',
    'get_cmdb_users': 'Get Users',
    'get_cmdb_user': 'Get User by public_id',
    'insert_cmdb_user_group': 'Create new UserGroup',
    'get_cmdb_user_groups': 'Get UserGroups',
    'get_cmdb_user_group': 'Get UserGroup by public_id',
    'update_cmdb_user_group': 'Update UserGroup by public_id',
    'delete_cmdb_user_group': 'Delete UserGroup by public_id',
}

# Names for routes that are not plain CRUD and would get a misleading generated name.
SPECIAL_NAMES = {
    'change_cmdb_user_password': 'Change User password',
    'update_cmdb_location_for_object': 'Update Location for Object',
    'delete_cmdb_location_for_object': 'Delete Location for Object',
    'run_cmdb_report_query': 'Run Report by public_id',
    'update_multiple_isms_risk_classes': 'Update multiple ISMS RiskClasses',
    'update_multiple_isms_impact_categories': 'Update multiple ISMS ImpactCategories',
    'duplicate_isms_risk_assessment': 'Duplicate ISMS RiskAssessment',
}

# Singular / plural noun per OpenAPI tag, used to build the generated operation names.
TAG_NOUNS = {
    'Objects': ('Object', 'Objects'),
    'ObjectGroups': ('ObjectGroup', 'ObjectGroups'),
    'ObjectLinks': ('ObjectLink', 'ObjectLinks'),
    'Types': ('Type', 'Types'),
    'Categories': ('Category', 'Categories'),
    'Section Templates': ('SectionTemplate', 'SectionTemplates'),
    'Users': ('User', 'Users'),
    'UserGroups': ('UserGroup', 'UserGroups'),
    'Persons': ('Person', 'Persons'),
    'PersonGroups': ('PersonGroup', 'PersonGroups'),
    'Relations': ('Relation', 'Relations'),
    'ObjectRelations': ('ObjectRelation', 'ObjectRelations'),
    'Webhooks': ('Webhook', 'Webhooks'),
    'Reports': ('Report', 'Reports'),
    'ReportCategories': ('ReportCategory', 'ReportCategories'),
    'Locations': ('Location', 'Locations'),
    'ExtendableOptions': ('ExtendableOption', 'ExtendableOptions'),
    'ISMS-RiskClasses': ('ISMS RiskClass', 'ISMS RiskClasses'),
    'ISMS-Likelihoods': ('ISMS Likelihood', 'ISMS Likelihoods'),
    'ISMS-Impacts': ('ISMS Impact', 'ISMS Impacts'),
    'ISMS-ImpactCategories': ('ISMS ImpactCategory', 'ISMS ImpactCategories'),
    'ISMS-ProtectionGoals': ('ISMS ProtectionGoal', 'ISMS ProtectionGoals'),
    'ISMS-RiskMatrix': ('ISMS RiskMatrix', 'ISMS RiskMatrix'),
    'ISMS-Risks': ('ISMS Risk', 'ISMS Risks'),
    'ISMS-Threats': ('ISMS Threat', 'ISMS Threats'),
    'ISMS-Vulnerabilities': ('ISMS Vulnerability', 'ISMS Vulnerabilities'),
    'ISMS-Controls': ('ISMS Control', 'ISMS Controls'),
    'ISMS-RiskAssessments': ('ISMS RiskAssessment', 'ISMS RiskAssessments'),
    'ISMS-ControlAssignments': ('ISMS ControlAssignment', 'ISMS ControlAssignments'),
}

SCOPE_TAGS = ('Cloud', 'OnPremise')

# operationIds in the OpenAPI spec that do not match the name of the function serving the route.
ROUTE_ID_ALIASES = {
    'update_object': 'update_cmdb_object',
    'delete_object': 'delete_cmdb_object',
    'get_types': 'get_cmdb_types',
    'delete_type': 'delete_cmdb_type',
    'count_objects_of_type': 'count_objects_of_cmdb_type',
    'get_users': 'get_cmdb_users',
    'get_user': 'get_cmdb_user',
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SCHEMA -> FIELDS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

# How deep a schema is unfolded. Deeper nesting carries no information for a field mapping and only
# risks looping on a self-referencing schema.
MAX_FIELD_DEPTH = 6

JSON_TO_INVOKER_TYPE = {
    'string': 'string',
    'integer': 'integer',
    'number': 'integer',
    'boolean': 'boolean',
    'object': 'object',
    'array': 'array',
}


@dataclass
class Field:
    """One <field> element of an invoker body."""
    name: str
    type: str
    children: list["Field"] = dataclass_field(default_factory=list)


class SchemaResolver:
    """Loads the OpenAPI files and turns their schemas into invoker field trees."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def load(self, path: str) -> Any:
        """Reads a YAML file once and remembers it."""
        real = os.path.abspath(path)

        if real not in self._cache:
            with open(real, encoding='utf-8') as file:
                self._cache[real] = yaml.safe_load(file)

        return self._cache[real]

    def resolve(self, schema: Any, base_dir: str) -> tuple[Any, str]:
        """
        Follows a '$ref' until a real schema is reached.

        Returns:
            tuple[Any, str]: the schema and the directory its own refs are relative to
        """
        seen = 0

        while isinstance(schema, dict) and '$ref' in schema and seen < 20:
            target = os.path.join(base_dir, schema['$ref'].split('#')[0])
            base_dir = os.path.dirname(os.path.abspath(target))
            schema = self.load(target)
            seen += 1

        return schema, base_dir

    def to_fields(self, schema: Any, base_dir: str, depth: int = 0) -> list[Field]:
        """Builds the <field> children describing the properties of an object or array schema."""
        schema, base_dir = self.resolve(schema, base_dir)

        if not isinstance(schema, dict) or depth >= MAX_FIELD_DEPTH:
            return []

        if 'properties' in schema:
            return [self._field(name, sub, base_dir, depth)
                    for name, sub in schema['properties'].items()]

        if schema.get('type') == 'array':
            # An array's children describe one element, matching how OpenCelium renders a list.
            return self.to_fields(schema.get('items', {}), base_dir, depth)

        for branch in ('oneOf', 'anyOf', 'allOf'):
            if branch in schema and schema[branch]:
                return self.to_fields(schema[branch][0], base_dir, depth)

        return []

    def type_of(self, schema: Any, base_dir: str) -> str:
        """Maps a schema onto one of the types an invoker field can carry."""
        schema, _ = self.resolve(schema, base_dir)

        if not isinstance(schema, dict):
            return 'string'

        declared = schema.get('type')

        if declared in JSON_TO_INVOKER_TYPE:
            return JSON_TO_INVOKER_TYPE[declared]

        if 'properties' in schema:
            return 'object'

        for branch in ('oneOf', 'anyOf', 'allOf'):
            if branch in schema and schema[branch]:
                return self.type_of(schema[branch][0], base_dir)

        return 'string'

    def _field(self, name: str, schema: Any, base_dir: str, depth: int) -> Field:
        resolved, sub_dir = self.resolve(schema, base_dir)
        field_type = self.type_of(resolved, sub_dir)
        children = self.to_fields(resolved, sub_dir, depth + 1) if field_type in ('object', 'array') else []

        return Field(name, field_type, children)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RESPONSE ENVELOPES                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def _pagination_fields() -> list[Field]:
    """
    The paging block GetMultiResponse.export() adds to every collection response.

    'parameters' echoes the CollectionParameters the request was served with, 'pager' carries the
    page arithmetic and 'pagination' the ready-made URLs of the neighbouring pages - together they
    are what a connection needs to walk through more than the first page. All three are objects;
    declaring them as arrays (as the hand-written invoker did) shifts every path by an index and
    makes them unusable in a mapping.
    """
    return [
        Field('parameters', 'object', [
            Field('limit', 'integer'),
            Field('sort', 'string'),
            Field('order', 'integer'),
            Field('page', 'integer'),
            Field('filter', 'object'),
            Field('optional', 'object'),
            Field('projection', 'object'),
        ]),
        Field('pager', 'object', [
            Field('page', 'integer'),
            Field('page_size', 'integer'),
            Field('total_pages', 'integer'),
        ]),
        Field('pagination', 'object', [
            Field('current', 'string'),
            Field('first', 'string'),
            Field('prev', 'string'),
            Field('next', 'string'),
            Field('last', 'string'),
        ]),
    ]


def _base_fields() -> list[Field]:
    """The two keys BaseAPIResponse.export() appends to every envelope."""
    return [Field('response_type', 'string'), Field('time', 'string')]


def envelope(response_class: str, payload: list[Field]) -> tuple[str, list[Field]] | None:
    """
    Wraps a payload in the envelope its response class produces.

    Returns:
        tuple[str, list[Field]] | None: body type and fields, or None when the class is unknown
    """
    if response_class == 'GetMultiResponse':
        return 'object', [
            Field('results', 'array', payload),
            Field('count', 'integer'),
            Field('total', 'integer'),
            *_pagination_fields(),
            *_base_fields(),
        ]

    if response_class == 'GetListResponse':
        return 'object', [Field('results', 'array', payload), *_base_fields()]

    if response_class in ('GetSingleResponse', 'UpdateSingleResponse'):
        return 'object', [Field('result', 'object', payload), *_base_fields()]

    if response_class == 'InsertSingleResponse':
        return 'object', [Field('result_id', 'integer'), Field('raw', 'object', payload), *_base_fields()]

    if response_class == 'DeleteSingleResponse':
        return 'object', [Field('raw', 'object', payload), *_base_fields()]

    if response_class == 'UpdateMultiResponse':
        return 'object', [Field('results', 'array', payload), Field('failed', 'array'), *_base_fields()]

    return None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ROUTE ANALYSIS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

RESPONSE_CLASSES = (
    'GetMultiResponse', 'GetListResponse', 'GetSingleResponse', 'InsertSingleResponse',
    'UpdateSingleResponse', 'UpdateMultiResponse', 'DeleteSingleResponse', 'DefaultResponse',
)

# Response classes ranked by how specific they are. A handler may build more than one - the state
# route answers with a DefaultResponse only on the "nothing changed" path - and the envelope of the
# richer one is what a mapping should see.
RESPONSE_PRIORITY = {name: index for index, name in enumerate(RESPONSE_CLASSES)}


@dataclass
class Route:
    """A REST route as the code actually serves it."""
    function: str
    url: str
    methods: list[str]
    response_class: str | None
    paginated: bool
    # Value of verify_api_access(required_api_level=...); 'LOCKED' means UI-only in cloud mode.
    api_level: str | None


PARAMETERS_ROOT = os.path.join(REPO_ROOT, 'cmdb', 'interface', 'rest_api', 'responses',
                               'response_parameters')


def paginating_parameter_classes() -> set[str]:
    """
    Names of the parameter classes that carry limit/page/sort/order.

    Handlers declare their query parameters through a decorator, and only the CollectionParameters
    family means paging - GroupDeletionParameters, for instance, takes a reassignment target and
    would otherwise have every DELETE dressed up with a page number.
    """
    found = {'CollectionParameters'}

    for file_name in sorted(os.listdir(PARAMETERS_ROOT)):
        if not file_name.endswith('.py'):
            continue

        with open(os.path.join(PARAMETERS_ROOT, file_name), encoding='utf-8') as file:
            tree = ast.parse(file.read())

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                    isinstance(base, ast.Name) and base.id in found for base in node.bases):
                found.add(node.name)

    return found


def _decorator_parts(node: ast.expr) -> tuple[str, str | None, list[ast.expr], dict[str, ast.expr]] | None:
    """Splits a decorator call into name, owner variable, positional args and keywords."""
    if not isinstance(node, ast.Call):
        return None

    if isinstance(node.func, ast.Attribute):
        name, owner = node.func.attr, node.func.value.id if isinstance(node.func.value, ast.Name) else None
    elif isinstance(node.func, ast.Name):
        name, owner = node.func.id, None
    else:
        return None

    return name, owner, list(node.args), {kw.arg: kw.value for kw in node.keywords}


def blueprint_prefixes() -> dict[str, str]:
    """
    Reads the url_prefix of every blueprint that init_rest_api actually registers.

    A blueprint missing from the result is not reachable, so its routes are left out of the
    invokers even when the OpenAPI spec still documents them.
    """
    with open(INIT_REST_API, encoding='utf-8') as file:
        tree = ast.parse(file.read())

    prefixes: dict[str, str] = {}

    for node in ast.walk(tree):
        parts = _decorator_parts(node)

        if not parts or parts[0] != 'register_blueprint' or not parts[2]:
            continue

        target = parts[2][0]

        if not isinstance(target, ast.Name):
            continue

        prefix = parts[3].get('url_prefix')
        prefixes[target.id] = prefix.value if isinstance(prefix, ast.Constant) else ''

    return prefixes


def _rule_to_endpoint(rule: str) -> str:
    """Turns a Flask rule into an OpenCelium endpoint path: '/<int:public_id>' -> '/{public_id}'."""
    out = []

    for part in rule.split('/'):
        if part.startswith('<') and part.endswith('>'):
            out.append('{' + part[1:-1].split(':')[-1] + '}')
        else:
            out.append(part)

    return '/'.join(out)


def analyze_routes() -> dict[str, Route]:
    """Collects every reachable REST route, keyed by the name of the function serving it."""
    prefixes = blueprint_prefixes()
    paging_classes = paginating_parameter_classes()
    routes: dict[str, Route] = {}

    for dir_path, _dirs, files in os.walk(ROUTES_ROOT):
        if '__pycache__' in dir_path:
            continue

        for file_name in sorted(files):
            if not file_name.endswith('.py'):
                continue

            with open(os.path.join(dir_path, file_name), encoding='utf-8') as file:
                tree = ast.parse(file.read())

            # Rules are sometimes held in a constant instead of written inline.
            constants = {node.targets[0].id: node.value.value
                         for node in tree.body
                         if isinstance(node, ast.Assign) and len(node.targets) == 1
                         and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
                         and isinstance(node.value.value, str)}
            constants.update(_imported_route_constants(tree, dir_path))

            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue

                route = _route_of(node, prefixes, constants, paging_classes)

                if route:
                    routes[route.function] = route

    return routes


def _imported_route_constants(tree: ast.Module, dir_path: str) -> dict[str, str]:
    """Loads string constants a route module imports from a sibling constants module."""
    found: dict[str, str] = {}

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue

        candidate = os.path.join(dir_path, node.module.split('.')[-1] + '.py')

        if not os.path.exists(candidate):
            continue

        with open(candidate, encoding='utf-8') as file:
            sub = ast.parse(file.read())

        for assign in sub.body:
            if isinstance(assign, ast.Assign) and len(assign.targets) == 1 \
                    and isinstance(assign.targets[0], ast.Name) and isinstance(assign.value, ast.Constant) \
                    and isinstance(assign.value.value, str):
                found[assign.targets[0].id] = assign.value.value

    return found


def _route_of(node: ast.FunctionDef,
              prefixes: dict[str, str],
              constants: dict[str, str],
              paging_classes: set[str]) -> Route | None:
    """Builds the Route a decorated handler serves, or None when it is not a reachable route."""
    rule: str | None = None
    methods: list[str] = []
    blueprint: str | None = None
    paginated = False
    api_level: str | None = None
    responses: list[str] = []

    for decorator in node.decorator_list:
        parts = _decorator_parts(decorator)

        if not parts:
            continue

        name, owner, args, keywords = parts

        if name == 'route':
            blueprint = owner

            if args and isinstance(args[0], ast.Constant):
                rule = args[0].value
            elif args and isinstance(args[0], ast.Name):
                rule = constants.get(args[0].id)

            declared = keywords.get('methods')

            if isinstance(declared, ast.List):
                methods = [item.value for item in declared.elts if isinstance(item, ast.Constant)]
        elif name == 'parse_collection_parameters':
            paginated = True
        elif name == 'parse_parameters':
            paginated = bool(args) and isinstance(args[0], ast.Name) and args[0].id in paging_classes
        elif name == 'verify_api_access':
            level = keywords.get('required_api_level') or (args[0] if args else None)

            if isinstance(level, ast.Attribute):
                api_level = level.attr

    if rule is None or blueprint not in prefixes:
        return None

    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in RESPONSE_CLASSES:
            responses.append(sub.func.id)

    response_class = min(responses, key=lambda name: RESPONSE_PRIORITY[name]) if responses else None
    url = _rule_to_endpoint(prefixes[blueprint] + rule)

    return Route(node.name, url, methods or ['GET'], response_class, paginated, api_level)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   OPENAPI SPEC                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass
class DocOperation:
    """One documented API operation."""
    path: str
    method: str
    operation_id: str
    tag: str
    scopes: list[str]
    request_schema: Any
    request_dir: str
    success_schema: Any
    success_dir: str
    entity_schema: Any
    entity_dir: str
    # Required query parameters other than the paging ones, as (name, default value) pairs.
    query_params: list[tuple[str, str]]


def entity_key(tag: str) -> str:
    """The components.schemas key holding the resource a tag is about ('ISMS-Risks' -> 'ISMS-Risk')."""
    singular = TAG_NOUNS.get(tag, (tag.rstrip('s'),))[0]
    return singular.replace(' ', '-')


def load_operations(resolver: SchemaResolver) -> list[DocOperation]:
    """Reads every operation the OpenAPI spec documents, in the order the spec lists them."""
    spec = resolver.load(OPENAPI_FILE)
    schemas = spec.get('components', {}).get('schemas', {})
    operations: list[DocOperation] = []

    for path, reference in spec['paths'].items():
        target = os.path.join(DOCS_ROOT, reference['$ref'])
        base_dir = os.path.dirname(os.path.abspath(target))
        document = resolver.load(target)

        for method in ('post', 'get', 'put', 'patch', 'delete'):
            if method not in document:
                continue

            operation = document[method]
            tags = operation.get('tags') or []
            tag = next((item for item in tags if item not in SCOPE_TAGS), '')
            request_schema = _content_schema(operation.get('requestBody'))
            success = operation.get('responses', {}).get('200') or operation.get('responses', {}).get(200)

            operations.append(DocOperation(
                path=path,
                method=method.upper(),
                operation_id=operation.get('operationId', ''),
                tag=tag,
                scopes=[item for item in tags if item in SCOPE_TAGS],
                request_schema=request_schema,
                request_dir=base_dir,
                success_schema=_content_schema(success),
                success_dir=base_dir,
                entity_schema=schemas.get(entity_key(tag)),
                entity_dir=DOCS_ROOT,
                query_params=_required_query_params(operation),
            ))

    return operations


def _required_query_params(operation: dict) -> list[tuple[str, str]]:
    """
    The query parameters a call cannot be made without, with the value to pre-fill.

    Optional ones are left out on purpose: OpenCelium sends whatever stands in the endpoint, and an
    empty view= or filter= is worse than no parameter at all. Required ones are declared with their
    documented default so they show up in the connection editor ready to be filled in.
    """
    found: list[tuple[str, str]] = []

    for parameter in operation.get('parameters') or []:
        if not isinstance(parameter, dict) or parameter.get('in') != 'query':
            continue

        name = parameter.get('name')

        # Paging is described as one pseudo parameter and is handled by PAGINATION_QUERY.
        if not parameter.get('required') or name in (None, 'CollectionParameters'):
            continue

        schema = parameter.get('schema') or {}
        value = schema.get('default', schema.get('example', ''))
        found.append((name, 'true' if value is True else 'false' if value is False else str(value)))

    return found


def _content_schema(node: Any) -> Any:
    """Digs the JSON schema out of an OpenAPI requestBody or response node."""
    if not isinstance(node, dict):
        return None

    content = node.get('content')

    if not isinstance(content, dict):
        return None

    for media in ('application/json', *content):
        if media in content and isinstance(content[media], dict):
            return content[media].get('schema')

    return None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  OPERATION NAMES                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def operation_name(doc: DocOperation, route: Route) -> str:
    """Names an operation, keeping every name that has already been published."""
    if route.function in LEGACY_NAMES:
        return LEGACY_NAMES[route.function]

    if route.function in SPECIAL_NAMES:
        return SPECIAL_NAMES[route.function]

    singular, plural = TAG_NOUNS.get(doc.tag, (doc.tag.rstrip('s') or doc.tag, doc.tag))
    is_collection = '{' not in doc.path.rsplit('/', 1)[-1]

    if doc.method == 'POST':
        return f"Create new {singular}"

    if doc.method == 'GET':
        return f"Get {plural}" if is_collection else f"Get {singular} by public_id"

    if doc.method in ('PUT', 'PATCH'):
        return f"Update {singular}" if is_collection else f"Update {singular} by public_id"

    if doc.method == 'DELETE':
        return f"Delete {singular}" if is_collection else f"Delete {singular} by public_id"

    return f"{doc.method.title()} {singular}"


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    RENDERING                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

RULE_WIDTH = 117


def escape(value: str) -> str:
    """Escapes the characters that may not appear literally in XML text or an attribute."""
    return (value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def banner(title: str, indent: str) -> list[str]:
    """Renders a centred comment banner in the style of the hand-written invoker."""
    inner = RULE_WIDTH - 4
    return [f"{indent}<!-- {title.center(inner, ' ')} -->"]


def render_fields(fields: Iterable[Field], indent: str) -> list[str]:
    """Renders a field tree, collapsing childless fields into a self-closing element."""
    lines: list[str] = []

    for item in fields:
        if item.children:
            lines.append(f'{indent}<field name="{escape(item.name)}" type="{item.type}">')
            lines.extend(render_fields(item.children, indent + '    '))
            lines.append(f'{indent}</field>')
        else:
            lines.append(f'{indent}<field name="{escape(item.name)}" type="{item.type}"/>')

    return lines


def render_body(tag: str, body_type: str | None, fields: list[Field], indent: str) -> list[str]:
    """Renders a <body> element, self-closing when the operation carries no payload."""
    if body_type is None:
        return [f'{indent}<{tag}/>']

    attributes = f'data="raw" format="json" type="{body_type}"'

    if not fields:
        return [f'{indent}<{tag} {attributes}/>']

    return [f'{indent}<{tag} {attributes}>',
            *render_fields(fields, indent + '    '),
            f'{indent}</{tag}>']


def render_operation(name: str,
                     variant: Variant,
                     route: Route,
                     method: str,
                     endpoint: str,
                     request_type: str | None,
                     request_fields: list[Field],
                     response_type: str | None,
                     response_fields: list[Field],
                     is_test: bool) -> list[str]:
    """Renders one <operation> element."""
    indent = ' ' * 8
    lines = [f'{indent}<operation name="{escape(name)}" type="{"test" if is_test else ""}">',
             f'{indent}    <request>',
             f'{indent}        <method>{method}</method>',
             f'{indent}        <endpoint>{escape(endpoint)}</endpoint>',
             f'{indent}        <header>']

    for header_name, header_value in variant.headers:
        lines.append(f'{indent}            <item name="{header_name}" type="string">{escape(header_value)}</item>')

    lines.append(f'{indent}        </header>')
    lines.extend(render_body('body', request_type, request_fields, indent + '        '))
    lines.append(f'{indent}    </request>')
    lines.append(f'{indent}    <response>')
    lines.append(f'{indent}        <success status="200">')
    lines.append(f'{indent}            <header/>')
    lines.extend(render_body('body', response_type, response_fields, indent + '            '))
    lines.append(f'{indent}        </success>')
    lines.append(f'{indent}        <fail status="500">')
    lines.append(f'{indent}            <header/>')
    lines.append(f'{indent}            <body/>')
    lines.append(f'{indent}        </fail>')
    lines.append(f'{indent}    </response>')
    lines.append(f'{indent}</operation>')

    return lines


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    GENERATION                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass
class Skipped:
    """A documented operation that could not be turned into an invoker operation."""
    path: str
    method: str
    operation_id: str
    reason: str


def endpoint_of(route: Route, doc: DocOperation, variant_url: str = '{url}/rest') -> str:
    """Builds the endpoint an operation is called on, including its query parameters."""
    query = list(PAGINATION_QUERY) if route.paginated else []
    query.extend(doc.query_params)
    endpoint = f"{variant_url}{route.url}"

    if query:
        endpoint = f"{endpoint}?" + '&'.join(f"{key}={value}" for key, value in query)

    return endpoint


def build_variant(variant: Variant,
                  operations: list[DocOperation],
                  routes: dict[str, Route],
                  resolver: SchemaResolver) -> tuple[str, int, list[Skipped], list[Skipped]]:
    """Renders one invoker XML and reports the operations it left out or had to correct."""
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
             '<invoker type="RESTful">',
             f'    <name>{variant.name}</name>',
             f'    <description>{DESCRIPTION}</description>',
             f'    <hint>{escape(variant.hint)}</hint>',
             '    <requiredData>']

    for item in variant.required_data:
        lines.append(f'        <item name="{item}" type="string" visibility="public"/>')

    lines.append('        <item name="token" type="string" visibility="private">Basic {username:password}</item>')
    lines.append('    </requiredData>')
    lines.append(f'    <authType>basic</authType>')
    lines.append('    <operations>')

    skipped: list[Skipped] = []
    corrected: list[Skipped] = []
    written = 0
    current_tag: str | None = None

    for doc in operations:
        function = ROUTE_ID_ALIASES.get(doc.operation_id, doc.operation_id)
        route = routes.get(function)

        if route is None:
            skipped.append(Skipped(doc.path, doc.method, doc.operation_id, 'no reachable route'))
            continue

        # An API-locked route is served to the user interface only, so in the cloud no integration
        # can reach it. On premise the check is a pass-through and the route works normally.
        if variant.cloud and route.api_level == 'LOCKED':
            skipped.append(Skipped(doc.path, doc.method, doc.operation_id,
                                   'API-locked, not callable in cloud mode'))
            continue

        # The scope tags are documentation and are not always kept in step with the decorators;
        # what the code lets through decides, the disagreement is reported.
        if doc.scopes and variant.scope_tag not in doc.scopes:
            corrected.append(Skipped(doc.path, doc.method, doc.operation_id,
                                     f'documented as {"/".join(doc.scopes)} only, '
                                     f'but reachable (api level {route.api_level or "none"})'))

        method = doc.method

        if method not in route.methods:
            # The spec and the code disagree; the code is what an integration will actually hit.
            if len(route.methods) != 1:
                skipped.append(Skipped(doc.path, doc.method, doc.operation_id,
                                       f'route serves {"/".join(route.methods)}'))
                continue

            method = route.methods[0]
            corrected.append(Skipped(doc.path, doc.method, doc.operation_id,
                                     f'documented as {doc.method}, served as {method}'))

        if doc.tag != current_tag:
            current_tag = doc.tag
            lines.append('')
            lines.extend(banner('', ' ' * 8))
            lines.extend(banner(doc.tag.upper(), ' ' * 8))
            lines.extend(banner('', ' ' * 8))
            lines.append('')

        request_type: str | None = None
        request_fields: list[Field] = []

        if doc.request_schema is not None:
            request_type = resolver.type_of(doc.request_schema, doc.request_dir)
            request_fields = resolver.to_fields(doc.request_schema, doc.request_dir)

        # An envelope wraps the bare resource, so the payload comes from the resource schema rather
        # than from the documented 200 body - that one already sketches an envelope of its own and
        # would end up nested inside the real one.
        if doc.entity_schema is not None:
            payload = resolver.to_fields(doc.entity_schema, doc.entity_dir)
        elif doc.success_schema is not None:
            payload = resolver.to_fields(doc.success_schema, doc.success_dir)
        else:
            payload = []

        wrapped = envelope(route.response_class, payload)

        if wrapped is not None:
            response_type, response_fields = wrapped
        elif doc.success_schema is not None:
            # DefaultResponse hands the payload back unwrapped, so the documented body is the body.
            response_type = resolver.type_of(doc.success_schema, doc.success_dir)
            response_fields = resolver.to_fields(doc.success_schema, doc.success_dir)
        else:
            response_type, response_fields = 'object', []

        lines.extend(render_operation(
            name=operation_name(doc, route),
            variant=variant,
            route=route,
            method=method,
            endpoint=endpoint_of(route, doc),
            request_type=request_type,
            request_fields=request_fields,
            response_type=response_type,
            response_fields=response_fields,
            is_test=function == TEST_OPERATION_ID and doc.method == 'GET',
        ))
        written += 1

    lines.append('    </operations>')
    lines.append('</invoker>')

    return '\n'.join(lines) + '\n', written, skipped, corrected


def main() -> int:
    """Regenerates both invoker XMLs and prints a short report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='do not write, exit non-zero when a file would change')
    args = parser.parse_args()

    resolver = SchemaResolver()
    operations = load_operations(resolver)
    routes = analyze_routes()
    changed = False

    for variant in VARIANTS:
        xml, written, skipped, corrected = build_variant(variant, operations, routes, resolver)
        target = os.path.join(HERE, variant.file_name)
        previous = open(target, encoding='utf-8').read() if os.path.exists(target) else None

        if previous != xml:
            changed = True

            if not args.check:
                with open(target, 'w', encoding='utf-8') as file:
                    file.write(xml)

        state = 'unchanged' if previous == xml else ('would change' if args.check else 'written')
        print(f"{variant.file_name}: {written} operations, {state} "
              f"(upload to OpenCelium as {variant.oc_file_name})")

        for entry in skipped:
            print(f"    skipped {entry.method} {entry.path} ({entry.operation_id}): {entry.reason}")

        for entry in corrected:
            print(f"    corrected {entry.path} ({entry.operation_id}): {entry.reason}")

    if args.check and changed:
        print("\nInvokers are out of date, run generate_invokers.py", file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
