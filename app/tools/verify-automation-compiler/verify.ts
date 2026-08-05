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

import {
    AutomationDefinition,
    createEmptyAutomationDefinition
} from '../../src/app/toolbox/automations/wizard/models/automation-definition.model';
import { AutomationCompilerService } from '../../src/app/toolbox/automations/wizard/services/automation-compiler.service';
import { TargetCatalogService } from '../../src/app/toolbox/automations/wizard/services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Differences that are properties of how the two captures were taken rather than compiler faults.
 *
 * Keeping them listed rather than silently ignored means a new difference cannot hide behind them.
 */
const ACCEPTED_UPDATE_DIFFERENCES: ReadonlyArray<{ path: string; reason: string }> = [
    {
        path: 'title',
        reason: 'the two capture files were saved under different names'
    },
    {
        path: 'toConnector.methods.0.label',
        reason: 'the update capture sends label: null where the create capture omits the key'
    },
    {
        path: 'toConnector.svgItems.1.entity.label',
        reason: 'same as toConnector.methods.0.label'
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


function main(): number {
    // Supplied by run.mjs, which knows where it lives; the bundle itself runs from a temp directory.
    const repoRoot = process.env['DG_REPO_ROOT']
        ? path.resolve(process.env['DG_REPO_ROOT'])
        : process.cwd();
    const flat = JSON.parse(fs.readFileSync(
        readArg('update', path.join(repoRoot, 'OpenCelium_Connection_Create_Request.json')), 'utf8'
    ));
    const wrapped = JSON.parse(fs.readFileSync(
        readArg('create', path.join(repoRoot, 'OpenCelium_Connection_Update_Request.json')), 'utf8'
    ));

    // Bound by shape: { connection, scheduler } is the create body, the flat object the update body.
    const referenceCreate = wrapped.connection ? wrapped : flat;
    const referenceUpdate = wrapped.connection ? flat : wrapped;

    const sourceConnector = {
        connectorId: referenceUpdate.fromConnector.connectorId,
        title: referenceUpdate.fromConnector.title,
        icon: referenceUpdate.fromConnector.icon ?? '',
        invoker: referenceCreate.connection.fromConnector.invoker
    };
    const dataGerryConnector = {
        connectorId: referenceUpdate.toConnector.connectorId,
        title: referenceUpdate.toConnector.title,
        icon: referenceUpdate.toConnector.icon ?? '',
        invoker: referenceCreate.connection.toConnector.invoker
    };

    const definition: AutomationDefinition = createEmptyAutomationDefinition();
    definition.name = referenceCreate.connection.title;
    definition.description = referenceCreate.connection.description ?? '';
    definition.direction = 'incoming';
    definition.objectType = { typeId: 1, name: 'hardware', label: 'Hardware' };
    definition.fields = [{ name: 'id', label: 'ID', type: 'text' }];
    definition.target = {
        connectorId: sourceConnector.connectorId,
        connectorTitle: sourceConnector.title,
        invokerName: sourceConnector.invoker.name,
        operation: 'create',
        remoteObjectTypeId: '10'
    };
    definition.mapping = [{ source: 'id', target: 'version', origin: 'auto', confidence: 1 }];
    definition.advanced.batchSize = 1;

    const context = {
        internalConnector: dataGerryConnector,
        targetConnector: sourceConnector,
        objectTypeFieldOrder: []
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

    if (created.warnings.length > 0) {
        console.log('warnings:');
        created.warnings.forEach(warning => console.log(`  - ${warning}`));
        console.log();
    }

    let failures = 0;

    const createDiff = diff(canonical(created.payload), canonical(referenceCreate));
    console.log(`CREATE (POST /schedulers): ${createDiff.length} difference(s)`);
    createDiff.forEach(entry => console.log(`  - ${entry.path}\n     ${entry.detail}`));
    failures += createDiff.length;

    const updateDiff = diff(canonical(updated.payload), canonical(referenceUpdate));
    const unexpected = updateDiff.filter(
        entry => !ACCEPTED_UPDATE_DIFFERENCES.some(accepted => accepted.path === entry.path)
    );

    console.log(`\nUPDATE (PUT /connections): ${updateDiff.length} difference(s), `
        + `${unexpected.length} unexpected`);
    ACCEPTED_UPDATE_DIFFERENCES.forEach(accepted => console.log(`  = ${accepted.path} (${accepted.reason})`));
    unexpected.forEach(entry => console.log(`  - ${entry.path}\n     ${entry.detail}`));
    failures += unexpected.length;

    console.log(`\n${failures === 0 ? 'PASS' : `FAIL - ${failures} unexpected difference(s)`}`);

    return failures === 0 ? 0 : 1;
}

process.exit(main());
