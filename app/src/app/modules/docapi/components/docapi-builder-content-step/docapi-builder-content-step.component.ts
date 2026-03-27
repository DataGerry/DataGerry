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
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { TemplateHelperService } from '../../../../settings/services/template-helper.service';
import { CmdbMode } from '../../../../framework/modes.enum';
import { ExternalObjectSelectorModalComponent } from '../external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from '../relation-template-selector-modal/relation-template-selector-modal.component';
import { ReportTemplateSelectorModalComponent } from '../report-template-selector-modal/report-template-selector-modal.component';
import { DEFAULT_PAGE_MARGINS, PageMargins, parsePageMarginsFromStyle } from '../../utils/page-margins.util';
import {
    DocapiDocumentOptionsModalComponent,
    DocumentOptionsModalResult
} from '../docapi-document-options/docapi-document-options-modal/docapi-document-options-modal.component';
import { DocapiAiAssistantModalComponent } from '../docapi-ai-assistant-modal/docapi-ai-assistant-modal.component';
import { DocapiEditorConfigService } from '../../services/docapi-editor-config.service';
import { environment } from '../../../../../environments/environment';
import { DEFAULT_COVER_PAGE, normalizeCoverPage } from '../../utils/cover-page.util';
import { DEFAULT_FOOTER, DEFAULT_HEADER, normalizeFooter, normalizeHeader } from '../../utils/page-section.util';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-builder-content-step',
    templateUrl: './docapi-builder-content-step.component.html',
    styleUrls: ['./docapi-builder-content-step.component.scss'],
    standalone: false
})
export class DocapiBuilderContentStepComponent {
    private readonly defaultPageMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };

    @Input()
    set preData(data: any) {
        if (data !== undefined) {
            this.contentForm?.patchValue({
                template_data: data?.template_data ?? '',
                cover_page: normalizeCoverPage(data?.cover_page),
                header: normalizeHeader(data?.header),
                footer: normalizeFooter(data?.footer)
            });
            this.pageMargins = parsePageMarginsFromStyle(data?.template_style, this.defaultPageMargins);
        }
    }

    @Input()
    set typeParam(data: any) {
        if (data) {
            this.templateType = data.templateType;
            this.templateTypeId = data?.parameters?.type ?? null;
            if (data.parameters?.type) {
                this.templateHelperService?.getObjectTemplateHelperData(data.parameters.type, '', 5, this.templateType).then(helperData => {
                    this.templateHelperData = helperData;
                });
            }
        }
    }

    @Input() public mode: CmdbMode;
    @Output() public previewRequested = new EventEmitter<void>();
    @Output() public pageMarginsChanged = new EventEmitter<PageMargins>();

    public modes = CmdbMode;
    public contentForm: UntypedFormGroup;
    public templateHelperData: any;
    public templateType: string = 'OBJECT';
    public templateTypeId: number | null = null;
    public editorConfig: Record<string, unknown>;

    private pageMargins: PageMargins = { ...this.defaultPageMargins };

    public get content() {
        return this.contentForm?.get('template_data');
    }

    constructor(
        private templateHelperService: TemplateHelperService,
        private modalService: NgbModal,
        private editorConfigService: DocapiEditorConfigService
    ) {
        this.contentForm = new UntypedFormGroup({
            template_data: new UntypedFormControl('', [Validators.required, Validators.max(15 * 1024 * 1024)]),
            cover_page: new UntypedFormGroup({
                activated: new UntypedFormControl(DEFAULT_COVER_PAGE.activated),
                content: new UntypedFormControl(DEFAULT_COVER_PAGE.content, [Validators.max(15 * 1024 * 1024)]),
                config: new UntypedFormControl(DEFAULT_COVER_PAGE.config)
            }),
            header: new UntypedFormGroup({
                activated: new UntypedFormControl(DEFAULT_HEADER.activated),
                content: new UntypedFormControl(DEFAULT_HEADER.content, [Validators.max(15 * 1024 * 1024)]),
                config: new UntypedFormControl(DEFAULT_HEADER.config)
            }),
            footer: new UntypedFormGroup({
                activated: new UntypedFormControl(DEFAULT_FOOTER.activated),
                content: new UntypedFormControl(DEFAULT_FOOTER.content, [Validators.max(15 * 1024 * 1024)]),
                config: new UntypedFormControl(DEFAULT_FOOTER.config)
            })
        });

        this.editorConfig = this.editorConfigService.createConfig({
            isCloudMode: environment.cloudMode,
            getTemplateType: () => this.templateType,
            getTemplateHelperData: () => this.templateHelperData,
            onPreviewRequested: () => this.previewRequested.emit(),
            onPageMarginsRequested: () => this.openPageMarginsDialog(),
            onAiAssistantRequested: (editor: any) => this.openAiAssistantModal(editor),
            onExternalObjectsRequested: (editor: any) => this.openExternalObjectsModal(editor),
            onRelationTemplateRequested: (editor: any) => this.openRelationTemplateModal(editor),
            onReportTemplateRequested: (editor: any) => this.openReportTemplateModal(editor)
        });
    }

    private openExternalObjectsModal(editor: any): void {
        const modalRef = this.modalService.open(ExternalObjectSelectorModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.result
            .then((template: string) => {
                if (!template) {
                    return;
                }

                editor.insertContent(template);
            })
            .catch(() => undefined);
    }

    private openRelationTemplateModal(editor: any): void {
        const modalRef = this.modalService.open(RelationTemplateSelectorModalComponent, {
            size: 'lg',
            backdrop: 'static'
        });

        modalRef.componentInstance.rootTypeId = this.templateTypeId;

        modalRef.result
            .then((template: string) => {
                if (!template) {
                    return;
                }

                editor.insertContent(template);
            })
            .catch(() => undefined);
    }

    private openReportTemplateModal(editor: any): void {
        const modalRef = this.modalService.open(ReportTemplateSelectorModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.result
            .then((template: string) => {
                if (!template) {
                    return;
                }

                editor.insertContent(template);
            })
            .catch(() => undefined);
    }

    private openPageMarginsDialog(): void {
        const modalRef = this.modalService.open(DocapiDocumentOptionsModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.componentInstance.initialMargins = { ...this.pageMargins };
        modalRef.componentInstance.initialCoverPage = normalizeCoverPage(this.contentForm?.get('cover_page')?.value);
        modalRef.componentInstance.initialHeader = normalizeHeader(this.contentForm?.get('header')?.value);
        modalRef.componentInstance.initialFooter = normalizeFooter(this.contentForm?.get('footer')?.value);
        modalRef.componentInstance.templateType = this.templateType;
        modalRef.componentInstance.templateTypeId = this.templateTypeId;
        modalRef.componentInstance.templateHelperData = this.templateHelperData;

        modalRef.result
            .then((result: DocumentOptionsModalResult) => {
                if (!result) {
                    return;
                }

                this.pageMargins = result.margins;
                this.pageMarginsChanged.emit(result.margins);
                this.contentForm?.get('cover_page')?.patchValue(normalizeCoverPage(result.coverPage));
                this.contentForm?.get('header')?.patchValue(normalizeHeader(result.header));
                this.contentForm?.get('footer')?.patchValue(normalizeFooter(result.footer));
            })
            .catch(() => undefined);
    }

    private openAiAssistantModal(editor: any): void {
        const modalRef = this.modalService.open(DocapiAiAssistantModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.result
            .then((generatedHtml: string) => {
                if (!generatedHtml) {
                    return;
                }

                editor.insertContent(generatedHtml);
            })
            .catch(() => undefined);
    }
}
