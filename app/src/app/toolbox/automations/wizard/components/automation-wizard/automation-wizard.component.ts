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
import { Component, inject, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { combineLatest, finalize } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { WizardStep } from 'src/app/core/components/base/wizard-stepper/wizard-stepper.component';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { environment } from 'src/environments/environment';

import { AutomationsService } from '../../../services/automations.service';
import { ConnectorsService } from '../../../connectors/services/connectors.service';
import { InternalConnectorHelperService } from '../../../connectors/services/internal-connector-helper.service';
import {
    AutomationDefinition,
    AutomationField,
    AutomationSystemField,
    createEmptyAutomationDefinition,
    describeAutomation,
    findSystemField,
    mappedSources,
    requiresMatching,
    systemFieldsFor
} from '../../models/automation-definition.model';
import {
    furthestReachableGroup,
    isGroupComplete,
    WizardGroup,
    WIZARD_GROUPS,
    WIZARD_GROUP_COUNT
} from '../../models/automation-wizard-step.model';
import { OcConnection } from '../../models/opencelium-connection.model';
import { ResolvedOperation, TargetField } from '../../models/target-catalog.model';
import { AutomationCompilerService, AutomationCompileContext } from '../../services/automation-compiler.service';
import { AutomationDefinitionCodecService } from '../../services/automation-definition-codec.service';
import { AutomationFieldMappingService } from '../../services/automation-field-mapping.service';
import { SelectableTargetSystem, TargetCatalogService } from '../../services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Title of the connector that represents DataGerry itself. */
const INTERNAL_CONNECTOR_TITLE = 'DataGerryInternal';

/**
 * The Automation Wizard.
 *
 * Replaces the embedded OpenCelium connection editor: users pick an object type, its fields, a target
 * system and an action, and the technical connection JSON is compiled from that. This component owns
 * the whole business model and hands slices to the step components, mirroring how
 * cmdb-license-activation-workflow drives its steps.
 */
@Component({
    selector: 'app-automation-wizard',
    templateUrl: './automation-wizard.component.html',
    styleUrls: ['./automation-wizard.component.scss'],
    standalone: false
})
export class AutomationWizardComponent implements OnInit {

    private readonly route = inject(ActivatedRoute);
    private readonly router = inject(Router);
    private readonly automationsService = inject(AutomationsService);
    private readonly connectorsService = inject(ConnectorsService);
    private readonly typeService = inject(TypeService);
    private readonly objectService = inject(ObjectService);
    private readonly toast = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly internalConnectorHelper = inject(InternalConnectorHelperService);
    private readonly compiler = inject(AutomationCompilerService);
    private readonly catalog = inject(TargetCatalogService);
    private readonly codec = inject(AutomationDefinitionCodecService);
    private readonly mapper = inject(AutomationFieldMappingService);

    public readonly WizardGroup = WizardGroup;
    public readonly groups = WIZARD_GROUPS;
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** The stepper's model. Fixed for the lifetime of the wizard, so it is built once. */
    public readonly steps: WizardStep[] = WIZARD_GROUPS.map(group => ({
        title: group.title,
        subtitle: group.subtitle,
        icon: group.icon
    }));

    public mode: 'create' | 'edit' = 'create';
    public currentGroup: WizardGroup = WizardGroup.TRIGGER;
    public definition: AutomationDefinition = createEmptyAutomationDefinition();

    /** Reference data loaded once and shared with the steps. */
    public objectTypes: CmdbType[] = [];
    public selectedType: CmdbType | null = null;
    public availableFields: AutomationField[] = [];
    public targetSystems: SelectableTargetSystem[] = [];
    public targetFields: TargetField[] = [];

    /**
     * State derived from the definition, recomputed in refresh() rather than read through getters.
     *
     * A getter is re-evaluated on every change detection run, and these all return fresh arrays and
     * strings. Handed to a child as an input that means the child sees a changed input several times
     * per second - which is what made the mapping step, with one dropdown per field, unusable.
     */
    public sourceFields: AutomationField[] = [];
    public systemFields: AutomationSystemField[] = [];
    public readableDescription = '';

    /** Target field names the lookup can search by, and whether a lookup happens at all. */
    public matchableTargets: string[] = [];
    public matchingRelevant = false;

    /** Operation names of the target system, for a call the user adds to the sequence. */
    public targetOperations: string[] = [];

    /** Compilation results, recomputed whenever the definition changes. */
    public validationErrors: string[] = [];
    public compileWarnings: string[] = [];
    public compiledPreview = '';

    /**
     * The compiled connection itself, so the sequence step can show the calls rather than describe
     * them. Null while the definition does not compile, which is what that step then says.
     */
    public compiledConnection: OcConnection | null = null;

    /** Sample values for the test step, keyed by DataGerry field name. */
    public sampleValues: Record<string, string> = {};
    public sampleLoading = false;
    public sampleObjectId: number | null = null;

    /** Set in edit mode; drives PUT instead of POST. */
    public connectionId: number | null = null;
    private schedulerId: number | null = null;
    private existingConnection: any = null;

    /**
     * True when an existing automation carries no business model - it was built with the old editor.
     * The wizard then shows the technical view read-only instead of guessing what the user meant.
     */
    public legacyWithoutDefinition = false;

    private internalConnector: any = null;
    private connectors: any[] = [];
    private samplePage = 1;

    /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnInit(): void {
        this.mode = (this.route.snapshot.data['mode'] ?? 'create') as 'create' | 'edit';

        this.internalConnectorHelper.checkInternalConnector({
            onExists: () => this.loadReferenceData(),
            redirectRoute: ['/automations/connectors/internal'],
            description: 'Internal DataGerry connector for automations',
            cancelRoute: ['/automations'],
            errorRoute: ['/automations']
        });
    }

    /* ------------------------------------------------- DATA LOADING ------------------------------------------------- */

    private loadReferenceData(): void {
        this.loaderService.show();

        combineLatest([
            this.connectorsService.getConnectors(),
            this.connectorsService.getInvokers(),
            this.typeService.getTypeList()
        ])
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: ([connectors, invokers, types]) => {
                    // The connector list carries only the invoker's name; the wizard needs the full
                    // definition to resolve operations and fields.
                    this.connectors = this.withFullInvokers(connectors ?? [], invokers ?? []);
                    this.internalConnector = this.connectors.find(
                        connector => connector.title === INTERNAL_CONNECTOR_TITLE
                    ) ?? null;

                    if (!this.internalConnector) {
                        this.internalConnectorHelper.redirectToInternalConnectorSetup(
                            ['/automations/connectors/internal'],
                            'Internal DataGerry connector for automations'
                        );

                        return;
                    }

                    this.objectTypes = (types ?? []) as CmdbType[];
                    this.targetSystems = this.catalog.selectableSystems(this.connectors, INTERNAL_CONNECTOR_TITLE);

                    if (this.mode === 'edit') {
                        this.restoreFromHistoryState();
                    }

                    this.refresh();
                },
                error: (err) => {
                    this.toast.error(err?.error?.message);
                    this.router.navigate(['/automations']);
                }
            });
    }


    /**
     * Rebuilds the automation from the connection the list component handed over.
     *
     * The business model travels inside the connection description, so an automation created by the
     * wizard reopens with every choice intact.
     */
    private restoreFromHistoryState(): void {
        const automation = history.state?.automation;

        if (!automation) {
            this.toast.warning('Automation data not found. Please open it again from the list.');
            this.router.navigate(['/automations']);

            return;
        }

        this.existingConnection = automation.connection ?? null;
        this.connectionId = this.existingConnection?.connectionId ?? null;
        this.schedulerId = automation.schedulerId ?? null;

        const decoded = this.codec.decode(this.existingConnection?.description);

        if (!decoded.definition) {
            this.legacyWithoutDefinition = true;
            this.definition.name = automation.title ?? this.existingConnection?.title ?? '';
            this.definition.description = decoded.description;

            return;
        }

        this.definition = decoded.definition;
        this.definition.name = automation.title ?? this.existingConnection?.title ?? this.definition.name;
        this.definition.description = decoded.description;
        this.definition.active = automation.status !== false;
        this.definition.trigger.cronExp = automation.cronExp ?? this.definition.trigger.cronExp;
        this.definition.trigger.type = this.definition.trigger.cronExp ? 'scheduled' : this.definition.trigger.type;

        this.onObjectTypeChanged(this.definition.objectType.typeId, false);
        this.currentGroup = WizardGroup.REVIEW;
    }


    /** Replaces each connector's invoker stub with the full definition. */
    private withFullInvokers(connectors: any[], invokers: any[]): any[] {
        const byName = new Map<string, any>(
            invokers.filter(invoker => invoker?.name).map(invoker => [invoker.name, invoker])
        );

        return connectors.map(connector => {
            const name = connector?.invoker?.name ?? connector?.invoker;
            const invoker = name ? byName.get(name) : null;

            return invoker ? { ...connector, invoker } : connector;
        });
    }

    /* ---------------------------------------------------- EVENTS ---------------------------------------------------- */

    public onStepSelected(index: number): void {
        this.currentGroup = index as WizardGroup;
    }


    public onNext(): void {
        if (this.currentGroup < WIZARD_GROUP_COUNT - 1) {
            this.currentGroup++;
            this.refresh();
        }
    }


    public onBack(): void {
        if (this.currentGroup > WizardGroup.TRIGGER) {
            this.currentGroup--;
        }
    }


    /** Any change from a step component funnels through here so derived state stays in sync. */
    public onDefinitionChanged(definition: AutomationDefinition): void {
        this.definition = definition;
        this.refresh();
    }


    /**
     * Loads the fields of the chosen object type.
     *
     * `resetSelection` is false while restoring a stored automation, whose field selection must
     * survive.
     */
    public onObjectTypeChanged(typeId: number | null, resetSelection = true): void {
        this.selectedType = this.objectTypes.find(type => type.public_id === typeId) ?? null;
        this.definition.objectType = {
            typeId: this.selectedType?.public_id ?? null,
            name: this.selectedType?.name ?? '',
            label: this.selectedType?.label ?? ''
        };
        this.availableFields = this.flattenTypeFields(this.selectedType);

        if (resetSelection) {
            this.definition.fields = [];
            this.definition.mapping = [];
        }

        this.refresh();
    }


    /**
     * Starts the mapping over for a newly chosen system or action.
     *
     * Unlike the reconciliation in refresh(), this discards existing pairs: they were made against a
     * different set of target fields and carrying them over would silently keep stale targets.
     */
    public onTargetChanged(): void {
        this.refreshTargetFields();
        this.refreshSourceFields();
        this.definition.mapping = this.mapper
            .suggest(this.sourceFields, this.targetFields)
            .map(suggestion => this.mapper.asEntry(suggestion));
        this.definition.unmapped = [];
        this.refresh();
    }


    /** Re-runs the suggestion for entries the user has not mapped by hand. */
    public onAutoMap(): void {
        this.refreshSourceFields();
        this.definition.mapping = this.mapper.fillGaps(
            this.definition.mapping,
            this.sourceFields,
            this.targetFields
        );
        this.refresh();
    }

    /**
     * Loads one real object of the selected type to fill the test step with actual values.
     *
     * Only meaningful for outgoing automations, where DataGerry is the source. A different object is
     * fetched on each call so the user can spot fields that are empty on one object but not another.
     */
    public onLoadSample(): void {
        if (!this.definition.objectType.typeId || this.definition.direction !== 'outgoing') {
            return;
        }

        this.sampleLoading = true;

        this.objectService
            .getObjects({
                filter: { type_id: this.definition.objectType.typeId },
                limit: 1,
                sort: 'public_id',
                order: 1,
                page: this.nextSamplePage(),
                projection: undefined
            })
            .pipe(finalize(() => (this.sampleLoading = false)))
            .subscribe({
                next: (response: any) => {
                    const object = response?.results?.[0];

                    if (!object) {
                        this.toast.info('No object of this type exists yet, so no sample values are available.');
                        this.samplePage = 1;

                        return;
                    }

                    this.sampleObjectId = object?.object_information?.object_id
                        ?? object?.public_id
                        ?? null;
                    this.sampleValues = this.extractFieldValues(object);
                },
                error: (err) => this.toast.error(err?.error?.message)
            });
    }


    /** Advances through the type's objects so repeated clicks show different samples. */
    private nextSamplePage(): number {
        this.samplePage = this.sampleValues && Object.keys(this.sampleValues).length > 0
            ? this.samplePage + 1
            : 1;

        return this.samplePage;
    }


    /** Reads name/value pairs out of a rendered object. */
    private extractFieldValues(object: any): Record<string, string> {
        const fields: any[] = object?.fields ?? [];

        return fields.reduce((values: Record<string, string>, field: any) => {
            if (field?.name !== undefined) {
                values[field.name] = field.value === null || field.value === undefined
                    ? ''
                    : String(field.value);
            }

            return values;
        }, {});
    }

    /* ---------------------------------------------------- SAVING ---------------------------------------------------- */

    public save(): void {
        if (this.validationErrors.length > 0) {
            this.toast.warning('Please resolve the listed problems first.');
            this.currentGroup = WizardGroup.REVIEW;

            return;
        }

        const context = this.compileContext();

        if (!context) {
            return;
        }

        const description = this.codec.encode(this.definition.description, this.definition);

        if (this.codec.exceedsSizeBudget(description)) {
            this.toast.warning(
                'This automation is large; reopening it in the wizard may not be possible. '
                + 'It will still run correctly.'
            );
        }

        this.loaderService.show();

        const request$ = this.mode === 'create'
            ? this.automationsService.createAutomation(this.createPayload(context, description))
            : this.automationsService.updateConnection(
                this.connectionId!,
                this.updatePayload(context, description)
            );

        request$.pipe(finalize(() => this.loaderService.hide())).subscribe({
            next: () => {
                this.toast.success(
                    this.mode === 'create' ? 'Automation created successfully' : 'Automation updated successfully'
                );
                this.router.navigate(['/automations']);
            },
            error: (err) => this.toast.error(err?.error?.message)
        });
    }


    public cancel(): void {
        this.router.navigate(['/automations']);
    }


    private createPayload(context: AutomationCompileContext, description: string): any {
        const compiled = this.compiler.compileForCreate(this.definition, context);
        compiled.payload.connection.description = description;

        return compiled.payload;
    }


    private updatePayload(context: AutomationCompileContext, description: string): any {
        const compiled = this.compiler.compileForUpdate(this.definition, context, this.connectionId!);
        compiled.payload.description = description;

        return compiled.payload;
    }

    /* --------------------------------------------------- FUNCTIONS -------------------------------------------------- */

    /** Recomputes validation, warnings and the technical preview after every change. */
    private refresh(): void {
        // All of these derive from the definition, so they are rebuilt here rather than at each call
        // site - a target list that only refreshed on the target step went stale as soon as the
        // direction changed, and stayed empty altogether when an automation was reopened for editing.
        this.refreshTargetFields();
        this.refreshSourceFields();
        this.reconcileMapping();

        this.systemFields = systemFieldsFor(this.definition.direction);
        this.readableDescription = describeAutomation(this.definition);
        this.refreshMatching();

        const context = this.compileContext();

        if (!context) {
            this.validationErrors = ['The internal DataGerry connector or the target system is not available.'];
            this.compiledPreview = '';
            this.compiledConnection = null;

            return;
        }

        this.validationErrors = this.compiler.validate(this.definition, context);

        if (this.validationErrors.length > 0) {
            this.compileWarnings = [];
            this.compiledPreview = '';
            this.compiledConnection = null;

            return;
        }

        const compiled = this.mode === 'create'
            ? this.compiler.compileForCreate(this.definition, context)
            : this.compiler.compileForUpdate(this.definition, context, this.connectionId ?? 0);

        this.compileWarnings = compiled.warnings;
        this.compiledPreview = JSON.stringify(compiled.payload, null, 2);
        this.compiledConnection = 'connection' in compiled.payload
            ? compiled.payload.connection
            : compiled.payload;
    }


    /**
     * Rebuilds the fields the target action accepts.
     *
     * Which invoker that is follows from the direction: an outgoing automation writes to the chosen
     * system, an incoming one writes to DataGerry.
     */
    private refreshTargetFields(): void {
        const targetInvoker = this.definition.direction === 'outgoing'
            ? this.connectorOf(this.definition.target.connectorId)?.invoker
            : this.internalConnector?.invoker;

        const operation: ResolvedOperation | null = this.catalog.resolveOperation(
            targetInvoker,
            this.definition.target.operation
        );

        this.targetFields = keepIfUnchanged(
            this.targetFields,
            this.catalog.targetFields(operation),
            field => field.path
        );
    }


    /**
     * Works out whether the automation looks its objects up, and by which fields it could.
     *
     * Both follow from the chosen action and from what the target system's read operation can
     * search by, so the mapping step never offers a marker that would not work.
     */
    private refreshMatching(): void {
        this.matchingRelevant = requiresMatching(this.definition);

        const targetInvoker = this.definition.direction === 'outgoing'
            ? this.connectorOf(this.definition.target.connectorId)?.invoker
            : this.internalConnector?.invoker;
        const lookup = this.catalog.resolveOperation(targetInvoker, 'list');

        this.targetOperations = keepIfUnchanged(
            this.targetOperations,
            (this.connectorOf(this.definition.target.connectorId)?.invoker?.operations ?? [])
                .map((operation: any) => operation?.name)
                .filter((name: string) => !!name),
            name => name
        );

        this.matchableTargets = keepIfUnchanged(
            this.matchableTargets,
            this.catalog.matchFilter(targetInvoker, lookup)?.keys ?? [],
            key => key
        );
    }


    /** Rebuilds the fields feeding the left-hand side of the mapping. */
    private refreshSourceFields(): void {
        this.sourceFields = keepIfUnchanged(
            this.sourceFields,
            this.sourceFieldsForMapping(),
            field => `${field.name}\u0000${field.label}`
        );
    }


    /**
     * Keeps the mapping in step with the fields currently on the source side.
     *
     * Fields are picked before the mapping step and can be changed afterwards, so entries are added
     * for new ones and dropped for removed ones. Everything the user decided - a chosen target, a
     * cleared one, a value adjustment - survives, because fillGaps only touches undecided pairs.
     */
    private reconcileMapping(): void {
        const sources = this.sourceFields;

        if (sources.length === 0) {
            if (this.definition.mapping.length > 0) {
                this.definition.mapping = [];
            }

            return;
        }

        // fillGaps() is the expensive half of a refresh - it fuzzy-matches every undecided pair - and
        // refresh() runs on every keystroke. Nothing about the source side changes while someone
        // types a condition value, so the whole reconciliation is skipped unless it has to happen.
        // It also replaces the mapping array, which the mapping step uses to detect real changes.
        if (this.mappingCovers(sources)) {
            return;
        }

        this.definition.mapping = this.mapper.fillGaps(
            this.mapper.prune(this.definition.mapping, sources, this.targetFields),
            sources,
            this.targetFields,
            this.definition.unmapped
        );
    }


    /**
     * Whether every offered source already feeds something, or was deliberately left alone.
     *
     * Cheap enough to run on every refresh, which is what keeps the fuzzy matching in fillGaps off
     * the keystroke path.
     */
    private mappingCovers(sources: AutomationField[]): boolean {
        const used = mappedSources(this.definition.mapping);
        const left = new Set(this.definition.unmapped);

        return sources.every(field => used.has(field.name) || left.has(field.name));
    }


    private compileContext(): AutomationCompileContext | null {
        const targetConnector = this.connectorOf(this.definition.target.connectorId);

        if (!this.internalConnector || !targetConnector) {
            return null;
        }

        return {
            internalConnector: this.internalConnector,
            targetConnector,
            objectTypeFieldOrder: this.availableFields.map(field => field.name)
        };
    }


    private connectorOf(connectorId: number | null): any {
        return this.connectors.find(connector => connector.connectorId === connectorId) ?? null;
    }


    /**
     * Which fields feed the left-hand side of the mapping.
     *
     * Outgoing automations read DataGerry, so the user's field selection applies. Incoming ones read
     * the foreign system, so its response fields do - plus any fixed value the user picked, such as
     * the object type, which has to reach DataGerry no matter which side is being read.
     */
    private sourceFieldsForMapping(): AutomationField[] {
        if (this.definition.direction === 'outgoing') {
            return this.definition.fields;
        }

        const sourceConnector = this.connectorOf(this.definition.target.connectorId);
        const operation = this.catalog.resolveOperation(sourceConnector?.invoker, 'list');
        const remoteFields = this.catalog.sourceItemFields(operation).map(field => ({
            name: field.path,
            label: field.name,
            type: field.type
        }));

        const constants = this.definition.fields.filter(
            field => findSystemField(field.name)?.kind === 'constant'
        );

        return [...constants, ...remoteFields];
    }


    /** Flattens a type's sections into the field list the wizard offers. */
    private flattenTypeFields(type: CmdbType | null): AutomationField[] {
        if (!type?.fields) {
            return [];
        }

        return type.fields.map((field: any) => ({
            name: field.name,
            label: field.label || field.name,
            type: field.type ?? 'text'
        }));
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public get reachableGroup(): number {
        return furthestReachableGroup(this.definition);
    }


    public get canAdvance(): boolean {
        return isGroupComplete(this.currentGroup, this.definition);
    }


    public get isLastGroup(): boolean {
        return this.currentGroup === WIZARD_GROUP_COUNT - 1;
    }


    public get isCloudMode(): boolean {
        return environment.cloudMode;
    }
}


/**
 * Returns the previous list when the new one describes the same thing.
 *
 * Recomputing produces an equal but distinct array, and handing that to a child component reads as
 * a change - ng-select rebuilds its dropdown, the mapping step rebuilds its cached view data. Keying
 * on the identifying part of each entry keeps those rebuilds tied to actual changes.
 */
function keepIfUnchanged<T>(previous: T[], next: T[], key: (item: T) => string): T[] {
    if (previous === next) {
        return previous;
    }

    const unchanged = previous.length === next.length
        && next.every((item, index) => key(item) === key(previous[index]));

    return unchanged ? previous : next;
}
