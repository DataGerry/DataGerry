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
import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { FormControl, FormGroup } from '@angular/forms';
import { Router } from '@angular/router';

import { Observable, ReplaySubject, takeUntil } from 'rxjs';

import { v4 as uuidv4 } from 'uuid';

import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { SectionTemplateService } from '../../services/section-template.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { CmdbMode } from 'src/app/framework/modes.enum';
import { APIInsertSingleResponse, APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
import { ReferenceControl } from 'src/app/framework/builder/controls/specials/ref.control';
import { BASIC_CONTROLS } from 'src/app/framework/builder/controls/basic-controls';
import {
    BuilderPaletteGroup,
    paletteItemsFromControls
} from 'src/app/framework/builder/palette/builder-palette.model';
import { BuilderSection } from 'src/app/framework/builder/schema/builder-section.model';
import { SingleSectionBuilderHost } from 'src/app/framework/builder/canvas/single-section-builder.host';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'section-template-builder',
    templateUrl: './section-template-builder.component.html',
    styleUrls: ['./section-template-builder.component.scss'],
    standalone: false
})
export class SectionTemplateBuilderComponent implements OnInit, OnDestroy {

    @Input()
    public sectionTemplateID: number;

    public initialSection: any = {
        'name': this.generateSectionTemplateName(),
        'label': 'Section',
        'type': 'section',
        'fields': []
    };

    public MODES: typeof CmdbMode = CmdbMode;

    public formGroup: FormGroup;
    isValid$: Observable<boolean>;

    public isFormValid: boolean = false;

    /**
     * The section card reads the template through this host, which is also what applies field drops,
     * reorders, removals and config-edit changes back onto it.
     */
    public readonly sectionHost: SingleSectionBuilderHost;

    private readonly unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    private readonly basicItems = paletteItemsFromControls(BASIC_CONTROLS);

    private readonly specialItems = paletteItemsFromControls([new ReferenceControl()]);

    /** Section templates offer the basic controls plus Reference; the section itself is fixed. */
    public readonly paletteGroups: Array<BuilderPaletteGroup> = [
        {
            id: 'basicControls',
            label: 'Basic Controls',
            expanded: true,
            items: this.basicItems
        },
        {
            id: 'specialControls',
            label: 'Special Controls',
            items: this.specialItems
        }
    ];

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private validationService: ValidationService,
        private sectionTemplateService: SectionTemplateService,
        private toastService: ToastService,
        private router: Router) {

        this.formGroup = new FormGroup({
            'isGlobal': new FormControl(false),
            'isMultiDataSection': new FormControl(false)
        });

        this.sectionHost = new SingleSectionBuilderHost(
            () => this.initialSection as BuilderSection,
            this.validationService
        );
    }


    ngOnInit(): void {
        //EDIT MODE
        if (this.sectionTemplateID > 0) {
            this.getSectionTemplate(this.sectionTemplateID);
        }

        this.isValid$ = this.validationService?.getIsValid();

        this.isValid$.pipe(takeUntil(this.unsubscribe)).subscribe(valid => {
            this.isFormValid = valid;
        });

        this.formGroup?.controls['isGlobal']?.valueChanges?.pipe(takeUntil(this.unsubscribe))
            .subscribe(isGlobal => this.renameTemplate(isGlobal));

        this.formGroup?.controls['isMultiDataSection']?.valueChanges?.pipe(takeUntil(this.unsubscribe))
            .subscribe(isMultiDataSection => {
                this.initialSection.type = isMultiDataSection ? 'multi-data-section' : 'section';
            });
    }


    public ngOnDestroy(): void {
        this.unsubscribe?.next();
        this.unsubscribe?.complete();
        this.validationService?.cleanup();
    }

    /* ---------------------------------------------------- API Calls --------------------------------------------------- */

    /**
     * Decides if a section template should be crated or updated
     */
    public handleSectionTemplate() {

        if (this.initialSection.fields.length === 0 || !this.isFormValid) {
            this.toastService.error("Form is invalid or incomplete. Cannot save.");
            return;
        }

        this.initialSection.type = this.getSectionTemplateType();

        if (this.sectionTemplateID > 0) {
            this.updateSectionTemplate();
        } else {
            this.createSectionTemplate();
        }
    }


    /**
     * Send section template data to backend for creation
     */
    public createSectionTemplate() {
        let params = {
            "name": this.initialSection?.name,
            "label": this.initialSection?.label,
            "type": this.getSectionTemplateType(),
            "is_global": this.formGroup?.value?.isGlobal,
            "predefined": false,
            "fields": JSON.stringify(this.initialSection?.fields)
        }

        this.sectionTemplateService?.postSectionTemplate(params).subscribe({
            next: (res: APIInsertSingleResponse) => {
                this.toastService.success("Section Template created!");
                this.router.navigate(['/framework/section_templates']);
            },
            error: (error) => {
                this.toastService.error(error?.error?.message);
            }
        });
    }


    /**
     * Send section template data to backend to update the existing section template
     */
    public updateSectionTemplate() {
        let params = {
            'name': this.initialSection?.name,
            'label': this.initialSection?.label,
            'type': this.getSectionTemplateType(),
            'is_global': this.formGroup?.value?.isGlobal,
            'predefined': false,
            'fields': JSON.stringify(this.initialSection?.fields),
            'public_id': this.initialSection?.public_id
        }

        this.sectionTemplateService?.updateSectionTemplate(params)
            .subscribe({
                next: (res: APIUpdateSingleResponse) => {
                    this.toastService.success("Section Template updated!");
                    this.router.navigate(['/framework/section_templates']);
                },
                error: (error) => this.toastService.error(error?.error?.message)
            }
            );
    }


    /**
     * Retrieves a section template with the given publicID
     * 
     * @param publicID publicID of section template which should be edited
     */
    private getSectionTemplate(publicID: number) {
        this.sectionTemplateService?.getSectionTemplate(publicID)
            .subscribe({
                next: (response: CmdbSectionTemplate) => {
                    this.initialSection = response;
                    this.formGroup?.controls?.isGlobal?.setValue(this.initialSection?.is_global);
                    this.formGroup?.controls?.isMultiDataSection?.setValue(this.initialSection?.type === 'multi-data-section');
                },
                error: (error) => this.toastService.error(error?.error?.message)
            }
            );
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Generates unique name for sections
     * 
     * @returns Unique name for section
     */
    public generateSectionTemplateName(isGlobal: boolean = false) {
        if (isGlobal) {
            return `dg_gst-${uuidv4()}`;
        }

        return `section_template-${uuidv4()}`;
    }


    /**
     * Moves the template between the global and the standard identifier namespace, reusing the
     * current name when it already carries the right prefix.
     *
     * The whole section object is replaced rather than renamed in place: the bound section editor
     * only patches its form from `ngOnChanges`, which needs a new reference to fire.
     */
    private renameTemplate(isGlobal: boolean): void {
        const currentName: string = this.initialSection?.name ?? '';
        const keepsCurrentName = isGlobal
            ? currentName.includes('dg_gst-')
            : currentName.includes('section_template');

        if (keepsCurrentName) {
            return;
        }

        this.initialSection = {
            ...this.initialSection,
            name: this.generateSectionTemplateName(isGlobal)
        };
    }


    private getSectionTemplateType(): string {
        return this.formGroup?.value?.isMultiDataSection ? 'multi-data-section' : 'section';
    }
}
