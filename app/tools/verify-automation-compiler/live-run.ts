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

import {
    AutomationDefinition,
    createEmptyAutomationDefinition
} from '../../src/app/toolbox/automations/wizard/models/automation-definition.model';
import { AutomationCompilerService } from '../../src/app/toolbox/automations/wizard/services/automation-compiler.service';
import { TargetCatalogService } from '../../src/app/toolbox/automations/wizard/services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Runs what the compiler produces, and reads back what the engine did with it.
 *
 * The last of the four questions. The capture comparison asks whether the compiler still produces
 * what it produced before, live-check whether that resolves against an installation's interface
 * descriptions, live-save whether OpenCelium accepts it - and none of them can say whether the
 * engine does with it what it was meant to. A condition that is never evaluated looks exactly like
 * one that is; so does a reference that resolves to nothing.
 *
 * Two runs of the same automation, differing only in what the condition compares against: once so
 * it holds, once so it does not. What comes back is the execution tree OpenCelium logged, and with
 * it the answer - the `if` result, and the payload the request actually carried.
 *
 * ## Why this is safe to run against a live installation
 *
 * The write into the target system is replaced, after compiling and before sending, with a request
 * to a host that does not resolve. Nothing this runs can reach the target system: the automation
 * reads DataGerry, evaluates the condition, and at most fails to reach a hostname that has no
 * address. The connection and the scheduler are both deleted afterwards.
 *
 * Which is the point. A check that has to write into a production CMDB to prove a condition works
 * is a check nobody runs twice.
 *
 * ## Running it
 *
 * From app/:
 *
 *   node_modules/esbuild/bin/esbuild tools/verify-automation-compiler/live-run.ts \
 *     --bundle --platform=node --format=cjs \
 *     --alias:@angular/core=tools/verify-automation-compiler/stub-angular-core.js \
 *     --outfile=/tmp/oc/live-run.cjs --log-level=error
 *
 *   OC_BASE=$OC OC_TOKEN="$TOKEN" DG_DATA_DIR=/tmp/oc \
 *   RUN_TYPE_ID=10 RUN_FIELDS=name,manufacturer RUN_MATCH=jakob \
 *   node /tmp/oc/live-run.cjs
 *
 * RUN_TYPE_ID is an object type that holds at least one object - a type with none makes the loop
 * run zero times and the check prove nothing. RUN_FIELDS is that type's field names in the order it
 * declares them, because that order is the address of a value. RUN_MATCH is a piece of text the
 * first of those fields contains on at least one object.
 */
const dir = process.env['DG_DATA_DIR']!;
const base = process.env['OC_BASE']!;
const token = process.env['OC_TOKEN']!;
const typeId = Number(process.env['RUN_TYPE_ID'] ?? '');
const fields = (process.env['RUN_FIELDS'] ?? '').split(',').map(name => name.trim()).filter(Boolean);
const match = process.env['RUN_MATCH'] ?? '';

/** A host that does not resolve, so the write can only ever fail to happen. */
const NOWHERE = 'https://dg-live-run.invalid/hook';


async function call(method: string, path: string, body?: unknown): Promise<{ status: number; body: any }> {
    const response = await fetch(`${base}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: token },
        body: body === undefined ? undefined : JSON.stringify(body)
    });
    const text = await response.text();

    try {
        return { status: response.status, body: text ? JSON.parse(text) : null };
    } catch {
        return { status: response.status, body: text.slice(0, 400) };
    }
}


function connectors(): { internal: any; target: any } {
    const read = (file: string) => JSON.parse(fs.readFileSync(`${dir}/${file}`, 'utf8'));
    const invokers: any[] = read('invokers.json');
    const all: any[] = read('connectors.json');
    const byName = new Map(invokers.map(invoker => [invoker.name, invoker]));
    const full = (connector: any) => ({
        ...connector,
        invoker: byName.get(
            typeof connector.invoker === 'string' ? connector.invoker : connector.invoker?.name
        )
    });

    return {
        internal: full(all.find(candidate => `${candidate.title}`.includes('DataGerry'))),
        target: full(all.find(candidate => !`${candidate.title}`.includes('DataGerry')))
    };
}


/**
 * The automation under test, and the write taken out of it.
 *
 * Everything up to the condition is what the wizard would send. What the condition guards is not:
 * the request that would have gone to the target system becomes one that goes nowhere, carrying the
 * value the mapping resolved so the log can show whether it resolved at all.
 */
function connectionFor(shouldHold: boolean): { connection: any; expected: string } {
    const { internal, target } = connectors();
    const definition: AutomationDefinition = createEmptyAutomationDefinition();

    definition.name = `dg-live-run ${shouldHold ? 'TRUE' : 'FALSE'}`;
    definition.description = 'Live execution check. The write is replaced before sending. Safe to delete.';
    definition.direction = 'outgoing';
    definition.objectType = { typeId, name: 'checked', label: 'Checked' };
    definition.fields = [{ name: fields[0], label: fields[0], type: 'text' }];
    definition.target = {
        connectorId: target.connectorId,
        connectorTitle: target.title,
        invokerName: target.invoker?.name ?? '',
        operation: 'create',
        remoteObjectTypeId: '1'
    };
    definition.mapping = [
        { target: 'params.title', sources: [{ field: fields[0], origin: 'manual', confidence: 1 }] }
    ];
    definition.conditions = {
        combinator: 'and',
        negate: false,
        // The only difference between the two runs: text the field holds, or text it cannot.
        rules: [{ field: fields[0], operator: 'contains', value: shouldHold ? match : `${match}-nothing-holds-this` }]
    };

    const compiler = new AutomationCompilerService(new TargetCatalogService());
    const context = { internalConnector: internal, targetConnector: target, objectTypeFieldOrder: fields };
    const errors = compiler.validate(definition, context);

    if (errors.length > 0) {
        throw new Error(`the definition does not validate: ${errors.join(' ')}`);
    }

    const connection = compiler.compileForCreate(definition, context).payload.connection;
    const write = connection.fromConnector.methods.find((method: any) => method.index.startsWith('1_0_'));
    const reference = write.request.body.fields.params.title;
    const envelope = () => ({ type: 'object', format: 'json', data: 'raw', fields: {} });

    write.methodType = 'HTTP_REQUEST';
    write.name = 'POST';
    write.connector = null;
    write.request = {
        endpoint: NOWHERE,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        body: { type: 'object', format: 'json', data: 'raw', fields: { title: reference } }
    };
    write.response = {
        name: 'response',
        success: { status: '200', header: {}, body: envelope() },
        fail: { status: '500', header: {}, body: envelope() }
    };

    // The bindings wrote into a body field that is gone; a plain reference needs none of them.
    connection.fieldBinding = [];

    const node = connection.ui.workflowNodes.find((entry: any) => entry.index === write.index);

    node.type = 'system';
    node.data = { title: 'HTTP Request', subtitle: 'POST', kind: 'system' };

    return { connection, expected: reference };
}


/** The logged execution tree, flattened to what each element did. */
async function tree(elementId: string, into: any[] = []): Promise<any[]> {
    const { status, body } = await call('GET', `/execution/log/element/${elementId}/children`);

    for (const child of (status < 300 && Array.isArray(body) ? body : [])) {
        const details = await call('GET', `/execution/log/element/${child.id}/details`);

        into.push(details.status < 300 ? details.body : child);
        await tree(child.id, into);
    }

    return into;
}


async function runOnce(shouldHold: boolean): Promise<boolean> {
    const label = shouldHold ? 'holds   ' : 'does not';
    const { connection } = connectionFor(shouldHold);
    const created = await call('POST', '/connection', connection);
    const connectionId = created.body?.connectionId;

    if (created.status >= 300 || !connectionId) {
        console.log(`[${label}] POST /connection -> ${created.status}`, JSON.stringify(created.body).slice(0, 400));

        return false;
    }

    const scheduler = await call('POST', '/scheduler', {
        connectionId,
        title: connection.title,
        status: false,
        cronExp: '',
        debugMode: true
    });
    const schedulerId = scheduler.body?.schedulerId;

    let held: string | undefined;
    let payload: string | undefined;

    if (schedulerId) {
        await call('GET', `/scheduler/execute/${schedulerId}`);

        // The run is started, not awaited; the log appears once it is over.
        for (let attempt = 0; attempt < 20 && !held; attempt++) {
            await new Promise(resolve => setTimeout(resolve, 3000));

            const files = await call('GET', `/execution/log-files?connectionId=${connectionId}`);
            const name = files.body?.result?.[0];

            if (!name) {
                continue;
            }

            const roots = await call('GET', `/execution/logs/children?fileName=${encodeURIComponent(name)}`);
            const elements = await tree(roots.body?.[0]?.id ?? '');
            const gate = elements.find((element: any) => element.type === 'IF');
            const request = elements.find((element: any) => element.indexPath?.startsWith('1_0_'));

            held = gate?.segment?.result;
            payload = request?.segment?.request?.payload;
        }
    }

    console.log(`[${label}] connection ${connectionId}, if -> ${held ?? 'no result logged'}`
        + (payload ? `, sent ${payload}` : ', nothing sent'));

    if (schedulerId) {
        await call('DELETE', `/scheduler/${schedulerId}`);
    }

    await call('DELETE', `/connection/${connectionId}`);

    // What the run had to show: the condition decided, and a request went out only when it held.
    return held === String(shouldHold) && (shouldHold ? !!payload : !payload);
}


async function main(): Promise<void> {
    if (!Number.isFinite(typeId) || fields.length === 0 || !match) {
        console.log('FAIL - RUN_TYPE_ID, RUN_FIELDS and RUN_MATCH are all required');
        process.exit(1);
    }

    const holds = await runOnce(true);
    const doesNot = await runOnce(false);

    console.log(holds && doesNot ? '\nPASS' : '\nFAIL - the engine did not do what was compiled');
    process.exit(holds && doesNot ? 0 : 1);
}

main().catch(error => {
    console.log('FAIL -', error);
    process.exit(1);
});
