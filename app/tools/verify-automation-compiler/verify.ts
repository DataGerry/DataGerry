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
import * as fs from 'fs';
import * as path from 'path';

import { AutomationDefinition } from '../../src/app/toolbox/automations/wizard/models/automation-definition.model';
import { AutomationCompilerService } from '../../src/app/toolbox/automations/wizard/services/automation-compiler.service';
import { AutomationDefinitionCodecService } from '../../src/app/toolbox/automations/wizard/services/automation-definition-codec.service';
import { TargetCatalogService } from '../../src/app/toolbox/automations/wizard/services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Differences that are properties of how the two captures were taken rather than compiler faults.
 *
 * Keeping them listed rather than silently ignored means a new difference cannot hide behind them.
 */
interface AcceptedDifference {
    /** Reads a difference and says whether it is one of the known ones. */
    matches: (entry: { path: string; detail: string }) => boolean;
    reason: string;
}


/**
 * Differences that are properties of the captures rather than compiler faults.
 *
 * The loop-iterator entry is the one to read twice: these captures address the iterated collection
 * as `results[0]`, which reads the first source object on every pass instead of the one the loop is
 * on. It looks correct against a single test object and silently repeats itself against real data.
 * The lookup capture, taken later and corrected by hand, uses `results[i]`; the compiler follows it
 * and deliberately does not reproduce what the older two carry.
 */
const ACCEPTED_DIFFERENCES: ReadonlyArray<AcceptedDifference> = [
    {
        matches: entry => entry.detail.includes('[i]') && entry.detail.includes('[0]'),
        reason: 'the capture addresses the looped collection as [0]; the compiler uses the iterator'
    },
    {
        matches: entry => entry.path === 'description',
        reason: 'the business model has gained fields since the capture, so its block differs'
    },
    {
        // These two captures leave the loop's rule tree empty while carrying its expression; the
        // later capture of a connection holding a loop and three conditions
        // (OpenCelium_Connection_Update_With_IF_AND_LOOP.json) carries the `for` rule that expression
        // is drawn from. The editor rebuilds the expression out of that tree, so an empty one comes
        // back walking nothing - the compiler follows the later capture.
        matches: entry => /ui\.workflowNodes\.\d+\.data\.conditionConfig\.tree/.test(entry.path),
        reason: 'the capture leaves the loop rule tree empty; the compiler writes the `for` rule'
    }
];

const ACCEPTED_CREATE_DIFFERENCES: ReadonlyArray<AcceptedDifference> = [
    ...ACCEPTED_DIFFERENCES,
    {
        matches: entry => entry.path === 'connection.title' || entry.path === 'connection.name',
        reason: 'the create capture was taken from a differently named connection'
    },
    {
        matches: entry => entry.path === 'connection.description',
        reason: 'the create capture carries no description, so it holds no business model either'
    }
];


function readArg(name: string, fallback: string): string {
    const hit = process.argv.find(arg => arg.startsWith(`--${name}=`));

    return hit ? hit.slice(name.length + 3) : fallback;
}


/** Replaces generated identifiers so a fresh uuid does not read as a difference. */
function canonical(value: unknown): unknown {
    const json = JSON.stringify(value, (_key, val) => val === undefined ? null : val);

    return JSON.parse(
        json.replace(/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, '<UUID>')
    );
}


function trim(value: unknown): string {
    const text = JSON.stringify(value);

    return text && text.length > 160 ? `${text.slice(0, 160)}...` : String(text);
}


/** Every structural difference, keyed by dotted path. */
function diff(actual: any, expected: any, at = ''): Array<{ path: string; detail: string }> {
    if (JSON.stringify(actual) === JSON.stringify(expected)) {
        return [];
    }

    const bothObjects = actual && expected
        && typeof actual === 'object' && typeof expected === 'object'
        && Array.isArray(actual) === Array.isArray(expected);

    if (!bothObjects) {
        return [{
            path: at || '<root>',
            detail: `actual: ${trim(actual)}\n     expected: ${trim(expected)}`
        }];
    }

    const keys = new Set([...Object.keys(actual), ...Object.keys(expected)]);
    const out: Array<{ path: string; detail: string }> = [];

    for (const key of keys) {
        out.push(...diff(actual[key], expected[key], at ? `${at}.${key}` : key));
    }

    return out;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                              FIXTURES FROM A CAPTURE                                               */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Undoes what the compiler wrote into an operation, recovering the invoker's own definition.
 *
 * A connection no longer carries the invoker definitions it was built from, so they are recovered
 * from the methods instead: a mapped field holds a colour reference where the invoker holds an
 * empty string, and the read endpoint has gained the filter and limit the compiler appends.
 */
function unpatch(value: any): any {
    if (typeof value === 'string') {
        return value.startsWith('#') ? '' : value;
    }

    if (Array.isArray(value)) {
        return value.map(unpatch);
    }

    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, val]) => [key, unpatch(val)]));
    }

    return value;
}


function stripEndpointQuery(endpoint: string): string {
    const separator = endpoint.indexOf('?');

    return separator === -1 ? endpoint : endpoint.slice(0, separator);
}


/** The invoker operation a captured method was built from. */
function operationOf(method: any): any {
    const { responseId: _dropped, ...response } = method.response ?? {};
    const request = unpatch(method.request ?? {});

    request.endpoint = stripEndpointQuery(request.endpoint ?? '');

    return { name: method.name, type: '', request, response: unpatch(response) };
}


/**
 * The connector a captured method ran against, with the invoker recovered from that method.
 *
 * `lastTestPassed` is kept: the connector list carries it and the compiler passes it through, so
 * dropping it here would make the compiler look wrong for doing the right thing.
 */
function connectorOf(method: any): any {
    return {
        ...method.connector,
        invoker: { name: method.connector.invokerName, operations: [operationOf(method)] }
    };
}

/**
 * Prints one comparison and returns how many differences were not accounted for.
 *
 * Accepted differences are printed with their reason rather than dropped, so a new difference
 * cannot hide behind one that was already understood.
 */
function report(
    label: string,
    differences: Array<{ path: string; detail: string }>,
    accepted: ReadonlyArray<AcceptedDifference>
): number {
    const unexpected = differences.filter(entry => !accepted.some(rule => rule.matches(entry)));

    console.log(`${label}: ${differences.length} difference(s), ${unexpected.length} unexpected`);

    differences
        .filter(entry => !unexpected.includes(entry))
        .forEach(entry => {
            const reason = accepted.find(rule => rule.matches(entry))!.reason;
            console.log(`  = ${entry.path} (${reason})`);
        });

    unexpected.forEach(entry => console.log(`  - ${entry.path}\n     ${entry.detail}`));

    return unexpected.length;
}

/* ------------------------------------------------------------------------------------------------------------------ */

function main(): number {
    // Supplied by run.mjs, which knows where it lives; the bundle itself runs from a temp directory.
    const repoRoot = process.env['DG_REPO_ROOT']
        ? path.resolve(process.env['DG_REPO_ROOT'])
        : process.cwd();
    const first = JSON.parse(fs.readFileSync(
        readArg('create', path.join(repoRoot, 'OpenCelium_Connection_Create_Request.json')), 'utf8'
    ));
    const second = JSON.parse(fs.readFileSync(
        readArg('update', path.join(repoRoot, 'OpenCelium_Connection_Update_Request.json')), 'utf8'
    ));

    // Bound by shape rather than by file name: only the update body carries the connection's id.
    const referenceUpdate = second.connectionId !== undefined ? second : first;
    const referenceCreate = second.connectionId !== undefined ? first : second;

    // The business model rides along in the description, so the very automation that produced the
    // capture is the one compiled here - no hand-written definition to drift out of step with it.
    const codec = new AutomationDefinitionCodecService();
    const definition: AutomationDefinition | null = codec.decode(referenceUpdate.description).definition;

    if (!definition) {
        console.error('The update capture carries no dg-automation block, so there is nothing to compile.');
        console.error('Capture it from a connection the wizard saved.');

        return 1;
    }

    const [sourceMethod, targetMethod] = referenceUpdate.fromConnector.methods;
    const dataGerryConnector = connectorOf(sourceMethod);
    const targetConnector = connectorOf(targetMethod);

    const context = {
        internalConnector: definition.direction === 'outgoing' ? dataGerryConnector : targetConnector,
        targetConnector: definition.direction === 'outgoing' ? targetConnector : dataGerryConnector,
        objectTypeFieldOrder: definition.fields.map(field => field.name)
    };

    const compiler = new AutomationCompilerService(new TargetCatalogService());
    const errors = compiler.validate(definition, context);

    if (errors.length > 0) {
        console.error('validate() rejected the definition:');
        errors.forEach(error => console.error(`  - ${error}`));

        return 1;
    }

    const created = compiler.compileForCreate(definition, context);
    const updated = compiler.compileForUpdate(definition, context, referenceUpdate.connectionId);

    // The wizard encodes the business model into the description after compiling, so the same step
    // is repeated here - otherwise the block that travels in the capture would read as a difference.
    const description = codec.encode(definition.description, definition);
    created.payload.connection.description = description;
    updated.payload.description = description;

    if (created.warnings.length > 0) {
        console.log('warnings:');
        created.warnings.forEach(warning => console.log(`  - ${warning}`));
        console.log();
    }

    let failures = 0;

    const updateDiff = diff(canonical(updated.payload), canonical(referenceUpdate));
    const unexpectedUpdate = report('UPDATE (PUT /connections)', updateDiff, ACCEPTED_DIFFERENCES);
    failures += unexpectedUpdate;

    // The create capture is the same automation under a different name, and the scheduler half of
    // the request has no counterpart in it, so only the connection is compared.
    console.log();
    const createDiff = diff(canonical({ connection: created.payload.connection }), canonical({ connection: referenceCreate }));
    failures += report('CREATE (POST /schedulers)', createDiff, ACCEPTED_CREATE_DIFFERENCES);

    console.log(`\n${failures === 0 ? 'PASS' : `FAIL - ${failures} unexpected difference(s)`}`);

    return failures === 0 ? 0 : 1;
}

process.exit(main());
