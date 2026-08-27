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
    Input,
    OnChanges,
    OnDestroy,
    Output,
    Renderer2,
    SimpleChanges
} from '@angular/core';

import { ReplaySubject } from 'rxjs';

import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ValidationService } from 'src/app/framework/builder/services/validation.service';

import { Controller } from 'src/app/framework/builder/controls/controls.common';
import { SectionControl } from 'src/app/framework/builder/controls/section.control';
import { Group } from '../../../management/models/group';
import { User } from '../../../management/models/user';
import { TextControl } from 'src/app/framework/builder/controls/text/text.control';
import { PasswordControl } from 'src/app/framework/builder/controls/text/password.control';
import { TextAreaControl } from 'src/app/framework/builder/controls/text/textarea.control';
import { ReferenceControl } from 'src/app/framework/builder/controls/specials/ref.control';
import { LocationControl } from 'src/app/framework/builder/controls/specials/location.control';
import { RadioControl } from 'src/app/framework/builder/controls/choice/radio.control';
import { SelectControl } from 'src/app/framework/builder/controls/choice/select.control';
import { CheckboxControl } from 'src/app/framework/builder/controls/choice/checkbox.control';
import { CmdbMode } from '../../modes.enum';
import { DateControl } from 'src/app/framework/builder/controls/date-time/date.control';
import { RefSectionControl } from 'src/app/framework/builder/controls/ref-section.common';
import { CmdbType, CmdbTypeSection } from '../../models/cmdb-type';
import { CmdbSectionTemplate } from '../../models/cmdb-section-template';
import { MultiSectionControl } from 'src/app/framework/builder/controls/multi-section.control';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { FieldIdentifierValidationService } from 'src/app/framework/builder/services/field-identifier-validation.service';
import { BuilderUtils } from 'src/app/framework/builder/utils/builder-utils';
import { NumberControl } from 'src/app/framework/builder/controls/number/number.control';
import { LocationFieldDeletionService } from '../services/location-field-deletion.service';
import { BuilderContext } from 'src/app/framework/builder/utils/builder-context';
import { BuilderInteractionPolicy, BuilderInteractionPolicyContext } from 'src/app/framework/builder/utils/builder-interaction-policy';
import { BuilderHighlightHelper } from 'src/app/framework/builder/utils/builder-highlight.helper';
import { BuilderTemplateManager } from 'src/app/framework/builder/utils/builder-template.manager';
import { BuilderMutationHelper } from 'src/app/framework/builder/utils/builder-mutation.helper';
/* ------------------------------------------------------------------------------------------------------------------ */
declare var $: any;

@Component({
    selector: 'cmdb-builder',
    templateUrl: './builder.component.html',
    styleUrls: ['./builder.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class BuilderComponent implements OnChanges, OnDestroy, AfterViewChecked, DoCheck, BuilderContext {
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public MODES: typeof CmdbMode = CmdbMode;

    public activeIndex: number | null = null;
    public draggedSectionIndex: number | null = null;
    public pendingSectionDropIndex: number | null = null;
    public draggedField: { field: any; section: CmdbTypeSection; index: number } | null = null;

    public sections: Array<any> = [];
    public typeInstance: CmdbType;
    public sectionIdenfier: Array<String> = [];
    public initialIdentifier: string = '';
    public newSections: Array<CmdbTypeSection> = [];
    public newFields: Array<CmdbTypeSection> = [];

    public activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null = null;
    public disableFields: boolean = false;

    // Flags to store previous highlight states
    public prevSectionHighlighted: boolean = false;
    public prevFieldHighlighted: boolean = false;
    public sectionReference: Array<any> | null = null;
    public initialFieldNames: Set<string> | null = null;

    @Input() public sectionTemplates: Array<CmdbSectionTemplate> = [];
    @Input() public globalSectionTemplates: Array<CmdbSectionTemplate> = [];
    @Input() public lockedSectionNames: Array<string> = [];
    @Input() public lockedFieldNames: Array<string> = [];

    public selectedGlobalSectionTemplates: Array<CmdbSectionTemplate> = [];
    private selectedGlobalTemplatesInitialized = false;

    public showColorPickerForSection: string | null = null;  // Keep track of which section's color picker is open

    @Input() public mode = CmdbMode.View;
    @Input() public groups: Array<Group> = [];
    @Input() public users: Array<User> = [];
    @Input() public types: Array<CmdbType> = [];
    @Input() public valid: boolean = true;


    @Input('typeInstance')
    public set TypeInstance(instance: CmdbType) {
        this.typeInstance = instance;
        if (!this.initialFieldNames) {
            this.initialFieldNames = new Set((instance?.fields ?? []).map(field => field?.name).filter(Boolean));
        }

        if (instance?.render_meta?.sections) {
            this.sectionReference = instance.render_meta.sections;
            this.mutation.syncSectionsFromTypeInstance();
        }
    }

    @Output() public validChange: EventEmitter<boolean> = new EventEmitter<boolean>();


    public structureControls = [
        new Controller('section', new SectionControl()),
        new Controller('multi-data-section', new MultiSectionControl()),
        new Controller('ref-section', new RefSectionControl())
    ];


    public basicControls = [
        new Controller('text', new TextControl()),
        new Controller('number', new NumberControl()),
        new Controller('password', new PasswordControl()),
        new Controller('textarea', new TextAreaControl()),
        new Controller('checkbox', new CheckboxControl()),
        new Controller('radio', new RadioControl()),
        new Controller('select', new SelectControl()),
        new Controller('date', new DateControl())
    ];


    public specialControls = [
        new Controller('ref', new ReferenceControl()),
        new Controller('location', new LocationControl())
    ];

    private readonly policy: BuilderInteractionPolicy;
    private readonly highlight: BuilderHighlightHelper;
    private readonly templateManager: BuilderTemplateManager;
    private readonly mutation: BuilderMutationHelper;


    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private modalService: NgbModal, private validationService: ValidationService,
        public sectionIdentifierService: SectionIdentifierService, private fieldIdentifierValidation: FieldIdentifierValidationService,
        private renderer: Renderer2,
        private el: ElementRef,
        private locationFieldDeletion: LocationFieldDeletionService,
    ) {
        this.typeInstance = new CmdbType();

        this.policy = new BuilderInteractionPolicy(() => this.buildPolicyContext());
        this.highlight = new BuilderHighlightHelper(this, this.policy, this.validationService);
        this.templateManager = new BuilderTemplateManager(this, this.policy);
        this.mutation = new BuilderMutationHelper(
            this,
            {
                validationService: this.validationService,
                sectionIdentifierService: this.sectionIdentifierService,
                fieldIdentifierValidation: this.fieldIdentifierValidation,
                locationFieldDeletion: this.locationFieldDeletion,
                renderer: this.renderer,
                el: this.el
            },
            this.policy,
            this.highlight,
            this.templateManager
        );
    }


    ngOnInit(): void {
        this.mutation.refreshFieldIdentifiers();
        this.highlight.updateHighlightState();
    }


    ngOnChanges(changes: SimpleChanges): void {
        if (this.globalSectionTemplates?.length > 0 && !this.selectedGlobalTemplatesInitialized) {
            this.selectedGlobalTemplatesInitialized = true;
            this.templateManager.setSelectedGlobalTemplates();
        }
    }


    ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        this.sectionIdentifierService?.resetIdentifiers();
        this.validationService?.cleanup();
        this.fieldIdentifierValidation?.clearFieldNames();
    }


    ngAfterViewChecked(): void {
        this.highlight.checkAndUpdateHighlightState()
    }


    ngDoCheck(): void {
        const sections = this.typeInstance?.render_meta?.sections;
        if (!sections) {
            return;
        }

        if (sections !== this.sectionReference) {
            this.sectionReference = sections;
            this.mutation.syncSectionsFromTypeInstance();
        }
    }


    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onDragStart(index: number): void {
        this.mutation.onDragStart(index);
    }

    public onSectionDrop(event: DndDropEvent): void {
        this.mutation.onSectionDrop(event);
    }

    public onSectionMoved(item: CmdbTypeSection, effect: DropEffect): void {
        this.mutation.onSectionMoved(item, effect);
    }

    public onFieldChange(data: any, sectionIndex?: number, fieldIndex?: number): void {
        this.mutation.onFieldChange(data, sectionIndex, fieldIndex);
    }

    public onFieldDrop(event: DndDropEvent, section: CmdbTypeSection): void {
        this.mutation.onFieldDrop(event, section);
    }

    public onFieldDragStart(field: any, section: CmdbTypeSection, index: number): void {
        this.mutation.onFieldDragStart(field, section, index);
    }

    public removeSection(item: CmdbTypeSection, sectionIndex: number): void {
        this.mutation.removeSection(item, sectionIndex);
    }

    public removeField(item: any, section: CmdbTypeSection): void {
        this.mutation.removeField(item, section);
    }

    /**
     * Prevents drag events only for sections that are not allowed to move.
     */
    public preventSectionDrag(event: DragEvent, section: CmdbTypeSection): void {
        if (!this.policy.canMoveSection(section) || this.isAnySectionHighlighted() || this.disableFields) {
            event?.stopPropagation(); // Stops event from affecting other elements
            event?.preventDefault();  // Prevent dragging behavior
        }
    }

    /**
     * Prevents drag events for all fields within a section if any field in the section is highlighted.
     */
    public preventDragForAllFields(event: DragEvent, section: any): void {
        this.highlight.preventDragForAllFields(event, section);
    }

    /**
     * Sets the active index for the current section and updates the section identifier service.
     */
    public setActiveIndex(index: number): void {
        this.activeIndex = index;
        this.sectionIdentifierService?.setActiveIndex(index);
    }

    /**
     * Toggles the visibility of the color picker for the specified section.
     */
    public toggleColorPicker(section: CmdbTypeSection): void {
        if (this.showColorPickerForSection === section?.name) {
            this.showColorPickerForSection = null;
        } else {
            this.showColorPickerForSection = section?.name;
        }
    }

    /**
     * Updates the background color of a specified section and applies it to the type instance metadata.
     */
    public updateSectionColor(section: CmdbTypeSection, color: string): void {
        if (this.mode === this.MODES.View) {
            return;
        }

        // Validate color input, ensure it's a valid string
        if (!color || color?.trim() === '') {
            return;
        }

        section.bg_color = color;


        const sectionIndex = this.typeInstance?.render_meta?.sections?.findIndex((s) => s?.name === section?.name);
        if (sectionIndex !== -1) {
            this.typeInstance.render_meta.sections[sectionIndex].bg_color = color;
        }

        //hide the color picker after selecting a color
        // this.showColorPickerForSection = null;
    }


    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * This method checks if the field is used for an external link.
     */
    public externalField(field) {
        return this.mutation.externalField(field);
    }

    public getFieldHiddenState(section: CmdbTypeSection, field: any): boolean {
        return this.mutation.getFieldHiddenState(section, field);
    }

    /* --------------------------------------------- INTERACTION / PERMISSIONS ------------------------------------------ */

    public getSectionCollapseIcon(section: CmdbTypeSection): [string, string] {
        return this.policy.getSectionCollapseIcon(section);
    }

    public isLockedField(field: any): boolean {
        return this.policy.isLockedField(field);
    }

    public canRemoveSection(section: CmdbTypeSection): boolean {
        return this.policy.canRemoveSection(section);
    }

    public canMoveSection(section: CmdbTypeSection): boolean {
        return this.policy.canMoveSection(section);
    }

    public canDropFieldsIntoSection(section: CmdbTypeSection): boolean {
        return this.policy.canDropFieldsIntoSection(section);
    }

    public canMoveField(field: any): boolean {
        return this.policy.canMoveField(field);
    }

    public canRemoveField(field: any): boolean {
        return this.policy.canRemoveField(field);
    }

    public getDnDEffectAllowedForField(field: any): string {
        return this.policy.canMoveField(field) ? "move" : "none";
    }

    public getSectionMode(section: CmdbTypeSection, mode: CmdbMode): CmdbMode {
        if (!this.policy.canEditSection(section)) {
            return CmdbMode.Global
        }

        if (this.isNewSection(section)) {
            return CmdbMode.Create
        }

        return mode;
    }

    /**
     * This prevents the special control "Location" to be placed inside an multi-data-section
     */
    public getInputType(sectionType: string) {
        if (sectionType == "multi-data-section") {
            return ['inputs'];
        }

        return ['inputs', 'location'];
    }

    /* ------------------------------------------------ HIGHLIGHT / STATE ----------------------------------------------- */

    public isSectionHighlighted(section: any): boolean {
        return this.highlight.isSectionHighlighted(section);
    }

    public isFieldHighlighted(field: any, section?: any): boolean {
        return this.highlight.isFieldHighlighted(field, section);
    }

    public isAnySectionHighlighted(): boolean {
        return this.highlight.isAnySectionHighlighted();
    }

    public isEmptyFielsExist(sectionIndex: number, fieldIndex: number): boolean {
        return this.highlight.isEmptyFielsExist(sectionIndex, fieldIndex);
    }

    public isConfigEditDisabled(sectionIndex: number, fieldIndex: number): boolean {
        return this.highlight.isConfigEditDisabled(sectionIndex, fieldIndex);
    }

    public isLocked(): boolean {
        return this.highlight.isLocked();
    }

    public getSectionHeaderClass(section: any): any {
        return this.highlight.getSectionHeaderClass(section);
    }

    public getDraggableItemClass(): any {
        return this.highlight.getDraggableItemClass();
    }

    /* ------------------------------------------------- PREVIEW / MISC ------------------------------------------------- */

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

    /**
     * Matches a given value to a corresponding type string.
     */
    public matchedType(value: string): string {
        return BuilderUtils?.matchedType(value);
    }


    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Checks if the given section is new by comparing it to the list of new sections.
     */
    public isNewSection(section: CmdbTypeSection): boolean {
        return BuilderUtils?.isNewSection(section, this.newSections);
    }

    /**
     * Checks if the given field is new by comparing it to the list of new fields.
     */
    public isNewField(field: any): boolean {
        return BuilderUtils?.isNewField(field, this.newFields)
            || this.isFieldAddedDuringEdit(field);
    }

    private isFieldAddedDuringEdit(field: any): boolean {
        if (this.mode !== CmdbMode.Edit || !field?.name || !this.initialFieldNames) {
            return false;
        }

        return !this.initialFieldNames.has(field.name) && !this.policy.isSchemaLockedField(field);
    }

    private buildPolicyContext(): BuilderInteractionPolicyContext {
        // Only APPLIED global templates make a section/field "global". Templates still available in the
        // palette must not lock or hijack a user-created section/field that shares their identifier.
        const appliedTemplates = this.selectedGlobalSectionTemplates ?? [];

        return {
            selectedGlobalSectionTemplates: appliedTemplates,
            globalTemplateIds: this.typeInstance?.global_template_ids ?? [],
            globalFieldNames: appliedTemplates.flatMap(template => (template?.fields ?? []).map(field => field?.name)),
            schemaLockedSectionNames: this.lockedSectionNames ?? [],
            schemaLockedFieldNames: this.lockedFieldNames ?? []
        };
    }
}
