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
    AfterViewChecked,
    ChangeDetectionStrategy,
    Component,
    DoCheck,
    ElementRef,
    EventEmitter,
    Inject,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Optional,
    Output,
    Renderer2
} from '@angular/core';

import { ReplaySubject } from 'rxjs';

import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ValidationService } from '../services/validation.service';
import { SectionIdentifierService } from '../services/SectionIdentifierService.service';
import { FieldIdentifierValidationService } from '../services/field-identifier-validation.service';
import { BUILDER_DELETION_GUARD, BuilderDeletionGuard } from '../services/builder-deletion-guard';

import { CmdbType } from '../../models/cmdb-type';
import { SectionTemplateListItem } from '../../section_templates/models/virtual-section-template.model';
import { CmdbMode } from '../../modes.enum';

import { BuilderSection } from '../schema/builder-section.model';
import { BuilderSchemaAdapter } from '../schema/builder-schema.adapter';
import { EmptySchemaAdapter } from '../schema/empty-schema.adapter';
import { BuilderPaletteGroup } from '../palette/builder-palette.model';
import { BuilderUtils } from '../utils/builder-utils';
import { BuilderContext } from '../utils/builder-context';
import { BuilderInteractionPolicy, BuilderInteractionPolicyContext } from '../utils/builder-interaction-policy';
import { BuilderModeResolver } from '../utils/builder-mode.resolver';
import { BuilderHighlightHelper } from '../utils/builder-highlight.helper';
import { BuilderTemplateManager } from '../utils/builder-template.manager';
import { BuilderMutationHelper } from '../utils/builder-mutation.helper';
import { BuilderSectionHost } from './builder-section-host';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The shared drag-and-drop canvas: a control palette on the left, an ordered list of section cards
 * on the right. It is feature-neutral - what is edited comes in as a schema adapter, what can be
 * dropped comes in as palette groups - so the type and relation content steps are the same canvas
 * with different configuration.
 */
@Component({
    selector: 'dg-builder-canvas',
    templateUrl: './builder-canvas.component.html',
    styleUrls: ['./builder-canvas.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class BuilderCanvasComponent implements OnInit, OnChanges, OnDestroy, AfterViewChecked, DoCheck,
    BuilderContext, BuilderSectionHost {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public MODES: typeof CmdbMode = CmdbMode;

    public activeIndex: number | null = null;
    public draggedSectionIndex: number | null = null;
    public pendingSectionDropIndex: number | null = null;
    public draggedField: { field: any; section: BuilderSection; index: number } | null = null;

    public sections: Array<BuilderSection> = [];
    public initialIdentifier: string = '';
    public newSections: Array<BuilderSection> = [];
    public newFields: Array<any> = [];

    public activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null = null;
    public disableFields: boolean = false;

    // Flags to store previous highlight states
    public prevSectionHighlighted: boolean = false;
    public prevFieldHighlighted: boolean = false;
    public sectionReference: Array<BuilderSection> | null = null;
    public initialFieldNames: Set<string> | null = null;

    public selectedGlobalSectionTemplates: Array<SectionTemplateListItem> = [];
    private selectedGlobalTemplatesInitialized = false;

    public showColorPickerForSection: string | null = null;  // Keep track of which section's color picker is open

    /** Stands in until a model is bound, so the helpers never have to null-check the schema. */
    private readonly emptySchema = new EmptySchemaAdapter();
    private boundSchema: BuilderSchemaAdapter | null = null;

    /** Reaches the edited model - the only thing here that knows where sections and fields live. */
    @Input('schema')
    public set Schema(adapter: BuilderSchemaAdapter | null) {
        this.boundSchema = adapter ?? null;

        if (adapter) {
            this.adoptSchema();
        }
    }

    public get schema(): BuilderSchemaAdapter {
        return this.boundSchema ?? this.emptySchema;
    }

    /** The draggable controls this builder offers, in display order. */
    @Input() public paletteGroups: Array<BuilderPaletteGroup> = [];

    @Input() public globalSectionTemplates: Array<SectionTemplateListItem> = [];
    @Input() public lockedSectionNames: Array<string> = [];
    @Input() public lockedFieldNames: Array<string> = [];

    @Input() public mode = CmdbMode.View;
    @Input() public types: Array<CmdbType> = [];
    @Input() public valid: boolean = true;

    /** Shows the Preview and Diagnostic actions under the palette. */
    @Input() public showTools: boolean = false;

    /** Stretches the palette to the empty drop zone's height before the first section is dropped. */
    @Input() public stretchPaletteWhenEmpty: boolean = false;

    @Output() public validChange: EventEmitter<boolean> = new EventEmitter<boolean>();

    private readonly policy: BuilderInteractionPolicy;
    private readonly modes: BuilderModeResolver;
    private readonly highlight: BuilderHighlightHelper;
    private readonly templateManager: BuilderTemplateManager;
    private readonly mutation: BuilderMutationHelper;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(
        private modalService: NgbModal,
        private validationService: ValidationService,
        public sectionIdentifierService: SectionIdentifierService,
        private fieldIdentifierValidation: FieldIdentifierValidationService,
        private renderer: Renderer2,
        private el: ElementRef,
        @Optional() @Inject(BUILDER_DELETION_GUARD) private deletionGuard: BuilderDeletionGuard | null
    ) {
        this.policy = new BuilderInteractionPolicy(() => this.buildPolicyContext());
        this.modes = new BuilderModeResolver(this, this.policy);
        this.highlight = new BuilderHighlightHelper(this, this.policy, this.validationService, this.modes);
        this.templateManager = new BuilderTemplateManager(this, this.policy);
        this.mutation = new BuilderMutationHelper(
            this,
            {
                validationService: this.validationService,
                sectionIdentifierService: this.sectionIdentifierService,
                fieldIdentifierValidation: this.fieldIdentifierValidation,
                deletionGuard: this.deletionGuard ?? null,
                renderer: this.renderer,
                el: this.el
            },
            this.policy,
            this.highlight,
            this.templateManager
        );
    }


    public ngOnInit(): void {
        this.mutation.refreshFieldIdentifiers();
        this.highlight.updateHighlightState();
    }


    public ngOnChanges(): void {
        if (this.globalSectionTemplates?.length > 0 && !this.selectedGlobalTemplatesInitialized) {
            this.selectedGlobalTemplatesInitialized = true;
            this.templateManager.setSelectedGlobalTemplates();
        }

        // Idempotent, and outside the guard above: a copied type arrives after the palette has loaded.
        if (this.globalSectionTemplates?.length > 0) {
            this.mutation.restorePortsSection();
        }
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        this.sectionIdentifierService?.resetIdentifiers();
        this.validationService?.cleanup();
        this.fieldIdentifierValidation?.clearFieldNames();
    }


    public ngAfterViewChecked(): void {
        this.highlight.checkAndUpdateHighlightState()
    }


    public ngDoCheck(): void {
        const sections = this.schema.readSections();

        if (sections === this.sectionReference) {
            return;
        }

        this.sectionReference = sections;
        this.mutation.syncSectionsFromModel();
    }


    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onDragStart(index: number): void {
        this.mutation.onDragStart(index);
    }

    public onSectionDrop(event: DndDropEvent): void {
        this.mutation.onSectionDrop(event);
    }

    public onSectionMoved(item: BuilderSection, effect: DropEffect): void {
        this.mutation.onSectionMoved(item, effect);
    }

    public onValuesChanged(data: any, sectionIndex?: number, fieldIndex?: number): void {
        this.mutation.onFieldChange(data, sectionIndex, fieldIndex);
    }

    public onFieldDrop(event: DndDropEvent, section: BuilderSection): void {
        this.mutation.onFieldDrop(event, section);
    }

    public onFieldDragStart(field: any, section: BuilderSection, index: number): void {
        this.mutation.onFieldDragStart(field, section, index);
    }

    public onSectionRemove(item: BuilderSection, sectionIndex: number): void {
        this.mutation.removeSection(item, sectionIndex);
    }

    public onFieldRemove(item: any, section: BuilderSection): void {
        this.mutation.removeField(item, section);
    }

    /**
     * Prevents drag events only for sections that are not allowed to move.
     */
    public onSectionDragStart(event: DragEvent, section: BuilderSection): void {
        if (!this.policy.canMoveSection(section) || this.isAnySectionHighlighted() || this.disableFields) {
            event?.stopPropagation(); // Stops event from affecting other elements
            event?.preventDefault();  // Prevent dragging behavior
        }
    }

    /**
     * Prevents drag events for all fields within a section if any field in the section is highlighted.
     */
    public onFieldDragBlocked(event: DragEvent, section: any): void {
        this.highlight.preventDragForAllFields(event, section);
    }

    /**
     * Sets the active index for the current section and updates the section identifier service.
     */
    public onSectionFocus(index: number): void {
        this.activeIndex = index;
        this.sectionIdentifierService?.setActiveIndex(index);
    }

    /**
     * Toggles the visibility of the color picker for the specified section.
     */
    public toggleColorPicker(section: BuilderSection): void {
        if (this.showColorPickerForSection === section?.name) {
            this.showColorPickerForSection = null;
        } else {
            this.showColorPickerForSection = section?.name;
        }
    }

    /**
     * Updates the background color of a specified section and applies it to the model.
     */
    public updateSectionColor(section: BuilderSection, color: string): void {
        if (this.mode === this.MODES.View) {
            return;
        }

        // Validate color input, ensure it's a valid string
        if (!color || color?.trim() === '') {
            return;
        }

        section.bg_color = color;

        const modelSections = this.schema.readSections();
        const sectionIndex = modelSections.findIndex((s) => s?.name === section?.name);

        if (sectionIndex !== -1) {
            modelSections[sectionIndex].bg_color = color;
        }
    }


    /* -------------------------------------------------- SECTION HOST -------------------------------------------------- */

    /** The section card always shows its actions on the canvas; only a fixed single section hides them. */
    public readonly showSectionActions = true;

    /** The canvas dispatches its section editors dynamically - a section may be a ref-section. */
    public readonly staticSectionEditor = false;

    public get fields(): Array<any> {
        return this.schema.readFields();
    }

    public getSectionMode(section: BuilderSection): CmdbMode {
        return this.modes.sectionMode(section);
    }

    public getFieldMode(field: any): CmdbMode {
        return this.modes.fieldMode(field);
    }

    public getSectionCollapseIcon(section: BuilderSection): [string, string] {
        return this.policy.getSectionCollapseIcon(section);
    }

    public getSectionHeaderClass(section: BuilderSection): Record<string, boolean> {
        return this.highlight.getSectionHeaderClass(section);
    }

    /**
     * This prevents the special control "Location" from being placed inside a multi-data-section.
     */
    public getFieldDropTypes(section: BuilderSection): Array<string> {
        if (section?.type == "multi-data-section") {
            return ['inputs'];
        }

        return ['inputs', 'location'];
    }

    /** On the canvas a field editor is told the real section type, so an MDS offers its hide control. */
    public getFieldSectionType(section: BuilderSection): string {
        return section?.type;
    }


    public getFieldDragEffect(field: any): string {
        return this.policy.canMoveField(field) ? "move" : "none";
    }

    public getFieldHiddenState(section: BuilderSection, field: any): boolean {
        return this.mutation.getFieldHiddenState(section, field);
    }

    public canMoveSection(section: BuilderSection): boolean {
        return this.policy.canMoveSection(section);
    }

    public canRemoveSection(section: BuilderSection): boolean {
        return this.policy.canRemoveSection(section);
    }

    public canDropFieldsIntoSection(section: BuilderSection): boolean {
        return this.policy.canDropFieldsIntoSection(section);
    }

    public canMoveField(field: any): boolean {
        return this.policy.canMoveField(field);
    }

    public canRemoveField(field: any): boolean {
        return this.policy.canRemoveField(field);
    }

    public isLockedField(field: any): boolean {
        return this.policy.isLockedField(field);
    }

    public isFieldHighlighted(field: any, section?: any): boolean {
        return this.highlight.isFieldHighlighted(field, section);
    }

    public isAnySectionHighlighted(): boolean {
        return this.highlight.isAnySectionHighlighted();
    }

    public isLocked(): boolean {
        return this.highlight.isLocked();
    }

    public isFieldEditDisabled(sectionIndex: number, fieldIndex: number): boolean {
        return this.highlight.isEmptyFielsExist(sectionIndex, fieldIndex)
            || this.highlight.isConfigEditDisabled(sectionIndex, fieldIndex);
    }

    /**
     * This method checks if the field is used for an external link.
     */
    public externalField(field: any): { links: Array<any>; total: number } {
        return this.mutation.externalField(field);
    }

    /**
     * Matches a given value to a corresponding type string.
     */
    public matchedType(value: string): string {
        return BuilderUtils?.matchedType(value);
    }


    /* ------------------------------------------------- PREVIEW / MISC ------------------------------------------------- */

    public isSectionHighlighted(section: any): boolean {
        return this.highlight.isSectionHighlighted(section);
    }

    public getDraggableItemClass(): any {
        return this.highlight.getDraggableItemClass();
    }

    /**
     * Opens a preview modal for the current sections.
     */
    public openPreview(): void {
        BuilderUtils?.openPreview(this.modalService, this.sections);
    }

    /**
     * Opens a diagnostic modal for the current sections.
     */
    public openDiagnostic(): void {
        BuilderUtils?.openDiagnostic(this.modalService, this.sections);
    }


    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Takes on a newly bound model: remembers which fields were already persisted (so fields added
     * during an edit keep an editable identifier) and rebuilds the section projection from it.
     */
    private adoptSchema(): void {
        if (!this.initialFieldNames) {
            this.initialFieldNames = new Set(
                this.schema.readFields().map(field => field?.name).filter(Boolean)
            );
        }

        this.sectionReference = this.schema.readSections();
        this.mutation.syncSectionsFromModel();
    }

    private buildPolicyContext(): BuilderInteractionPolicyContext {
        // Only APPLIED global templates make a section/field "global". Templates still available in the
        // palette must not lock or hijack a user-created section/field that shares their identifier.
        const appliedTemplates = this.selectedGlobalSectionTemplates ?? [];

        return {
            selectedGlobalSectionTemplates: appliedTemplates,
            globalTemplateIds: this.schema.readGlobalTemplateIds(),
            globalFieldNames: appliedTemplates.flatMap(template => (template?.fields ?? []).map(field => field?.name)),
            schemaLockedSectionNames: this.lockedSectionNames ?? [],
            schemaLockedFieldNames: this.lockedFieldNames ?? []
        };
    }
}
