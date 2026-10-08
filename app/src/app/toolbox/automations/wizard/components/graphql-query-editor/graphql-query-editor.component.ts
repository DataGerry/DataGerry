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
import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';

import {
    declaredVariables,
    GqlDocument,
    GqlSchema,
    GqlSchemaField,
    GqlSelection,
    INTROSPECTION_QUERY,
    listPathsOf,
    looksLikeList,
    parseGraphql,
    printGraphql,
    responseFieldsOf,
    responseKey,
    schemaFieldAt,
    schemaFromIntrospection,
    selectedPaths,
    toggleField
} from '../../models/graphql-query.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One change to a GraphQL call, written back in one go so the sequence recompiles once. */
export interface GraphqlEdit {
    query: string;

    /** The answer's shape, as the invoker response schema the rest of the automation reads. */
    response: Record<string, unknown>;

    /** Variable values to set; null takes a variable out. */
    variables: Record<string, string | null>;
}


/** A field of the answer as the side panel lists it. */
interface AnswerNode {
    key: string;
    path: string;
    depth: number;
    isObject: boolean;
    isList: boolean;
}


/** A field the schema offers, as the explorer lists it. */
interface ExplorerNode {
    name: string;
    path: string[];
    depth: number;
    field: GqlSchemaField;
    selected: boolean;
    open: boolean;
}


const SCHEMA_STORAGE_PREFIX = 'automations.graphql.schema.';


/**
 * Writing the query of a GraphQL call, and knowing what it answers.
 *
 * Where OpenCelium opens GraphiQL - a separate IDE that runs queries but tells the automation
 * nothing - this sits in the call itself and works out the answer's shape from the query, which
 * is what every later reference and loop is built on. With the server's schema loaded the fields
 * can be picked from a tree, and the schema also settles which fields are lists; without it the
 * shape is still known, and the list question is a guess the user can correct.
 */
@Component({
    selector: 'app-graphql-query-editor',
    templateUrl: './graphql-query-editor.component.html',
    styleUrls: ['./graphql-query-editor.component.scss'],
    standalone: false
})
export class GraphqlQueryEditorComponent implements OnChanges {

    @Input() public query = '';

    /** The values the variables currently have, by name. */
    @Input() public variables: Record<string, string> = {};

    /** The stored answer shape, when one was saved; which fields are lists is read back from it. */
    @Input() public response: unknown = null;

    /** Names the connector, which is what a loaded schema is remembered under. */
    @Input() public schemaKey = '';

    @Output() public edit = new EventEmitter<GraphqlEdit>();
    @Output() public pickVariable = new EventEmitter<string>();

    public text = '';
    public error = '';
    public schema: GqlSchema | null = null;
    public schemaImportOpen = false;
    public schemaText = '';
    public schemaError = '';
    public copied = false;

    public answer: AnswerNode[] = [];
    public explorer: ExplorerNode[] = [];
    public readable: string[] = [];
    public declared: string[] = [];

    public readonly introspectionQuery = INTROSPECTION_QUERY;

    private document: GqlDocument = { header: '', selections: [], trailing: '' };

    /** Which answer paths are lists, as decided so far - by the stored schema, the user, or a guess. */
    private lists = new Map<string, boolean>();
    private openPaths = new Set<string>();
    private lastEmitted = '';

    /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['schemaKey']) {
            this.schema = this.readSchema();
        }

        if (changes['response']) {
            this.lists = new Map(listPathsOf(this.response).map(path => [path, true]));
        }

        // A query coming back as what was just sent is this editor's own echo; taking it would
        // reset the cursor's text to the formatted form while the user is still looking at theirs.
        if (changes['query'] && this.query !== this.lastEmitted) {
            this.text = this.query;
            this.parse();
        } else if (changes['response'] || changes['schemaKey']) {
            this.rebuild();
        }
    }

    /* ---------------------------------------------------- QUERY ----------------------------------------------------- */

    public onType(value: string): void {
        this.text = value;
        this.parse();
    }


    /** Stores the query once the user leaves the editor, formatted, so it cannot be misread. */
    public commit(): void {
        if (this.error || this.text === this.lastEmitted) {
            return;
        }

        this.emitDocument();
    }


    public format(): void {
        if (!this.error) {
            this.emitDocument();
        }
    }


    private parse(): void {
        try {
            this.document = parseGraphql(this.text);
            this.error = '';
        } catch (error: any) {
            this.error = error?.message ?? 'The query cannot be read.';
        }

        this.rebuild();
    }


    /**
     * Sends the query, its answer and any variable change. While the text does not parse, what is
     * sent is the query as last stored, and the text being typed is left alone.
     */
    private emitDocument(variables: Record<string, string | null> = {}): void {
        const printed = this.document.selections.length > 0 ? printGraphql(this.document) : '';
        const query = this.error ? this.query : printed;
        const declared = declaredVariables(this.document);

        // Variables the query no longer declares would be sent anyway and could be rejected.
        const dropped = Object.keys(this.variables).filter(name => !declared.includes(name));

        if (!this.error) {
            this.text = query;
        }

        this.lastEmitted = query;
        this.edit.emit({
            query,
            response: this.responseFields(),
            variables: {
                ...Object.fromEntries(dropped.map(name => [name, null])),
                ...variables
            }
        });
        this.rebuild();
    }

    /* -------------------------------------------------- VARIABLES --------------------------------------------------- */

    public onVariable(name: string, value: string): void {
        this.emitDocument({ [name]: value });
    }


    public isReference(value: string | undefined): boolean {
        return !!value && /^#[0-9A-Fa-f]{6}\.\(/.test(value);
    }


    /** A reference by the name it reads, as the rest of the sequence shows references. */
    public referenceName(value: string): string {
        const last = value.split('.').filter(Boolean).pop() ?? value;

        return last.replace(/\[[^\]]*\]$/, '') || last;
    }

    /* ---------------------------------------------------- ANSWER ---------------------------------------------------- */

    /** Marks a field as a list or as a single object, for when no schema can say. */
    public toggleList(node: AnswerNode): void {
        this.lists.set(node.path, !node.isList);
        this.emitDocument();
    }

    /* --------------------------------------------------- EXPLORER --------------------------------------------------- */

    public toggleOpen(node: ExplorerNode): void {
        const key = node.path.join('.');

        if (this.openPaths.has(key)) {
            this.openPaths.delete(key);
        } else {
            this.openPaths.add(key);
        }

        this.rebuild();
    }


    /** Adds the field to the query or takes it out, and opens an object so its fields can follow. */
    public toggleField(node: ExplorerNode): void {
        this.document = toggleField(this.document, node.path, node.field.leaf);

        if (!node.field.leaf && !node.selected) {
            this.openPaths.add(node.path.join('.'));
        }

        this.emitDocument();
    }

    /* ---------------------------------------------------- SCHEMA ---------------------------------------------------- */

    public importSchema(): void {
        try {
            this.schema = schemaFromIntrospection(this.schemaText);
            this.schemaError = '';
            this.schemaText = '';
            this.schemaImportOpen = false;
            this.writeSchema(this.schema);
            this.lists.clear();
            this.emitDocument();
        } catch (error: any) {
            this.schemaError = error?.message ?? 'The schema could not be read.';
        }
    }


    public forgetSchema(): void {
        this.schema = null;
        this.writeSchema(null);
        this.rebuild();
    }


    public copyIntrospection(): void {
        navigator.clipboard?.writeText(this.introspectionQuery).then(() => {
            this.copied = true;
            window.setTimeout(() => this.copied = false, 1500);
        }).catch(() => undefined);
    }


    private readSchema(): GqlSchema | null {
        try {
            const raw = this.schemaKey ? window.localStorage.getItem(SCHEMA_STORAGE_PREFIX + this.schemaKey) : null;

            return raw ? JSON.parse(raw) as GqlSchema : null;
        } catch {
            return null;
        }
    }


    /** Per browser and connector: the schema belongs to the server, not to one automation. */
    private writeSchema(schema: GqlSchema | null): void {
        if (!this.schemaKey) {
            return;
        }

        try {
            if (schema) {
                window.localStorage.setItem(SCHEMA_STORAGE_PREFIX + this.schemaKey, JSON.stringify(schema));
            } else {
                window.localStorage.removeItem(SCHEMA_STORAGE_PREFIX + this.schemaKey);
            }
        } catch {
            // Too large or not allowed: the schema then lasts for this visit only.
        }
    }

    /* ------------------------------------------------- COMPUTATION -------------------------------------------------- */

    public get rootTypeLabel(): string {
        return this.rootType || 'Query';
    }


    private get rootType(): string {
        const mutation = /^\s*mutation\b/.test(this.document.header);

        return (mutation ? this.schema?.mutationType : this.schema?.queryType) ?? '';
    }


    /**
     * Whether the field at an answer path is a list. The schema knows; failing that, whatever was
     * decided for the path before; failing that, a guess from its name.
     */
    private isList(keyPath: string, namePath: string[]): boolean {
        if (this.schema) {
            const field = schemaFieldAt(this.schema, this.rootType, namePath);

            if (field) {
                return field.list;
            }
        }

        return this.lists.get(keyPath) ?? looksLikeList(namePath[namePath.length - 1] ?? '');
    }


    private responseFields(): Record<string, unknown> {
        const names = new Map<string, string[]>();
        this.collectNames(this.document.selections, '', [], names);

        return responseFieldsOf(this.document, path => this.isList(path, names.get(path) ?? path.split('.')));
    }


    /** Maps each answer path (by response key) to its path of schema field names. */
    private collectNames(selections: GqlSelection[], prefix: string, names: string[], out: Map<string, string[]>): void {
        for (const selection of selections) {
            if (selection.spread) {
                continue;
            }

            if (selection.inline) {
                this.collectNames(selection.children ?? [], prefix, names, out);

                continue;
            }

            const key = responseKey(selection);
            const path = prefix ? `${prefix}.${key}` : key;
            const namePath = [...names, selection.name];
            out.set(path, namePath);
            this.collectNames(selection.children ?? [], path, namePath, out);
        }
    }


    /** Recomputes everything the template shows, so it never has to work anything out itself. */
    private rebuild(): void {
        const fields = this.responseFields();

        this.declared = declaredVariables(this.document);
        this.answer = this.answerNodes((fields['data'] ?? {}) as Record<string, unknown>, '', 0);
        this.readable = this.readablePaths(fields['data'], 'data');
        this.explorer = this.schema ? this.explorerNodes(this.rootType, [], 0, selectedPaths(this.document)) : [];
    }


    private answerNodes(node: Record<string, unknown>, prefix: string, depth: number): AnswerNode[] {
        return Object.entries(node).flatMap(([key, value]) => {
            const path = prefix ? `${prefix}.${key}` : key;
            const isList = Array.isArray(value);
            const inner = isList ? value[0] : value;
            const isObject = !!inner && typeof inner === 'object';
            const own: AnswerNode = { key, path, depth, isObject, isList };

            return isObject ? [own, ...this.answerNodes(inner as Record<string, unknown>, path, depth + 1)] : [own];
        });
    }


    /** The paths a later step reads, written the way the value picker lists them. */
    private readablePaths(node: unknown, prefix: string): string[] {
        if (Array.isArray(node)) {
            return [`${prefix}[*]`, ...this.readablePaths(node[0], `${prefix}[i]`)];
        }

        if (!node || typeof node !== 'object') {
            return prefix === 'data' ? [] : [prefix];
        }

        return Object.entries(node as Record<string, unknown>)
            .flatMap(([key, value]) => this.readablePaths(value, `${prefix}.${key}`));
    }


    private explorerNodes(type: string, path: string[], depth: number, selected: Set<string>): ExplorerNode[] {
        const fields = this.schema?.types[type] ?? {};

        // Deep enough for any real query; a cyclic schema would otherwise be infinite.
        if (depth > 8) {
            return [];
        }

        return Object.entries(fields)
            .sort(([left], [right]) => left.localeCompare(right))
            .flatMap(([name, field]) => {
                const own = [...path, name];
                const key = own.join('.');
                const node: ExplorerNode = {
                    name,
                    path: own,
                    depth,
                    field,
                    selected: selected.has(key),
                    open: this.openPaths.has(key)
                };

                return node.open && !field.leaf
                    ? [node, ...this.explorerNodes(field.type, own, depth + 1, selected)]
                    : [node];
            });
    }
}
