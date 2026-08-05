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
import { Injectable } from '@angular/core';

import { AutomationOperation } from '../models/automation-definition.model';
import {
    findAdapter,
    OPERATION_EXCLUDE_KEYWORDS,
    OPERATION_KEYWORDS,
    ResolvedOperation,
    TargetField,
    TargetOperationCandidates
} from '../models/target-catalog.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A target system the user can pick, derived from the configured connectors. */
export interface SelectableTargetSystem {
    connectorId: number;
    title: string;
    invokerName: string;
    displayName: string;

    /** False when the action mapping had to be guessed - surfaced in the UI. */
    verified: boolean;

    /** Actions that could actually be resolved against this invoker. */
    availableOperations: AutomationOperation[];
}

/**
 * Resolves the wizard's functional vocabulary against whatever OpenCelium actually reports.
 *
 * Operation names and payload shapes differ per system and per invoker version, so this service
 * never assumes either: names come from adapter candidates with a keyword fallback, and every path
 * is read out of the invoker's own operation schema.
 */
@Injectable({ providedIn: 'root' })
export class TargetCatalogService {

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                OPERATION RESOLUTION                                                */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Finds the invoker operation that implements a functional action.
     *
     * Tries the adapter's candidate names first, then falls back to keyword scoring. Returns null
     * when the invoker offers nothing suitable, which the UI reports as an unsupported action.
     */
    public resolveOperation(invoker: any, action: keyof TargetOperationCandidates): ResolvedOperation | null {
        const operations: any[] = Array.isArray(invoker?.operations) ? invoker.operations : [];

        if (operations.length === 0) {
            return null;
        }

        const adapter = findAdapter(invoker?.name);

        if (adapter) {
            for (const candidate of adapter.operations[action]) {
                const match = operations.find(
                    operation => this.normalize(operation?.name) === this.normalize(candidate)
                );

                if (match) {
                    return this.toResolved(match, true);
                }
            }
        }

        const guessed = this.guessOperation(operations, action);

        return guessed ? this.toResolved(guessed, false) : null;
    }


    /** Which of the three functional actions this invoker can perform. */
    public availableOperations(invoker: any): AutomationOperation[] {
        const actions: AutomationOperation[] = ['create', 'update', 'delete'];

        return actions.filter(action => this.resolveOperation(invoker, action) !== null);
    }


    /**
     * Builds the list of pickable target systems from the configured connectors.
     *
     * The internal DataGerry connector is excluded: it is always the other end of an automation,
     * never the chosen target system.
     */
    public selectableSystems(
        connectors: any[],
        internalConnectorTitle: string
    ): SelectableTargetSystem[] {
        return (connectors ?? [])
            .filter(connector => connector?.title !== internalConnectorTitle)
            .map(connector => {
                const invoker = connector?.invoker;
                const adapter = findAdapter(invoker?.name);

                return {
                    connectorId: connector.connectorId,
                    title: connector.title,
                    invokerName: invoker?.name ?? '',
                    displayName: adapter?.displayName ?? invoker?.name ?? connector.title,
                    verified: adapter?.verified ?? false,
                    availableOperations: this.availableOperations(invoker)
                };
            })
            .filter(system => system.availableOperations.length > 0);
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   FIELD DISCOVERY                                                  */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Lists the fields a target operation accepts, flattened out of its request body schema.
     *
     * Arrays are treated as leaves: OpenCelium addresses their elements positionally and the
     * reference payloads contain no example of mapping into one, so the wizard offers the array
     * itself rather than inventing an element path.
     */
    public targetFields(operation: ResolvedOperation | null): TargetField[] {
        const fields = operation?.definition?.request?.body?.fields;

        if (!fields || typeof fields !== 'object') {
            return [];
        }

        return this.flatten(fields, '');
    }


    /**
     * Lists the fields a source operation returns for one item of its collection.
     *
     * These are the values an automation can read, so they feed the mapping step's left-hand side
     * when the source is a foreign system.
     */
    public sourceItemFields(operation: ResolvedOperation | null): TargetField[] {
        const body = operation?.definition?.response?.success?.body?.fields;

        if (!body || typeof body !== 'object') {
            return [];
        }

        const arrayPath = operation!.responseArrayPath;

        if (!arrayPath) {
            return this.flatten(body, '');
        }

        const collection = body[arrayPath];
        const item = Array.isArray(collection) ? collection[0] : null;

        return item && typeof item === 'object' ? this.flatten(item, '') : [];
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      INTERNALS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    private toResolved(operation: any, verified: boolean): ResolvedOperation {
        return {
            name: operation.name,
            definition: operation,
            responseArrayPath: this.findResponseArrayPath(operation),
            verified
        };
    }


    /**
     * Locates the collection inside an operation's success response.
     *
     * Both reference systems wrap their items in a single array-valued key - 'result' for i-doit,
     * 'results' for DataGerry - so the first array-valued key wins. Returns '' for operations that
     * do not answer with a list.
     */
    private findResponseArrayPath(operation: any): string {
        const fields = operation?.response?.success?.body?.fields;

        if (!fields || typeof fields !== 'object') {
            return '';
        }

        const arrayKey = Object.keys(fields).find(key => Array.isArray(fields[key]) && fields[key].length > 0);

        return arrayKey ?? '';
    }


    /** Scores every operation by keyword and returns the best non-excluded candidate. */
    private guessOperation(operations: any[], action: keyof TargetOperationCandidates): any | null {
        const keywords = OPERATION_KEYWORDS[action];
        let best: { operation: any; score: number } | null = null;

        for (const operation of operations) {
            const name = this.normalize(operation?.name);

            if (!name || OPERATION_EXCLUDE_KEYWORDS.some(word => name.includes(word))) {
                continue;
            }

            // Earlier keywords imply the action more strongly, so they score higher.
            const index = keywords.findIndex(keyword => name.includes(keyword));

            if (index === -1) {
                continue;
            }

            const score = keywords.length - index;

            if (!best || score > best.score) {
                best = { operation, score };
            }
        }

        return best?.operation ?? null;
    }


    /** Turns a nested schema object into dotted leaf paths. */
    private flatten(node: Record<string, any>, prefix: string): TargetField[] {
        const result: TargetField[] = [];

        for (const [key, value] of Object.entries(node)) {
            const path = prefix ? `${prefix}.${key}` : key;

            if (value && typeof value === 'object' && !Array.isArray(value)) {
                result.push(...this.flatten(value, path));
                continue;
            }

            result.push({
                path,
                name: key,
                type: Array.isArray(value) ? 'array' : typeof value === 'string' ? 'string' : typeof value
            });
        }

        return result;
    }


    private normalize(value: string | null | undefined): string {
        return (value ?? '').trim().toLowerCase();
    }
}
