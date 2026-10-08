/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
/* ------------------------------------------------------------------------------------------------------------------ */

/*
 * Just enough GraphQL to edit a query and know what it answers.
 *
 * A GraphQL invoker such as JDisc's has one operation and no fixed answer: what comes back is
 * whatever the query asked for. The invoker's response schema is a guess made when it was written,
 * and every reference and loop downstream is built from that guess - so a query asking for anything
 * else left the rest of the automation unable to read it. Reading the query tells us the answer's
 * shape exactly, except for which fields are lists, which only the server's schema knows.
 */

/** One field of a selection set, or a fragment inside it. */
export interface GqlSelection {
    /** The field's name; for a fragment, its spelling: `... on Device` or `...DeviceParts`. */
    name: string;
    alias?: string;

    /** The argument list as written, parentheses included. Kept verbatim, never interpreted. */
    args?: string;
    directives?: string;

    /** Null for a leaf. */
    children: GqlSelection[] | null;

    /** An inline fragment's fields belong to the object around it. */
    inline?: boolean;

    /** A named fragment, defined elsewhere in the document and kept as written. */
    spread?: boolean;
}


export interface GqlDocument {
    /** Everything before the first selection set: `query Devices($name: String)`, or empty. */
    header: string;
    selections: GqlSelection[];

    /** Whatever follows the operation - fragment definitions, typically - kept as written. */
    trailing: string;
}


export class GqlSyntaxError extends Error {
    constructor(message: string, public readonly line: number) {
        super(`Line ${line}: ${message}`);
    }
}

/* ----------------------------------------------------- PARSING ---------------------------------------------------- */

const NAME = /[_A-Za-z][_0-9A-Za-z]*/y;


export function parseGraphql(source: string): GqlDocument {
    const reader = new Reader(source);
    reader.skip();

    const open = reader.findTopLevel('{');

    if (open === -1) {
        if (!source.trim()) {
            return { header: '', selections: [], trailing: '' };
        }

        throw reader.error('A query needs a selection in braces, e.g. { devices { findAll { id } } }');
    }

    const header = source.slice(reader.at, open).trim();
    reader.at = open;
    const selections = reader.selectionSet();
    reader.skip();

    return { header, selections, trailing: source.slice(reader.at).trim() };
}


class Reader {
    public at = 0;

    constructor(private readonly source: string) {}


    public error(message: string): GqlSyntaxError {
        return new GqlSyntaxError(message, this.source.slice(0, this.at).split('\n').length);
    }


    /** Whitespace, commas and comments mean nothing to GraphQL. */
    public skip(): void {
        while (this.at < this.source.length) {
            const char = this.source[this.at];

            if (char === '#') {
                const end = this.source.indexOf('\n', this.at);
                this.at = end === -1 ? this.source.length : end + 1;
            } else if (/[\s,﻿]/.test(char)) {
                this.at++;
            } else {
                return;
            }
        }
    }


    /** The position of `char` outside strings, comments and brackets, from here on. */
    public findTopLevel(char: string): number {
        let depth = 0;

        for (let index = this.at; index < this.source.length; index++) {
            const current = this.source[index];

            if (current === '"') {
                index = this.stringEnd(index) - 1;
            } else if (current === '#') {
                const end = this.source.indexOf('\n', index);
                index = end === -1 ? this.source.length : end;
            } else if (current === '(' || current === '[') {
                depth++;
            } else if (current === ')' || current === ']') {
                depth--;
            } else if (current === char && depth === 0) {
                return index;
            }
        }

        return -1;
    }


    public selectionSet(): GqlSelection[] {
        this.expect('{');
        const selections: GqlSelection[] = [];

        for (;;) {
            this.skip();

            if (this.at >= this.source.length) {
                throw this.error('A "}" is missing.');
            }

            if (this.peek('}')) {
                this.at++;

                return selections;
            }

            selections.push(this.peek('...') ? this.fragment() : this.field());
        }
    }


    private field(): GqlSelection {
        const first = this.name();
        this.skip();

        const selection: GqlSelection = { name: first, children: null };

        if (this.peek(':')) {
            this.at++;
            this.skip();
            selection.alias = first;
            selection.name = this.name();
            this.skip();
        }

        if (this.peek('(')) {
            selection.args = this.balanced('(', ')');
            this.skip();
        }

        const directives = this.directives();

        if (directives) {
            selection.directives = directives;
        }

        if (this.peek('{')) {
            selection.children = this.selectionSet();
        }

        return selection;
    }


    private fragment(): GqlSelection {
        this.at += 3;
        this.skip();

        if (this.peek('{') || this.peek('@') || /^on\s/.test(this.source.slice(this.at, this.at + 3))) {
            let name = '...';

            if (this.peek('on')) {
                this.at += 2;
                this.skip();
                name = `... on ${this.name()}`;
                this.skip();
            }

            const directives = this.directives();

            return {
                name,
                inline: true,
                ...(directives ? { directives } : {}),
                children: this.selectionSet()
            };
        }

        const name = `...${this.name()}`;
        this.skip();
        const directives = this.directives();

        return { name, spread: true, children: null, ...(directives ? { directives } : {}) };
    }


    private directives(): string {
        const parts: string[] = [];

        while (this.peek('@')) {
            this.at++;
            let directive = `@${this.name()}`;
            this.skip();

            if (this.peek('(')) {
                directive += this.balanced('(', ')');
                this.skip();
            }

            parts.push(directive);
        }

        return parts.join(' ');
    }


    private name(): string {
        NAME.lastIndex = this.at;
        const match = NAME.exec(this.source);

        if (!match) {
            const found = this.source[this.at] ?? 'the end';

            throw this.error(`A field name was expected, found "${found}".`);
        }

        this.at += match[0].length;

        return match[0];
    }


    /** The text from an opening bracket to its partner, both included. */
    private balanced(open: string, close: string): string {
        const start = this.at;
        let depth = 0;

        while (this.at < this.source.length) {
            const char = this.source[this.at];

            if (char === '"') {
                this.at = this.stringEnd(this.at);

                continue;
            }

            if (char === open) {
                depth++;
            } else if (char === close) {
                depth--;

                if (depth === 0) {
                    this.at++;

                    return this.source.slice(start, this.at);
                }
            }

            this.at++;
        }

        throw this.error(`A "${close}" is missing.`);
    }


    /** The position just after the string starting at `start`, block strings included. */
    private stringEnd(start: number): number {
        if (this.source.startsWith('"""', start)) {
            const end = this.source.indexOf('"""', start + 3);

            return end === -1 ? this.source.length : end + 3;
        }

        for (let index = start + 1; index < this.source.length; index++) {
            if (this.source[index] === '\\') {
                index++;
            } else if (this.source[index] === '"') {
                return index + 1;
            }
        }

        return this.source.length;
    }


    private peek(text: string): boolean {
        return this.source.startsWith(text, this.at);
    }


    private expect(text: string): void {
        if (!this.peek(text)) {
            throw this.error(`"${text}" was expected.`);
        }

        this.at += text.length;
    }
}

/* ---------------------------------------------------- PRINTING ---------------------------------------------------- */

/**
 * The document written out again, one field per line.
 *
 * Braces always stand apart from what they hold. OpenCelium fills `{name}` placeholders in a request
 * body from the connector's settings, and `{id}` written tightly would be read as one of those.
 */
export function printGraphql(document: GqlDocument): string {
    const body = printSelections(document.selections, '  ');
    const operation = `${document.header ? `${document.header} ` : ''}{\n${body}\n}`;

    return document.trailing ? `${operation}\n\n${document.trailing}` : operation;
}


function printSelections(selections: GqlSelection[], indent: string): string {
    return selections.map(selection => {
        const head = [
            selection.alias ? `${selection.alias}: ${selection.name}` : selection.name,
            selection.args ?? ''
        ].join('') + (selection.directives ? ` ${selection.directives}` : '');

        if (!selection.children) {
            return `${indent}${head}`;
        }

        if (selection.children.length === 0) {
            return `${indent}${head} { }`;
        }

        return `${indent}${head} {\n${printSelections(selection.children, `${indent}  `)}\n${indent}}`;
    }).join('\n');
}

/* ------------------------------------------------- WHAT IT ANSWERS ------------------------------------------------ */

/** The key a field's value arrives under: its alias when it has one. */
export function responseKey(selection: GqlSelection): string {
    return selection.alias ?? selection.name;
}


/**
 * The answer's shape as an invoker response schema: `{ data: { ... } }`, a list as `[ { ... } ]`.
 *
 * `isList` decides for each field, by its dotted path of response keys below `data`. Inline fragments
 * add their fields to the object around them; a named fragment is defined elsewhere and adds
 * nothing that can be known here.
 */
export function responseFieldsOf(
    document: GqlDocument,
    isList: (path: string) => boolean
): Record<string, unknown> {
    return { data: objectOf(document.selections, '', isList) };
}


function objectOf(selections: GqlSelection[], prefix: string, isList: (path: string) => boolean): Record<string, unknown> {
    const object: Record<string, unknown> = {};

    for (const selection of selections) {
        if (selection.spread) {
            continue;
        }

        if (selection.inline) {
            Object.assign(object, objectOf(selection.children ?? [], prefix, isList));

            continue;
        }

        const key = responseKey(selection);
        const path = prefix ? `${prefix}.${key}` : key;
        const value = selection.children ? objectOf(selection.children, path, isList) : '';

        object[key] = isList(path) ? [value] : value;
    }

    return object;
}


/** The paths below `data` that a stored response schema marks as lists. */
export function listPathsOf(fields: unknown): string[] {
    const data = (fields as Record<string, unknown> | null)?.['data'];
    const paths: string[] = [];

    const walk = (node: unknown, prefix: string) => {
        if (!node || typeof node !== 'object') {
            return;
        }

        for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
            const path = prefix ? `${prefix}.${key}` : key;

            if (Array.isArray(value)) {
                paths.push(path);
                walk(value[0], path);
            } else {
                walk(value, path);
            }
        }
    };

    walk(data, '');

    return paths;
}


/**
 * A guess at whether a field answers a list, for when no schema says.
 *
 * Plural names are not enough: JDisc's `devices` is a namespace and its `findAll` is the list. The
 * guess keys on the verbs and suffixes list fields are named with, and the user corrects the rest.
 */
export function looksLikeList(name: string): boolean {
    return /^(find|list|search|all)/i.test(name)
        || /(All|List|Items|Nodes|Edges|Collection)$/.test(name)
        || name === 'nodes'
        || name === 'edges'
        || name === 'items';
}


/** The variables the operation declares, by name without the `$`. */
export function declaredVariables(document: GqlDocument): string[] {
    return [...document.header.matchAll(/\$([_A-Za-z][_0-9A-Za-z]*)\s*:/g)].map(match => match[1]);
}


/** Every path of fields the document selects, by schema field name (not alias), as `a.b.c`. */
export function selectedPaths(document: GqlDocument): Set<string> {
    const paths = new Set<string>();

    const walk = (selections: GqlSelection[], prefix: string) => {
        for (const selection of selections) {
            if (selection.spread) {
                continue;
            }

            if (selection.inline) {
                walk(selection.children ?? [], prefix);

                continue;
            }

            const path = prefix ? `${prefix}.${selection.name}` : selection.name;
            paths.add(path);
            walk(selection.children ?? [], path);
        }
    };

    walk(document.selections, '');

    return paths;
}


/**
 * Adds the field at `path` to the document, or takes it out when it is already there.
 *
 * What is added is created along the way; what is taken out takes its parents with it once they
 * select nothing else, because an empty selection set is not valid GraphQL.
 */
export function toggleField(document: GqlDocument, path: string[], leaf: boolean): GqlDocument {
    const copy: GqlDocument = JSON.parse(JSON.stringify(document));

    if (hasField(copy.selections, path)) {
        removeField(copy.selections, path);
    } else {
        addField(copy.selections, path, leaf);
    }

    return copy;
}


function hasField(selections: GqlSelection[], path: string[]): boolean {
    const found = selections.find(selection => !selection.inline && !selection.spread && selection.name === path[0]);

    if (!found) {
        return false;
    }

    return path.length === 1 || hasField(found.children ?? [], path.slice(1));
}


function addField(selections: GqlSelection[], path: string[], leaf: boolean): void {
    let found = selections.find(selection => !selection.inline && !selection.spread && selection.name === path[0]);
    const last = path.length === 1;

    if (!found) {
        found = { name: path[0], children: last && leaf ? null : [] };
        selections.push(found);
    }

    if (!last) {
        found.children = found.children ?? [];
        addField(found.children, path.slice(1), leaf);
    }
}


function removeField(selections: GqlSelection[], path: string[]): boolean {
    const index = selections.findIndex(selection => !selection.inline && !selection.spread && selection.name === path[0]);

    if (index === -1) {
        return false;
    }

    if (path.length === 1) {
        selections.splice(index, 1);
    } else {
        const children = selections[index].children ?? [];
        removeField(children, path.slice(1));

        if (children.length === 0) {
            selections.splice(index, 1);
        }
    }

    return true;
}

/* ----------------------------------------------------- SCHEMA ----------------------------------------------------- */

/** A server's schema, cut down to what choosing fields needs. */
export interface GqlSchema {
    queryType: string;
    mutationType: string | null;

    /** Object types by name, each with its fields by name. */
    types: Record<string, Record<string, GqlSchemaField>>;
}


export interface GqlSchemaField {
    /** The named type the field answers, with lists and non-null unwrapped. */
    type: string;
    list: boolean;

    /** True when the type has no fields of its own: a scalar or an enum. */
    leaf: boolean;
    args: string[];
}


/**
 * What to send the server to learn its schema - the standard question, trimmed to what is used.
 *
 * Offered to copy because the wizard cannot ask the server itself: the credentials live in the
 * connector inside OpenCelium, not here.
 */
export const INTROSPECTION_QUERY = [
    'query IntrospectionQuery {',
    '  __schema {',
    '    queryType { name }',
    '    mutationType { name }',
    '    types {',
    '      kind',
    '      name',
    '      fields(includeDeprecated: true) {',
    '        name',
    '        args { name }',
    '        type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }',
    '      }',
    '    }',
    '  }',
    '}'
].join('\n');


/**
 * Reads an introspection answer, as JSON text, into a GqlSchema.
 *
 * Accepts the whole answer (`{ "data": { "__schema": … } }`) or just the `__schema` part, since
 * either is what people end up copying. Throws with a readable message for anything else.
 */
export function schemaFromIntrospection(text: string): GqlSchema {
    let parsed: any;

    try {
        parsed = JSON.parse(text);
    } catch {
        throw new Error('This is not JSON. Paste the answer the server gave to the introspection query.');
    }

    const schema = parsed?.data?.__schema ?? parsed?.__schema ?? parsed;

    if (!Array.isArray(schema?.types) || !schema?.queryType?.name) {
        throw new Error('No schema found. The answer should contain "__schema" with "types" and "queryType".');
    }

    const kinds = new Map<string, string>(schema.types.map((type: any) => [type.name, type.kind]));
    const types: GqlSchema['types'] = {};

    for (const type of schema.types) {
        if (!Array.isArray(type.fields) || String(type.name).startsWith('__')) {
            continue;
        }

        types[type.name] = Object.fromEntries(type.fields.map((field: any) => {
            const named = unwrapType(field.type);
            const kind = kinds.get(named.name) ?? named.kind;

            return [field.name, {
                type: named.name,
                list: named.list,
                leaf: kind === 'SCALAR' || kind === 'ENUM',
                args: (field.args ?? []).map((arg: any) => arg.name)
            }];
        }));
    }

    return {
        queryType: schema.queryType.name,
        mutationType: schema.mutationType?.name ?? null,
        types
    };
}


function unwrapType(type: any): { name: string; kind: string; list: boolean } {
    let list = false;
    let current = type;

    while (current && (current.kind === 'NON_NULL' || current.kind === 'LIST')) {
        list = list || current.kind === 'LIST';
        current = current.ofType;
    }

    return { name: current?.name ?? '', kind: current?.kind ?? '', list };
}


/** The schema field at a path of field names from the operation's root type, or null. */
export function schemaFieldAt(schema: GqlSchema, root: string, path: string[]): GqlSchemaField | null {
    let type = root;
    let field: GqlSchemaField | null = null;

    for (const name of path) {
        field = schema.types[type]?.[name] ?? null;

        if (!field) {
            return null;
        }

        type = field.type;
    }

    return field;
}
