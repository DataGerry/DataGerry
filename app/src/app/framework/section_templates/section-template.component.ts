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
import { Component, inject, OnDestroy, OnInit } from '@angular/core';

import { finalize, map, switchMap, takeUntil } from 'rxjs/operators';
import { Observable, ReplaySubject, forkJoin, of } from 'rxjs';

import { v4 as uuidv4 } from 'uuid';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { SectionTemplateService } from './services/section-template.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import { SectionTemplateDeleteModalComponent } from './layout/modals/section-template-delete/section-template-delete-modal.component';
import { CmdbSectionTemplate, Field } from '../models/cmdb-section-template';
import { SectionTemplateTransformModalComponent } from './layout/modals/section-template-transform/section-template-transform-modal.component';
import { SectionTemplateCloneModalComponent } from './layout/modals/section-template-clone/section-template-clone-modal.component';
import { PreviewModalComponent } from 'src/app/framework/builder/modals/preview-modal/preview-modal.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { SectionTemplateListItem, isVirtualSectionTemplate } from './models/virtual-section-template.model';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface GlobalTemplateCounts {
    'types': number,
    'objects': number
}

@Component({
    selector: 'cmdb-section-template',
    templateUrl: './section-template.component.html',
    styleUrls: ['./section-template.component.scss'],
    standalone: false
})
export class SectionTemplateComponent implements OnInit, OnDestroy {
    private readonly sectionTemplateService = inject(SectionTemplateService);
    private readonly modalService = inject(NgbModal);
    private readonly toastService = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly optionCatalog = inject(ExtendableOptionCatalogService);

    public sectionTemplates: SectionTemplateListItem[] = [];
    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    private modalRef: NgbModalRef;
    public isLoading$ = this.loaderService.isLoading$;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngOnInit(): void {
        this.getAllSectionTemplates();
    }


    ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }
    }

    /* -------------------------------------------------- API FUNCTIONS ------------------------------------------------- */

    /** Loads stored and virtual templates, rendering the table only once both arrived. */
    getAllSectionTemplates() {
        this.loaderService.show();

        forkJoin({
            stored: this.sectionTemplateService.getSectionTemplates(),
            virtual: this.sectionTemplateService.getVirtualSectionTemplates()
        }).pipe(takeUntil(this.unsubscribe), finalize(() => this.loaderService.hide()))
        .subscribe({
            next: ({ stored, virtual }) => {
                const storedTemplates = (stored?.results ?? []) as CmdbSectionTemplate[];

                // Virtual templates lead the list
                this.sectionTemplates = [...virtual, ...storedTemplates];
            },
            error: (error) => this.toastService.error(error?.error?.message)}
        );
    }

    /* ------------------------------------------------- MODAL HANDLING ------------------------------------------------- */

    /**
     * Displays a modal view for user to confirm deletion of section template
     * @param sectionTemplate instance of section template which should be deleted
     */
    showDeleteModal(sectionTemplate: SectionTemplateListItem) {
        if (!this.isWritable(sectionTemplate)) {
            return;
        }

        this.loaderService.show();

        this.sectionTemplateService.getGlobalSectionTemplateCount(sectionTemplate.public_id).pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response: GlobalTemplateCounts) => {
                    let counts: GlobalTemplateCounts = response

                    this.modalRef = this.modalService.open(SectionTemplateDeleteModalComponent, {
                        size: 'lg',
                        windowClass: 'dg-modal-window',
                        backdropClass: 'dg-modal-window-backdrop'
                    });
                    this.modalRef.componentInstance.sectionTemplate = sectionTemplate;
                    this.modalRef.componentInstance.templateCounts = counts;

                    this.modalRef.result.then((sectionTemplateID: number) => {
                        //Delete the section template
                        if (sectionTemplateID > 0) {
                            this.loaderService.show();
                            this.sectionTemplateService.deleteSectionTemplate(sectionTemplateID).pipe(finalize(() => this.loaderService.hide()))
                                .subscribe({
                                    next: (res: any) => {
                                        this.toastService.success("Section Template with ID " + sectionTemplateID + " deleted!");
                                        this.getAllSectionTemplates();
                                    },
                                    error: (error) => this.toastService.error(error?.error?.message)
                                });
                        }
                    });
                }
            });
    }


    /**
     * Displays a modal view for user to confirm transformation of 
     * section template to a global section template
     * 
     * @param sectionTemplate instance of section template which should be transformed
     */
    showTransformModal(sectionTemplate: SectionTemplateListItem) {
        if (!this.isWritable(sectionTemplate)) {
            return;
        }

        this.modalRef = this.modalService.open(SectionTemplateTransformModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.sectionTemplate = sectionTemplate;

        this.modalRef.result.then((sectionTemplateID: number) => {
            //Delete the section template
            if (sectionTemplateID > 0) {
                let params = {
                    'name': sectionTemplate.name,
                    'label': sectionTemplate.label,
                    'type': sectionTemplate.type ?? 'section',
                    'is_global': true,
                    'predefined': false,
                    'fields': JSON.stringify(sectionTemplate.fields),
                    'public_id': sectionTemplate.public_id
                }

                this.loaderService.show();

                this.sectionTemplateService.updateSectionTemplate(params).pipe(finalize(() => this.loaderService.hide()))
                    .subscribe({
                        next: (res: APIUpdateSingleResponse) => {
                            this.toastService.success(`Section Template with ID: ${sectionTemplate.public_id} transformed 
                                            to a Global Section Template!`);
                            this.getAllSectionTemplates();
                        },
                        error: (error) => this.toastService.error(error?.error?.message)
                    }
                    );
            }
        });
    }


    /**
     * Displays a modal view for user to clone a section template
     * 
     * @param sectionTemplate instance of section template which should be cloned
     */
    public showCloneModal(sectionTemplate: SectionTemplateListItem) {
        this.modalRef = this.modalService.open(SectionTemplateCloneModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.sectionTemplate = sectionTemplate;

        this.modalRef.result.then((values: any) => {
            if (!values) {
                return;
            }

            this.cloneSectionTemplate(sectionTemplate, values.templateLabel, !!values.isGlobal);
        }, () => { /* dismissed */ });
    }


    /**
     * Displays a preview of a section template with all fields. Any select declaring an OptionType
     * is resolved before the modal opens.
     * 
     * @param sectionTemplate The section template which should be previewed
     */
    public showTemplatePreview(sectionTemplate: SectionTemplateListItem) {
        this.loaderService.show();

        this.optionCatalog.resolveFieldOptions(sectionTemplate?.fields ?? []).pipe(
            takeUntil(this.unsubscribe),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: (resolvedFields) => this.openTemplatePreview(sectionTemplate, resolvedFields),
            error: () => this.toastService.error('The options of this section template could not be loaded.')
        });
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /** Virtual templates cannot be cloned - they have no public_id and a reserved name. */
    public isVirtual(sectionTemplate: SectionTemplateListItem): boolean {
        return isVirtualSectionTemplate(sectionTemplate);
    }


    /** Narrows to a stored template, so no write path can run for a virtual one. */
    private isWritable(sectionTemplate: SectionTemplateListItem): sectionTemplate is CmdbSectionTemplate {
        return !this.isVirtual(sectionTemplate);
    }


    /**
     * Creates new IDs for fields
     * 
     * @param fields Fields which require new IDs
     * @returns The given fields with new IDs
     */
    private setNewFieldIDs(fields: readonly Field[]): Field[] {
        return fields.map((field) => ({ ...field, name: this.generateFieldName(field.type) }));
    }


    /**
     * Retrives the label for the "Type" column of the table
     * @param sectionTemplate The template for which the label should be calculated
     * @returns (string): Type name for the given section template
     */
    public getTemplateTypeLabel(sectionTemplate: SectionTemplateListItem): string {
        if (sectionTemplate.predefined) {
            return "Predefined";
        }

        if (sectionTemplate.is_global) {
            return "Global";
        }

        return "Standard";
    }


    /**
     * Generates a new name for a field
     * @param fieldType Type of the field
     */
    private generateFieldName(fieldType: string) {
        return `${fieldType}-${uuidv4()}`
    }


    /**
     * Generates a unique name for section templates
     * 
     * @returns unique name for section templates
     */
    public generateSectionTemplateName(isGlobal: boolean = false) {
        if (isGlobal) {
            return `dg_gst-${uuidv4()}`;
        }

        return `section_template-${uuidv4()}`;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Clones a stored or virtual template into a new standard template. */
    private cloneSectionTemplate(sectionTemplate: SectionTemplateListItem, label: string, isGlobal: boolean): void {
        this.loaderService.show();

        this.cloneFields(sectionTemplate).pipe(
            takeUntil(this.unsubscribe),
            switchMap((fields) => this.sectionTemplateService.postSectionTemplate({
                'name': this.generateSectionTemplateName(isGlobal),
                'label': label,
                'type': sectionTemplate?.type ?? 'section',
                'is_global': isGlobal,
                'predefined': false,
                'fields': JSON.stringify(fields)
            })),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: () => {
                this.toastService.success('Section Template cloned!');
                this.getAllSectionTemplates();
            },
            error: (error) => this.toastService.error(error?.error?.message
                ?? 'The section template could not be cloned.')
        });
    }


    /**
     * Fields of the copy. A stored template is copied as it is; only a virtual template needs its
     * `option_type` selects materialised, because the copy must not depend on the catalog anymore.
     */
    private cloneFields(sectionTemplate: SectionTemplateListItem): Observable<Field[]> {
        const fields = sectionTemplate?.fields ?? [];

        if (!this.isVirtual(sectionTemplate)) {
            return of(this.setNewFieldIDs(fields));
        }

        return this.optionCatalog.resolveFieldOptions(fields).pipe(
            map((resolvedFields) => this.detachFields(resolvedFields))
        );
    }


    /** New field IDs and no `option_type`, so the clone is a plain, editable template. */
    private detachFields(fields: readonly Field[]): Field[] {
        return this.setNewFieldIDs(fields).map(({ option_type, options, ...field }) => (
            options ? { ...field, options: options.map(({ label }) => ({ name: label, label })) } : field
        ));
    }


    /** Drops `option_type` so the preview renders plain selects without the option manager buttons. */
    private withoutOptionManagers(fields: readonly Field[]): Field[] {
        return fields.map(({ option_type, ...field }) => field);
    }


    /** Previews a copy, so resolved options never reach the model the table holds. */
    private openTemplatePreview(sectionTemplate: SectionTemplateListItem, fields: Field[]): void {
        this.modalRef = this.modalService.open(PreviewModalComponent, {
            size: 'lg',
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        this.modalRef.componentInstance.sections = [{ ...sectionTemplate, fields: this.withoutOptionManagers(fields) }];
    }
}
