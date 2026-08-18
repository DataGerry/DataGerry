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
import {
    AutomationDefinition,
    createEmptyAutomationDefinition
} from '../../../models/automation-definition.model';
import { OcConnection } from '../../../models/opencelium-connection.model';
import { referenceLabel, tokensOf, WizardStepFlowComponent } from './wizard-step-flow.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The component reads the compiled connection and writes the definition, and holds no dependencies
 * of its own - so it is exercised directly, with a connection shaped like the ones the compiler
 * produces and the captures show.
 *
 * What is worth pinning down here is everything that cannot be seen by looking at the payload: which
 * rows the sequence shows, which step a row belongs to once several have been added, and which
 * element of a collection a value offered to a step actually points at.
 */
function connection(extra: Partial<OcConnection> = {}): OcConnection {
    return {
        title: 'Sync',
        name: 'Sync',
        description: '',
        fieldBinding: [],
        fromConnector: {
            connectorId: -1,
            title: 'DEFAULT',
            methods: [
                {
                    id: 'method-0',
                    name: 'Get Objects',
                    index: '0',
                    methodType: 'CONNECTOR',
                    dataAggregator: null,
                    color: '#FFCFB5',
                    connector: { connectorId: 3, title: 'DataGerry', icon: null, invokerName: 'DataGerry' },
                    request: { endpoint: '{url}/rest/objects/', method: 'GET', header: {}, body: {} },
                    response: {
                        success: {
                            status: '200',
                            body: {
                                fields: {
                                    count: '',
                                    results: [{
                                        public_id: '',
                                        fields: [{ name: '', value: '' }]
                                    }]
                                }
                            }
                        }
                    }
                },
                {
                    id: 'method-1',
                    name: 'cmdb.object.create',
                    index: '1_0',
                    methodType: 'CONNECTOR',
                    dataAggregator: null,
                    color: '#C77E7E',
                    connector: { connectorId: 10, title: 'i-doit', icon: null, invokerName: 'i-doit' },
                    request: {
                        endpoint: '{url}',
                        method: 'POST',
                        header: { 'Content-Type': 'application/json' },
                        body: { fields: { params: { title: '#FFCFB5.(response).body.$.results[i].fields[0].value' } } }
                    },
                    response: { success: { status: '200', body: { fields: { result: { id: '' } } } } }
                }
            ],
            operators: [{
                id: 'loop-0',
                index: '1',
                type: 'loop',
                dataAggregator: null,
                expression: 'for {%#FFCFB5.(response).body.$.results[*]%}',
                iterator: 'i'
            }]
        },
        toConnector: null,
        ui: { viewport: { x: 0, y: 0, zoom: 1 }, workflowNodes: [], workflowEdges: [], flowcharts: [], flowchartEdges: [] },
        ...extra
    };
}


function definitionFor(): AutomationDefinition {
    const definition = createEmptyAutomationDefinition();

    definition.direction = 'outgoing';
    definition.objectType = { typeId: 1, name: 'server', label: 'Server' };
    definition.fields = [{ name: 'hostname', label: 'Hostname', type: 'text' }];
    definition.target = {
        connectorId: 10,
        connectorTitle: 'i-doit',
        invokerName: 'i-doit',
        operation: 'create',
        remoteObjectTypeId: '10'
    };

    return definition;
}


describe('WizardStepFlowComponent', () => {
    let component: WizardStepFlowComponent;

    /** Stands in for the host: it recompiles on every change, which is a new connection object. */
    function settle(next: OcConnection = connection()): void {
        component.connection = next;
        component.ngDoCheck();
    }


    beforeEach(() => {
        component = new WizardStepFlowComponent();
        component.definition = definitionFor();
        component.dataGerryFields = [
            { name: 'hostname', label: 'Hostname', type: 'text' },
            { name: 'serial', label: 'Serial', type: 'text' }
        ];
        settle();
    });

    /* ---------------------------------------------------- SEQUENCE -------------------------------------------------- */

    describe('the sequence', () => {
        it('leaves out what nobody can act on', () => {
            // The read on DataGerry's side and the loop over its objects are the automation itself.
            expect(component.steps.map(step => step.index)).toEqual(['1_0']);
        });


        it('shows a loop and a condition the user added, in the order they run', () => {
            const withContainers = connection();

            withContainers.fromConnector.operators.push(
                {
                    id: 'if-extra-1',
                    index: '1_1',
                    type: 'if',
                    dataAggregator: null,
                    expression: '({%#C77E7E.(response).body.$.result.id%} NotNull)',
                    iterator: null
                },
                {
                    id: 'loop-extra-2',
                    index: '1_1_0',
                    type: 'loop',
                    dataAggregator: null,
                    expression: 'for {%#FFCFB5.(response).body.$.results[i].fields[*]%}',
                    iterator: 'j'
                }
            );
            settle(withContainers);

            expect(component.steps.map(step => step.index)).toEqual(['1_0', '1_1', '1_1_0']);
            expect(component.steps.map(step => step.kind)).toEqual(['call', 'if', 'loop']);

            // Read at a glance: the reference is worth no more than its last segment here.
            expect(component.steps[1].detail).toBe('id NotNull');
            expect(component.steps[2].depth).toBeGreaterThan(component.steps[1].depth);
        });


        /*
         * A condition and a loop's list are references too, and were the last places still showing
         * the whole route. They are cut the same way as a request value so a field is called the
         * same thing wherever it appears.
         */
        it('marks the reference inside a condition instead of spelling out its route', () => {
            const withContainers = connection();
            withContainers.fromConnector.operators.push(
                {
                    id: 'if-extra-1',
                    index: '1_1',
                    type: 'if',
                    dataAggregator: null,
                    expression: '({%#FFCFB5.(response).body.$.results[i].id%} NotNull)',
                    iterator: null
                }
            );
            settle(withContainers);

            const condition = component.steps.find(step => step.kind === 'if')!;
            const marked = condition.detailTokens!.filter(token => token.reference);

            expect(marked.map(token => token.label)).toEqual(['id']);
            expect(marked[0].text).toBe('{%#FFCFB5.(response).body.$.results[i].id%}');
            // The parentheses around the whole thing say nothing, so they are not shown; what is
            // left beside the reference is the comparison itself.
            expect(condition.detailTokens!.filter(token => !token.reference)
                .map(token => token.text).join('')).toBe(' NotNull');
        });


        it('marks the list a loop walks the same way', () => {
            const withContainers = connection();
            withContainers.fromConnector.operators.push(
                {
                    id: 'loop-extra-1',
                    index: '1_1',
                    type: 'loop',
                    dataAggregator: null,
                    expression: 'for {%#FFCFB5.(response).body.$.results[i].fields[*]%}',
                    iterator: 'j'
                }
            );
            settle(withContainers);

            const loop = component.steps.find(step => step.kind === 'loop')!;

            expect(loop.expressionTokens!.map(token => token.label)).toEqual(['for ', 'fields']);
            expect(loop.expressionTokens![1].reference).toBeTrue();
        });


        /* A call has no reference in its subtitle, but the row renders tokens either way. */
        it('gives a call a single plain token so every row is drawn the same', () => {
            settle(connection());

            const call = component.steps.find(step => step.kind === 'call')!;

            expect(call.detailTokens).toEqual([
                { text: call.detail, reference: false, label: call.detail }
            ]);
        });
    });

    /* ----------------------------------------------------- VALUES --------------------------------------------------- */

    describe('the values a step can be given', () => {
        it('offers only what has already answered', () => {
            component.openStep = 'method-1';
            component.ngDoCheck();

            const groups = new Set(component.valueSources.map(source => source.group));

            // The write itself has not run when it is being filled in.
            expect(groups.has('i-doit · cmdb.object.create')).toBeFalse();
            expect(groups.has('DataGerry · Get Objects')).toBeTrue();
        });


        it('addresses the walked collection by its iterator and everything else by position', () => {
            component.openStep = 'method-1';
            component.ngDoCheck();

            const labels = component.valueSources.map(source => source.label);

            // results is what the loop walks; the fields inside one object are not walked by anything.
            expect(labels).toContain('results[i].public_id');
            expect(labels).toContain('results[i].fields[0].value');
            expect(labels).toContain('count');
        });


        it('names the DataGerry fields, which the payload cannot', () => {
            component.openStep = 'method-1';
            component.ngDoCheck();

            const serial = component.valueSources.find(source => source.label === 'Serial');

            // Second field of the type, so the second entry of the object's field list.
            expect(serial?.reference).toBe('#FFCFB5.(response).body.$.results[i].fields[1].value');
            expect(serial?.group).toBe('DataGerry fields');
        });


        it('keeps collections apart from values, because only a loop can use one', () => {
            component.openStep = 'method-1';
            component.ngDoCheck();

            expect(component.listSources.map(source => source.label)).toContain('results[*]');
            expect(component.plainSources.some(source => source.label.endsWith('[*]'))).toBeFalse();
        });


        it('reads a nested list by the iterator of the loop that walks it', () => {
            const nested = connection();

            nested.fromConnector.operators.push({
                id: 'loop-extra-2',
                index: '1_1',
                type: 'loop',
                dataAggregator: null,
                expression: 'for {%#FFCFB5.(response).body.$.results[i].fields[*]%}',
                iterator: 'j'
            });
            nested.fromConnector.methods.push({
                ...nested.fromConnector.methods[1],
                id: 'method-extra-3',
                index: '1_1_0'
            });
            settle(nested);

            component.openStep = 'method-extra-3';
            component.ngDoCheck();

            const labels = component.valueSources.map(source => source.label);

            expect(labels).toContain('results[i].fields[j].value');
            expect(labels).not.toContain('results[i].fields[0].value');
        });
    });

    /* ----------------------------------------------------- EDITING -------------------------------------------------- */

    describe('editing a call', () => {
        function withExtras(): OcConnection {
            const next = connection();

            next.fromConnector.methods.push({
                ...next.fromConnector.methods[1],
                id: 'method-extra-1',
                index: '1_1',
                name: 'cmdb.category.create'
            });

            return next;
        }


        beforeEach(() => {
            component.definition.extras = [{
                id: 'extra-1',
                after: '1_0',
                kind: 'operation',
                operation: 'cmdb.category.create'
            }];
            settle(withExtras());
        });


        it('keeps the values of an added call on the entry, not on its position', () => {
            component.openStep = 'method-extra-1';
            component.ngDoCheck();
            component.onEdit(component.selected!, 'headers', 'X-Token', 'abc');

            expect(component.definition.extras[0].headers).toEqual({ 'X-Token': 'abc' });
            expect(component.definition.overrides['1_1']).toBeUndefined();
        });


        it('keeps a correction to a call the assistant built on its position', () => {
            component.openStep = 'method-1';
            component.ngDoCheck();
            component.onEdit(component.selected!, 'body', 'params.type', '10');

            expect(component.definition.overrides['1_0'].body).toEqual({ 'params.type': '10' });
            expect(component.definition.extras[0].body).toBeUndefined();
        });


        it('takes a value back out again', () => {
            component.openStep = 'method-extra-1';
            component.ngDoCheck();

            const step = component.selected!;

            component.onEdit(step, 'body', 'params.title', 'x');
            expect(component.isOwn(step, 'body', 'params.title')).toBeTrue();

            component.onRemovePair(step, 'body', 'params.title');
            expect(component.isOwn(step, 'body', 'params.title')).toBeFalse();
        });


        it('finds the entry behind a row even after another was added before it', () => {
            component.definition.extras = [
                { id: 'extra-0', after: '1_0', kind: 'operation', operation: 'first' },
                { id: 'extra-1', after: '1_0', kind: 'operation', operation: 'cmdb.category.create' }
            ];

            const next = withExtras();

            // The compiler names a node after the entry, so the row that moved is still traceable.
            next.fromConnector.methods.push({
                ...next.fromConnector.methods[1],
                id: 'method-extra-0',
                index: '1_2',
                name: 'first'
            });
            settle(next);

            component.openStep = 'method-extra-1';
            component.ngDoCheck();
            component.onEdit(component.selected!, 'headers', 'X-Token', 'abc');

            expect(component.definition.extras.find(extra => extra.id === 'extra-1')?.headers)
                .toEqual({ 'X-Token': 'abc' });
        });


        it('keeps a pair being typed while something else on the call is edited', () => {
            component.openStep = 'method-extra-1';
            component.ngDoCheck();
            component.draft.headers = { key: 'X-Token', value: '' };

            // Editing elsewhere recompiles the connection, which must not empty what is half typed.
            component.onEdit(component.selected!, 'body', 'params.title', 'x');
            settle(withExtras());

            expect(component.draft.headers.key).toBe('X-Token');
        });
    });

    /* ------------------------------------------------- ADDING STEPS ------------------------------------------------- */

    describe('adding and removing steps', () => {
        it('lifts what was inside a removed step up to where it stood', () => {
            component.definition.extras = [
                { id: 'extra-if', after: '1_0', kind: 'if', operation: '', condition: { left: '#x', operator: '=', right: '1' } },
                { id: 'extra-call', after: 'extra-if', kind: 'operation', operation: 'cmdb.object.update' }
            ];

            const next = connection();

            next.fromConnector.operators.push({
                id: 'if-extra-if',
                index: '1_1',
                type: 'if',
                dataAggregator: null,
                expression: '({%#x%} = \'1\')',
                iterator: null
            });
            settle(next);

            component.openStep = 'if-extra-if';
            component.ngDoCheck();
            component.onRemoveCall(component.selected!);

            expect(component.definition.extras.map(extra => extra.id)).toEqual(['extra-call']);

            // Not left pointing at a step that is gone: it runs where the condition used to.
            expect(component.definition.extras[0].after).toBe('1_0');
        });


        it('hands a new loop a name no other loop is using', () => {
            const next = connection();

            next.fromConnector.operators.push({
                id: 'loop-extra-1',
                index: '1_1',
                type: 'loop',
                dataAggregator: null,
                expression: 'for {%#FFCFB5.(response).body.$.results[i].fields[*]%}',
                iterator: 'j'
            });
            settle(next);

            component.openStep = 'method-1';
            component.ngDoCheck();
            component.onChooseKind('loop');
            component.loopList = '#FFCFB5.(response).body.$.results[*]';
            component.onSaveLoop();

            // 'i' belongs to the loop over the objects, 'j' to the one already there.
            expect(component.definition.extras[0].loop?.iterator).toBe('k');
        });
    });
});


/*
 * A reference carries its whole route to a value and only its last segment means anything to a
 * reader. These pin the cut, because getting it wrong shows the wrong field name against the right
 * value - which is worse than showing the route.
 */
describe('value tokens', () => {

    it('shows a reference by the field it points at', () => {
        const tokens = tokensOf('#FFCFB5.(response).body.$.results[i].fields[0].value');

        expect(tokens.length).toBe(1);
        expect(tokens[0].reference).toBeTrue();
        expect(tokens[0].label).toBe('value');
        expect(tokens[0].text).toBe('#FFCFB5.(response).body.$.results[i].fields[0].value');
    });


    it('drops an index from the name but keeps it in the reference', () => {
        const [token] = tokensOf('#FFCFB5.(response).body.$.result[0]');

        expect(token.label).toBe('result');
        expect(token.text).toBe('#FFCFB5.(response).body.$.result[0]');
    });


    /* An Authorization header is the word Bearer and then a token, so a value is not one or other. */
    it('keeps the text around a reference', () => {
        const tokens = tokensOf('Bearer #C77E7E.(response).body.$.token');

        expect(tokens.map(token => token.reference)).toEqual([false, true]);
        expect(tokens[0].text).toBe('Bearer ');
        expect(tokens[1].label).toBe('token');
    });


    it('reads the wrapped spelling an expression uses', () => {
        const [token] = tokensOf('{%#FFCFB5.(response).body.$.results[i].type_id%}');

        expect(token.reference).toBeTrue();
        expect(token.label).toBe('type_id');
    });


    it('leaves a plain value alone', () => {
        const tokens = tokensOf('application/json');

        expect(tokens.length).toBe(1);
        expect(tokens[0].reference).toBeFalse();
        expect(tokens[0].label).toBe('application/json');
    });


    it('answers with nothing for an empty value, so the row can say so', () => {
        expect(tokensOf('')).toEqual([]);
    });


    it('falls back to the whole reference when there is no segment to take', () => {
        expect(referenceLabel('#FFCFB5.(response)')).toBe('(response)');
    });
});


describe('WizardStepFlowComponent editing', () => {

    it('opens one value at a time', () => {
        const component = new WizardStepFlowComponent();

        component.startEditing('body', 'params.title');
        expect(component.isEditing('body', 'params.title')).toBeTrue();

        component.startEditing('headers', 'Authorization');
        expect(component.isEditing('body', 'params.title')).toBeFalse();
        expect(component.isEditing('headers', 'Authorization')).toBeTrue();
    });


    it('closes on demand, which is what a blur does', () => {
        const component = new WizardStepFlowComponent();

        component.startEditing('endpoint', '');
        component.stopEditing();

        expect(component.isEditing('endpoint', '')).toBeFalse();
    });


    /* Keys from different parts must not collide - both a header and a body field may be `id`. */
    it('tells a header apart from a body field of the same name', () => {
        const component = new WizardStepFlowComponent();

        component.startEditing('headers', 'id');

        expect(component.isEditing('body', 'id')).toBeFalse();
    });
});
