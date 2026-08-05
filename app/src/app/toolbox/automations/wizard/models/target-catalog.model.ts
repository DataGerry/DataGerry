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
import { AutomationOperation } from './automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Maps the wizard's functional actions onto the concrete operations an OpenCelium invoker offers.
 *
 * Operation names differ per system and even between versions of the same invoker: the reference
 * payloads from a running installation carry a DataGerryCloud invoker with 12 short-named
 * operations ('AddObject'), while cmdb/open_celium/invokers/dg_cloud_invoker.xml ships 43
 * long-named ones ('Create new Object'). Adapters therefore list *candidate* names in priority
 * order and fall back to keyword matching, and nothing here hardcodes a response shape - paths are
 * resolved from the invoker's own operation schema at compile time.
 */

/** Operation-name candidates per functional action, most specific first. */
export interface TargetOperationCandidates {
    list: string[];
    create: string[];
    update: string[];
    delete: string[];
}


/**
 * Where the object-type restriction goes in the list operation's request.
 *
 * Without it an automation reads every object of the system instead of the selected type - the
 * reference payload sets params.filter.type = ["10"] on i-doit's cmdb.objects.read.
 */
export interface ListFilterPlacement {
    /** Dotted path inside request.body.fields, e.g. 'params.filter.type'. */
    bodyPath?: string;

    /**
     * Query parameter appended to request.endpoint, for list operations that take no body
     * (DataGerry's Get Objects is a GET).
     */
    endpointQuery?: string;

    /** Whether the value is written as a single-element array. */
    asArray: boolean;

    /**
     * Whether the parent object of bodyPath is reduced to just this key.
     *
     * The reference prunes i-doit's filter object down to `type` alone, dropping the seven unused
     * filter keys the invoker template carries.
     */
    pruneSiblings: boolean;
}


export interface TargetSystemAdapter {
    /** Invoker name as reported by OpenCelium - the lookup key. */
    invokerName: string;

    /** Name shown in the wizard. */
    displayName: string;

    /**
     * Whether the mapping of actions to operations is backed by a known-good reference payload.
     * Unverified adapters are resolved by heuristics and are flagged as such in the UI.
     */
    verified: boolean;
    operations: TargetOperationCandidates;

    /** How to restrict the list operation to one object type. Absent when unknown. */
    listFilter?: ListFilterPlacement;

    /**
     * Where the read operation takes its page size, so the wizard's batch size setting has an
     * effect. Dotted path inside request.body.fields, or a query parameter name.
     */
    listLimit?: { bodyPath?: string; endpointQuery?: string };

    /**
     * Label the wizard gives the system's identifier for an object type, shown when the user has to
     * supply it by hand (an i-doit type id is not derivable from a DataGerry type).
     */
    remoteTypeLabel?: string;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                  VERIFIED ADAPTERS                                                 */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * DataGerry restricts a list read through the REST filter query parameter.
 *
 * Its Get Objects operation is a GET without a body, so the restriction cannot go into
 * request.body. No reference payload covers the outgoing direction - the compiler warns about this.
 */
const DATAGERRY_LIST_FILTER: ListFilterPlacement = {
    endpointQuery: 'filter',
    asArray: false,
    pruneSiblings: false
};

/** DataGerry's own operation names, taken from cmdb/open_celium/invokers/dg_cloud_invoker.xml. */
const DATAGERRY_OPERATIONS: TargetOperationCandidates = {
    list: ['Get Objects', 'GetObjects'],
    create: ['Create new Object', 'AddObject'],
    update: ['Update object', 'Update Object', 'UpdateObject'],
    delete: ['Delete Object by public_id', 'DeleteObject']
};

/**
 * Adapters whose action mapping is backed by evidence.
 *
 * DataGerry: from the shipped invoker XML. i-doit: from the reference connection payloads
 * (cmdb.objects.read on the source side).
 */
export const KNOWN_TARGET_ADAPTERS: ReadonlyArray<TargetSystemAdapter> = [
    {
        invokerName: 'DataGerry',
        displayName: 'DataGerry',
        verified: true,
        operations: DATAGERRY_OPERATIONS,
        listFilter: DATAGERRY_LIST_FILTER,
        listLimit: { endpointQuery: 'limit' }
    },
    {
        invokerName: 'DataGerryCloud',
        displayName: 'DataGerry',
        verified: true,
        operations: DATAGERRY_OPERATIONS,
        listFilter: DATAGERRY_LIST_FILTER,
        listLimit: { endpointQuery: 'limit' }
    },
    {
        invokerName: 'i-doit',
        displayName: 'i-doit',
        verified: true,
        operations: {
            list: ['cmdb.objects.read'],
            create: ['cmdb.object.create'],
            update: ['cmdb.object.update'],
            delete: ['cmdb.object.delete']
        },
        // Taken from the reference payload: params.filter is pruned to type: ["10"].
        listFilter: { bodyPath: 'params.filter.type', asArray: true, pruneSiblings: true },
        listLimit: { bodyPath: 'params.limit' },
        remoteTypeLabel: 'i-doit object type ID'
    }
];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     HEURISTICS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Keywords used to guess an operation when no verified adapter exists.
 *
 * Ordered by how strongly each word implies the action, so 'create' beats a mere 'new'.
 */
export const OPERATION_KEYWORDS: Readonly<Record<keyof TargetOperationCandidates, string[]>> = {
    list: ['read', 'list', 'search', 'query', 'getall', 'get'],
    create: ['create', 'insert', 'add', 'new', 'post'],
    update: ['update', 'edit', 'modify', 'patch', 'set'],
    delete: ['delete', 'remove', 'destroy', 'purge']
};

/**
 * Words that make an operation unsuitable as a business action even if it matches a keyword -
 * connector self-tests and auth calls.
 */
export const OPERATION_EXCLUDE_KEYWORDS: ReadonlyArray<string> = ['login', 'logout', 'test', 'ping', 'auth'];

/** Functional action names in the order the wizard presents them. */
export const AUTOMATION_OPERATION_CHOICES: ReadonlyArray<{ value: AutomationOperation; label: string; icon: string }> = [
    { value: 'create', label: 'Create object', icon: 'fas fa-plus' },
    { value: 'update', label: 'Update object', icon: 'fas fa-pen' },
    { value: 'delete', label: 'Delete object', icon: 'fas fa-trash' }
];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   RESOLVED TARGET                                                  */
/* ------------------------------------------------------------------------------------------------------------------ */

/** An invoker operation resolved for one side of an automation. */
export interface ResolvedOperation {
    /** Operation name exactly as OpenCelium reports it. */
    name: string;

    /** The full invoker operation definition, cloned into the connection's methods. */
    definition: any;

    /**
     * Dotted path inside the success response body that carries the collection of items,
     * derived from the operation's own response schema. Empty when the response is not a list.
     */
    responseArrayPath: string;

    /** Whether the resolution came from a verified adapter rather than keyword matching. */
    verified: boolean;
}


/** A field the target operation accepts, flattened out of its request body schema. */
export interface TargetField {
    /** Dotted path inside the request body, e.g. 'params.title'. */
    path: string;

    /** Last path segment, used for name-based mapping suggestions. */
    name: string;

    /** Schema type when the invoker declares one. */
    type: string;
}


export function findAdapter(invokerName: string): TargetSystemAdapter | null {
    if (!invokerName) {
        return null;
    }

    const normalized = invokerName.trim().toLowerCase();

    return KNOWN_TARGET_ADAPTERS.find(adapter => adapter.invokerName.toLowerCase() === normalized) ?? null;
}
