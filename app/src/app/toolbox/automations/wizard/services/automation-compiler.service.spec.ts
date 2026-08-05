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
import { AutomationDefinition, createEmptyAutomationDefinition } from '../models/automation-definition.model';
import { AutomationCompilerService, AutomationCompileContext } from './automation-compiler.service';
import { TargetCatalogService } from './target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Fixtures modelled on the reference payloads captured from a running installation
 * (OpenCelium_Connection_*_Request.json), reduced to the operations these tests exercise.
 *
 * The full-payload comparison against those files lives in
 * app/tools/verify-automation-compiler, which needs no browser. These specs lock in the
 * structural contract so a regression is caught without the capture files at hand.
 */
function idoitInvoker(): any {
    return {
        name: 'i-doit',
        description: 'i-doit',
        hint: '',
        icon: '',
        data: { url: 'http://example/src/jsonrpc.php', apikey: '' },
        auth: 'token',
        operations: [
            { name: 'login', type: 'test', request: {}, response: {} },
            {
                name: 'cmdb.objects.read',
                type: '',
                request: {
                    endpoint: '{url}',
                    method: 'POST',
                    header: { 'Content-Type': 'application/json' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: {
                            method: 'cmdb.objects.read',
                            params: {
                                filter: { sysid: '', type: [], title: '' },
                                apikey: '{apikey}',
                                limit: ''
                            }
                        }
                    }
                },
                response: {
                    success: {
                        status: '200',
                        body: {
                            type: 'object',
                            format: 'json',
                            data: 'raw',
                            fields: { result: [{ id: '', title: '', sysid: '' }], id: '' }
                        }
                    },
                    fail: { status: '200', body: null }
                }
            },
            {
                name: 'cmdb.object.create',
                type: '',
                request: {
                    endpoint: '{url}',
                    method: 'POST',
                    header: { 'Content-Type': 'application/json' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: {
                            method: 'cmdb.object.create',
                            params: { type: '', title: '', category: '', apikey: '{apikey}' }
                        }
                    }
                },
                response: {
                    success: { status: '200', body: { fields: { result: { id: '' } } } },
                    fail: { status: '200', body: null }
                }
            }
        ]
    };
}


function dataGerryInvoker(): any {
    return {
        name: 'DataGerryCloud',
        description: 'DataGerry',
        hint: '',
        icon: '',
        data: { url: '', username: '' },
        auth: 'basic',
        operations: [
            { name: 'GetCategories', type: 'test', request: {}, response: {} },
            {
                name: 'AddObject',
                type: '',
                request: {
                    endpoint: '{url}/rest/objects/',
                    method: 'POST',
                    header: { Authorization: '{token}' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: { type_id: '', version: '', active: '', fields: [] }
                    }
                },
                response: {
                    success: { status: '200', body: { type: 'array', format: 'json', data: 'raw', fields: {} } },
                    fail: { status: '401', body: null }
                }
            },
            {
                name: 'GetObjects',
                type: '',
                request: { endpoint: '{url}/rest/objects/', method: 'GET', header: {}, body: {} },
                response: {
                    success: {
                        status: '200',
                        body: { fields: { results: [{ public_id: '', fields: [] }], count: '' } }
                    },
                    fail: { status: '401', body: null }
                }
            }
        ]
    };
}


function context(): AutomationCompileContext {
    return {
        internalConnector: {
            connectorId: 9,
            title: 'DataGerryInternal',
            icon: '',
            invoker: dataGerryInvoker()
        },
        targetConnector: { connectorId: 10, title: 'i-doit Demo', icon: '', invoker: idoitInvoker() },
        objectTypeFieldOrder: ['hostname', 'serial']
    };
}


/** The reference scenario: i-doit is read, DataGerry is written. */
function incomingDefinition(): AutomationDefinition {
    const definition = createEmptyAutomationDefinition();
    definition.name = 'My Automation';
    definition.direction = 'incoming';
    definition.objectType = { typeId: 1, name: 'hardware', label: 'Hardware' };
    definition.fields = [{ name: 'id', label: 'ID', type: 'text' }];
    definition.target = {
        connectorId: 10,
        connectorTitle: 'i-doit Demo',
        invokerName: 'i-doit',
        operation: 'create',
        remoteObjectTypeId: '10'
    };
    definition.mapping = [{ source: 'id', target: 'version', origin: 'auto', confidence: 1 }];
    definition.advanced.batchSize = 1;

    return definition;
}


describe('AutomationCompilerService', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });

    /* --------------------------------------------------- VALIDATION -------------------------------------------------- */

    describe('validate', () => {
        it('accepts the reference scenario', () => {
            expect(compiler.validate(incomingDefinition(), context())).toEqual([]);
        });


        it('rejects a trigger the compiler cannot execute yet', () => {
            const definition = incomingDefinition();
            definition.trigger.type = 'webhook';

            expect(compiler.validate(definition, context())
                .some(error => error.includes('cannot be executed yet'))).toBeTrue();
        });


        it('requires a cron expression for a scheduled trigger', () => {
            const definition = incomingDefinition();
            definition.trigger = { type: 'scheduled', cronExp: '' };

            expect(compiler.validate(definition, context())
                .some(error => error.includes('cron expression'))).toBeTrue();
        });


        it('requires a name, an object type, fields, a target and a mapping', () => {
            const empty = createEmptyAutomationDefinition();
            const errors = compiler.validate(empty, context());

            expect(errors.some(error => error.includes('name'))).toBeTrue();
            expect(errors.some(error => error.includes('object type'))).toBeTrue();
            expect(errors.some(error => error.includes('at least one field'))).toBeTrue();
            expect(errors.some(error => error.includes('target system'))).toBeTrue();
        });


        it('reports when nothing has been mapped', () => {
            const definition = incomingDefinition();
            definition.mapping = [{ source: 'id', target: '', origin: 'auto', confidence: 0 }];

            expect(compiler.validate(definition, context())
                .some(error => error.includes('Map at least one field'))).toBeTrue();
        });
    });

    /* -------------------------------------------------- CONNECTION --------------------------------------------------- */

    describe('compileForCreate', () => {
        it('reads the source and writes the target according to the direction', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.connectorId).toBe(10);
            expect(payload.connection.fromConnector.methods[0].name).toBe('cmdb.objects.read');
            expect(payload.connection.toConnector.connectorId).toBe(9);
            expect(payload.connection.toConnector.methods[0].name).toBe('AddObject');
        });


        it('assigns the reference colours and execution indices', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[0].color).toBe('#FFCFB5');
            expect(payload.connection.fromConnector.methods[0].index).toBe('0');
            expect(payload.connection.toConnector.methods[0].color).toBe('#C77E7E');
            expect(payload.connection.toConnector.methods[0].index).toBe('0_0');
        });


        it('labels the read method and leaves the target method unlabelled', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[0].label).toBe('GetObjects');
            expect('label' in payload.connection.toConnector.methods[0]).toBeFalse();
        });


        it('wraps the target method in a loop over the source collection', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const loop = payload.connection.toConnector.operators[0];

            expect(loop.type).toBe('loop');
            expect(loop.expression).toBe('for {%#FFCFB5.(response).body.$.result[*]%}');
            expect(loop.iterator).toBe('i');
            expect(loop.condition).toBeNull();
        });


        it('writes the source reference into the target request body', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.toConnector.methods[0].request.body.fields.version)
                .toBe('#FFCFB5.(response).body.$.result[0].id');
        });


        it('records the same pair as a field binding with its enhancement script', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const binding = payload.connection.fieldBinding[0];

            expect(binding.from[0]).toEqual({
                color: '#FFCFB5',
                field: 'body.$.result[0].id',
                type: 'response'
            });
            expect(binding.to[0]).toEqual({ color: '#C77E7E', field: 'body.$.version', type: 'request' });
            expect(binding.enhancement.expertCode).toBe('RESULT_VAR = VAR_0;');
            expect(binding.enhancement.expertVar).toContain('#C77E7E.(request).body.$.version');
            expect(binding.enhancement.expertVar).toContain('#FFCFB5.(response).body.$.result[0].id');
        });


        it('restricts the read to the selected object type and prunes unused filter keys', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const params = payload.connection.fromConnector.methods[0].request.body.fields.params;

            expect(params.filter).toEqual({ type: ['10'] });
        });


        it('applies the batch size as the read operation page size', () => {
            const definition = incomingDefinition();
            definition.advanced.batchSize = 250;

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[0].request.body.fields.params.limit).toBe('250');
        });


        it('omits the connector titles and sends id 0', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect('title' in payload.connection.fromConnector).toBeFalse();
            expect('title' in payload.connection.toConnector).toBeFalse();
            expect(payload.connection.id).toBe(0);
        });


        it('builds the visual graph with an arrow from the loop to the method', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.svgItems[0].id).toBe('fromConnector_0');
            expect(payload.connection.toConnector.svgItems[0].id).toBe('toConnector_0');
            expect(payload.connection.toConnector.svgItems[1].id).toBe('toConnector_0_0');
            expect(payload.connection.toConnector.arrows).toEqual([
                { from: 'toConnector_0', to: 'toConnector_0_0' }
            ]);
        });


        it('gives a method svgItem the invoker but no error block, and the reverse for methods', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const entity = payload.connection.fromConnector.svgItems[0].entity;

            expect(entity.invoker).toBeTruthy();
            expect('error' in entity).toBeFalse();
            expect(payload.connection.fromConnector.methods[0].error).toEqual({ hasError: false, messages: [] });
            expect('invoker' in payload.connection.fromConnector.methods[0]).toBeFalse();
        });


        it('derives the scheduler from the trigger and the advanced settings', () => {
            const definition = incomingDefinition();
            definition.trigger = { type: 'scheduled', cronExp: '0 2 * * *' };
            definition.advanced.loggingEnabled = true;
            definition.active = false;

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.scheduler).toEqual({
                title: 'My Automation',
                debugMode: true,
                status: 0,
                cronExp: '0 2 * * *'
            });
        });


        it('sends no cron expression for a manual trigger', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.scheduler.cronExp).toBe('');
            expect(payload.scheduler.status).toBe(1);
        });
    });

    /* ---------------------------------------------------- UPDATE ----------------------------------------------------- */

    describe('compileForUpdate', () => {
        it('carries the connector titles and repeats the connection id', () => {
            const { payload } = compiler.compileForUpdate(incomingDefinition(), context(), 16);

            expect(payload.fromConnector.title).toBe('i-doit Demo');
            expect(payload.toConnector.title).toBe('DataGerryInternal');
            expect(payload.id).toBe(16);
            expect(payload.connectionId).toBe(16);
        });


        it('does not resend the connector credentials', () => {
            const { payload } = compiler.compileForUpdate(incomingDefinition(), context(), 16);

            expect(payload.fromConnector.invoker.data).toBe('');
            expect(payload.fromConnector.invoker.auth).toBe('');
            expect(payload.toConnector.invoker.data).toBe('');
            expect(payload.fromConnector.svgItems[0].entity.invoker.data).toBe('');
        });


        it('leaves the caller\'s connector objects untouched', () => {
            const shared = context();

            compiler.compileForUpdate(incomingDefinition(), shared, 16);

            expect(shared.targetConnector.invoker.auth).toBe('token');
            expect(shared.internalConnector.invoker.auth).toBe('basic');
        });
    });

    /* -------------------------------------------------- DIRECTIONS --------------------------------------------------- */

    describe('outgoing automations', () => {
        function outgoingDefinition(): AutomationDefinition {
            const definition = incomingDefinition();
            definition.direction = 'outgoing';
            definition.fields = [
                { name: 'hostname', label: 'Hostname', type: 'text' },
                { name: 'serial', label: 'Serial', type: 'text' }
            ];
            definition.mapping = [{ source: 'serial', target: 'params.title', origin: 'manual', confidence: 1 }];

            return definition;
        }


        it('reads DataGerry and writes the foreign system', () => {
            const { payload } = compiler.compileForCreate(outgoingDefinition(), context());

            expect(payload.connection.fromConnector.connectorId).toBe(9);
            expect(payload.connection.fromConnector.methods[0].name).toBe('GetObjects');
            expect(payload.connection.toConnector.connectorId).toBe(10);
        });


        it('addresses a DataGerry field by its position in the object type', () => {
            const { payload } = compiler.compileForCreate(outgoingDefinition(), context());

            // 'serial' is the second field of the type, so it is fields[1].value.
            expect(payload.connection.fieldBinding[0].from[0].field)
                .toBe('body.$.results[0].fields[1].value');
        });


        it('warns that DataGerry fields are addressed positionally', () => {
            const { warnings } = compiler.compileForCreate(outgoingDefinition(), context());

            expect(warnings.some(warning => warning.includes('position in the object type'))).toBeTrue();
        });


        it('skips a mapped field that is not part of the object type', () => {
            const definition = outgoingDefinition();
            definition.mapping = [
                { source: 'not_in_type', target: 'params.title', origin: 'manual', confidence: 1 },
                { source: 'serial', target: 'params.category', origin: 'manual', confidence: 1 }
            ];

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fieldBinding.length).toBe(1);
            expect(warnings.some(warning => warning.includes('not_in_type'))).toBeTrue();
        });
    });

    /* -------------------------------------------------- CONDITIONS ---------------------------------------------------- */

    describe('conditions', () => {
        it('compiles rules into the loop condition and mirrors them in ui.operators', () => {
            const definition = incomingDefinition();
            definition.conditions = {
                combinator: 'and',
                negate: false,
                rules: [
                    { field: 'title', operator: 'contains', value: 'srv' },
                    { field: 'sysid', operator: 'is_not_empty', value: '' }
                ]
            };

            const { payload, warnings } = compiler.compileForCreate(definition, context());
            const loop = payload.connection.toConnector.operators[0];

            expect(loop.condition).toContain('.includes("srv")');
            expect(loop.condition).toContain(' && ');
            expect(payload.connection.ui.operators.length).toBe(2);
            expect(payload.connection.ui.operators[1].items.length).toBe(2);
            expect(warnings.some(warning => warning.includes('condition'))).toBeTrue();
        });


        it('negates the whole expression when the group is negated', () => {
            const definition = incomingDefinition();
            definition.conditions = {
                combinator: 'or',
                negate: true,
                rules: [{ field: 'title', operator: 'equals', value: 'x' }]
            };

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.toConnector.operators[0].condition?.startsWith('!')).toBeTrue();
        });
    });

    /* ------------------------------------------------- UI OPERATORS --------------------------------------------------- */

    it('mirrors the loop as a rule-builder group', () => {
        const { payload } = compiler.compileForCreate(incomingDefinition(), context());
        const group = payload.connection.ui.operators[0];

        expect(group.id).toBe(payload.connection.toConnector.operators[0].uiId);
        expect(group.items[0].properties.operator).toBe('for');
        expect(group.items[0].properties.leftField).toBe('{%#FFCFB5.(response).body.$.result[*]%}');
    });


    it('marks the connection as an expert-mode, editable connection', () => {
        const { payload } = compiler.compileForCreate(incomingDefinition(), context());

        expect(payload.connection.template).toEqual({ mode: 'expert', templateId: -1, label: '' });
        expect(payload.connection.readOnly).toBeFalse();
        expect(payload.connection.categoryId).toBeNull();
    });
});
