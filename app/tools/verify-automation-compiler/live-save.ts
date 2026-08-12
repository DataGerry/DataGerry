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
 * Asks a running OpenCelium whether it accepts what the compiler produces.
 *
 * A different question again from the two checks beside it. The capture comparison asks whether the
 * compiler still produces what it produced before; live-check asks whether that resolves against
 * the interface descriptions an installation actually has. Neither can answer whether OpenCelium
 * takes the payload - only OpenCelium can, and only by being handed one.
 *
 * Which matters most for the parts no capture covers. A shape derived from a captured connection is
 * checked by construction; a shape that had to be worked out - a free request, a condition of the
 * user's own, a loop over a list an answer holds - is not checked by anything until it is saved.
 *
 * It creates a connection, reads it back, and deletes it again. Nothing is executed: acceptance is
 * what this answers, and running an automation would write into the target system.
 *
 * It talks to OpenCelium directly - `POST /connection`, not the `/rest/open_celium/schedulers` the
 * wizard uses, which is DataGerry's own path in front of it. Only the connection half is sent: the
 * scheduler beside it decides when an automation runs, and this is about what it would run.
 *
 * Usage, from app/:
 *
 *   OC_BASE=http://host:9090 OC_TOKEN="$TOKEN" DG_DATA_DIR=/tmp/oc node /tmp/oc/live-save.cjs
 *
 * DG_DATA_DIR holds invokers.json and connectors.json, as for live-check.
 */
const dir = process.env['DG_DATA_DIR']!;
const base = process.env['OC_BASE']!;
const token = process.env['OC_TOKEN']!;
const read = (file: string) => JSON.parse(fs.readFileSync(`${dir}/${file}`, 'utf8'));


function unwrap(value: any): any {
    if (Array.isArray(value)) {
        return value;
    }

    for (const key of ['_embedded', 'content', 'invokers', 'connectors']) {
        if (value && key in value) {
            return unwrap(value[key]);
        }
    }

    const lists = Object.values(value ?? {}).filter(Array.isArray);

    return lists[0] ?? [];
}


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


/** The automation under test: one of everything the captures do not cover. */
function definitionUnderTest(targetTitle: string, targetConnectorId: number): AutomationDefinition {
    const definition = createEmptyAutomationDefinition();

    definition.name = `dg-live-save ${new Date().toISOString().slice(0, 19)}`;
    definition.description = 'Created by live-save.ts to check acceptance. Safe to delete.';
    definition.direction = 'outgoing';
    definition.objectType = { typeId: 1, name: 'test', label: 'Test' };
    definition.fields = [{ name: 'text-98758', label: 'Title', type: 'text' }];
    definition.target = {
        connectorId: targetConnectorId,
        connectorTitle: targetTitle,
        invokerName: 'i-doit',
        operation: 'create',
        remoteObjectTypeId: '10'
    };
    definition.mapping = [
        { target: 'params.title', sources: [{ field: 'text-98758', origin: 'manual', confidence: 1 }] }
    ];
    definition.extras = [
        {
            id: 'extra-if',
            after: '1_0',
            kind: 'if',
            operation: '',
            condition: {
                left: '#C77E7E.(response).body.$.result.id',
                operator: 'NotNull',
                right: ''
            }
        },
        {
            id: 'extra-loop',
            after: 'extra-if',
            kind: 'loop',
            operation: '',
            loop: { list: '#FFCFB5.(response).body.$.results[*]', iterator: 'j' }
        },
        {
            id: 'extra-http',
            after: 'extra-loop',
            kind: 'http',
            operation: '',
            verb: 'POST',
            endpoint: 'https://example.invalid/hook',
            headers: { 'Content-Type': 'application/json' },
            body: { 'event.object': '#C77E7E.(response).body.$.result.id' }
        }
    ];

    return definition;
}


async function main(): Promise<void> {
    const invokers: any[] = unwrap(read('invokers.json'));
    const connectors: any[] = unwrap(read('connectors.json'));
    const byName = new Map(invokers.map(invoker => [invoker.name, invoker]));
    const full = (connector: any) => ({
        ...connector,
        invoker: byName.get(
            typeof connector.invoker === 'string' ? connector.invoker : connector.invoker?.name
        ) ?? connector.invoker
    });

    const target = full(connectors.find(candidate => candidate.invoker?.name === 'i-doit'
        || candidate.invoker === 'i-doit'));
    const internal = full(connectors.find(candidate => `${candidate.title}`.includes('DataGerry')));

    if (!target || !internal) {
        console.log('FAIL - this installation has no i-doit and DataGerry connector pair');
        process.exit(1);
    }

    const compiler = new AutomationCompilerService(new TargetCatalogService());
    const definition = definitionUnderTest(target.title, target.connectorId);
    const context = {
        internalConnector: internal,
        targetConnector: target,
        objectTypeFieldOrder: ['text-98758']
    };

    const errors = compiler.validate(definition, context);

    if (errors.length > 0) {
        console.log('FAIL - the definition does not validate:', errors);
        process.exit(1);
    }

    const { payload, warnings } = compiler.compileForCreate(definition, context);

    warnings.forEach(warning => console.log(`  warning: ${warning}`));

    // Written out first: when the server rejects a payload, the payload is what has to be read.
    fs.writeFileSync(`${dir}/live-save-payload.json`, JSON.stringify(payload, null, 2));

    if (process.env['OC_DRY']) {
        console.log(`wrote ${dir}/live-save-payload.json - nothing sent`);
        process.exit(0);
    }

    const created = await call('POST', '/connection', payload.connection);
    const connectionId = created.body?.connectionId ?? created.body?.connection?.connectionId;

    console.log(`POST /connection -> ${created.status}${connectionId ? ` (connection ${connectionId})` : ''}`);

    if (created.status >= 300 || !connectionId) {
        console.log(JSON.stringify(created.body).slice(0, 1500));
        process.exit(1);
    }

    // Read back rather than trusting the create: OpenCelium normalises what it stores, and what it
    // stored is what it would run.
    const stored = await call('GET', `/connection/${connectionId}`);
    const connection = stored.body?.connection ?? stored.body;
    const operators = connection?.fromConnector?.operators ?? [];
    const methods = connection?.fromConnector?.methods ?? [];

    console.log(`GET  /connection/${connectionId} -> ${stored.status}`);
    console.log('  indices:', [...methods, ...operators]
        .map((entry: any) => `${entry.index}:${entry.type ?? entry.methodType}`)
        .sort()
        .join(' '));

    operators.forEach((operator: any) =>
        console.log(`  ${operator.type} ${operator.index}: ${operator.expression}`));

    const free = methods.find((method: any) => method.methodType === 'HTTP_REQUEST');

    console.log('  free request:', free
        ? `${free.request?.method} ${free.request?.endpoint} body=${JSON.stringify(free.request?.body?.fields)}`
        : 'MISSING');

    const removed = await call('DELETE', `/connection/${connectionId}`);

    console.log(`DELETE /connection/${connectionId} -> ${removed.status}`);

    // The derived loop, the condition, and the loop the definition adds - and the free request that
    // runs inside all three.
    const kept = operators.length === 3 && !!free && removed.status < 300;

    console.log(kept ? '\nPASS' : '\nFAIL - what came back is not what was sent');
    process.exit(kept ? 0 : 1);
}

main().catch(error => {
    console.log('FAIL -', error);
    process.exit(1);
});
