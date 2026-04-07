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
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnDestroy,
    Output
} from '@angular/core';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';

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
import { DEFAULT_TABLE_OF_CONTENTS, normalizeTableOfContents } from '../../utils/table-of-contents.util';

export interface HeadingNavItem {
    id: string;
    level: number;
    text: string;
    children: HeadingNavItem[];
}

interface EditorInstance {
    getBody: () => HTMLElement;
    focus: () => void;
    selection: {
        select: (node: HTMLElement) => void;
        scrollIntoView: (node: HTMLElement, alignTop: boolean) => void;
    };
    insertContent: (content: string) => void;
}

interface TemplateInputData {
    template_data?: string;
    cover_page?: unknown;
    header?: unknown;
    footer?: unknown;
    table_of_contents?: unknown;
    template_style?: string;
}

interface TypeParamData {
    templateType: string;
    parameters?: { type?: number };
}

@Component({
    selector: 'cmdb-docapi-builder-content-step',
    templateUrl: './docapi-builder-content-step.component.html',
    styleUrls: ['./docapi-builder-content-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class DocapiBuilderContentStepComponent implements OnDestroy {
    @Input() public mode: CmdbMode;

    @Input()
    set preData(data: TemplateInputData | undefined) {
        if (!data) return;

        this.contentForm.patchValue({
            template_data: data.template_data ?? '',
            cover_page: normalizeCoverPage(data.cover_page),
            header: normalizeHeader(data.header),
            footer: normalizeFooter(data.footer),
            table_of_contents: normalizeTableOfContents(data.table_of_contents)
        });
        this.pageMargins = parsePageMarginsFromStyle(data.template_style, this.defaultPageMargins);
    }

    @Input()
    set typeParam(data: TypeParamData | undefined) {
        if (!data) return;

        this.templateType = data.templateType;
        this.templateTypeId = data.parameters?.type ?? null;

        if (this.templateTypeId) {
            this.templateHelperService
                .getObjectTemplateHelperData(this.templateTypeId, '', 5, this.templateType)
                .then(helperData => {
                    this.templateHelperData = helperData;
                    this.cdr.markForCheck();
                });
        }
    }

    @Output() public readonly previewRequested = new EventEmitter<void>();
    @Output() public readonly pageMarginsChanged = new EventEmitter<PageMargins>();

    public readonly modes = CmdbMode;
    public contentForm: FormGroup;
    public editorConfig: Record<string, unknown>;

    public templateHelperData: any[] = [];
    public templateType = 'OBJECT';
    public templateTypeId: number | null = null;

    public headingNavigation: HeadingNavItem[] = [];
    public activeHeadingId: string | null = null;
    public outlineCollapsed = true;

    private readonly headingSyncDebounceMs = 160;
    private readonly defaultPageMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };
    private readonly headingElementMap = new Map<string, HTMLElement>();

    private pageMargins: PageMargins = { ...this.defaultPageMargins };
    private headingSyncTimeout?: number;
    private editorInstance?: EditorInstance;

    constructor(
        private readonly templateHelperService: TemplateHelperService,
        private readonly modalService: NgbModal,
        private readonly editorConfigService: DocapiEditorConfigService,
        private readonly cdr: ChangeDetectorRef
    ) {
        this.initForm();
        this.initEditorConfig();
    }

    public ngOnDestroy(): void {
        this.clearHeadingSyncTimeout();
        this.headingElementMap.clear();
    }

    public get content(): FormControl<string> | null {
        return this.contentForm.get('template_data') as FormControl<string>;
    }

    public jumpToHeading(item: HeadingNavItem): void {
        const target = this.headingElementMap.get(item.id);
        if (!target || !this.editorInstance) return;

        this.editorInstance.focus();
        this.editorInstance.selection.select(target);
        this.editorInstance.selection.scrollIntoView(target, true);
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });

        this.activeHeadingId = item.id;
        this.cdr.markForCheck();
    }

    public trackByHeadingId(_index: number, item: HeadingNavItem): string {
        return item.id;
    }

    private initForm(): void {
        this.contentForm = new FormGroup({
            template_data: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.max(15 * 1024 * 1024)] }),
            cover_page: new FormGroup({
                activated: new FormControl(DEFAULT_COVER_PAGE.activated),
                content: new FormControl(DEFAULT_COVER_PAGE.content, [Validators.max(15 * 1024 * 1024)]),
                config: new FormControl(DEFAULT_COVER_PAGE.config)
            }),
            header: new FormGroup({
                activated: new FormControl(DEFAULT_HEADER.activated),
                content: new FormControl(DEFAULT_HEADER.content, [Validators.max(15 * 1024 * 1024)]),
                config: new FormControl(DEFAULT_HEADER.config)
            }),
            footer: new FormGroup({
                activated: new FormControl(DEFAULT_FOOTER.activated),
                content: new FormControl(DEFAULT_FOOTER.content, [Validators.max(15 * 1024 * 1024)]),
                config: new FormControl(DEFAULT_FOOTER.config)
            }),
            table_of_contents: new FormGroup({
                activated: new FormControl(DEFAULT_TABLE_OF_CONTENTS.activated),
                config: new FormControl(normalizeTableOfContents(DEFAULT_TABLE_OF_CONTENTS).config)
            })
        });
    }

    private initEditorConfig(): void {
        this.editorConfig = this.editorConfigService.createConfig({
            isCloudMode: environment.cloudMode,
            getTemplateType: () => this.templateType,
            getTemplateHelperData: () => this.templateHelperData,
            onPreviewRequested: () => this.previewRequested.emit(),
            onPageMarginsRequested: () => this.openPageMarginsDialog(),
            onEditorInitialized: (editor: EditorInstance) => {
                this.editorInstance = editor;
                this.scheduleHeadingSync(0);
            },
            onEditorContentChanged: () => this.scheduleHeadingSync(),
            onAiAssistantRequested: () => this.openModalAndInsertContent(DocapiAiAssistantModalComponent, { size: 'xl' }),
            onExternalObjectsRequested: () => this.openModalAndInsertContent(ExternalObjectSelectorModalComponent, { size: 'xl' }),
            onRelationTemplateRequested: () => this.openModalAndInsertContent(RelationTemplateSelectorModalComponent, { size: 'lg' }, { rootTypeId: this.templateTypeId }),
            onReportTemplateRequested: () => this.openModalAndInsertContent(ReportTemplateSelectorModalComponent, { size: 'xl' })
        });
    }

    private scheduleHeadingSync(delay = this.headingSyncDebounceMs): void {
        this.clearHeadingSyncTimeout();

        this.headingSyncTimeout = window.setTimeout(() => {
            this.syncHeadingNavigation();
            this.cdr.markForCheck();
        }, delay);
    }

    private clearHeadingSyncTimeout(): void {
        if (this.headingSyncTimeout !== undefined) {
            window.clearTimeout(this.headingSyncTimeout);
            this.headingSyncTimeout = undefined;
        }
    }

    private syncHeadingNavigation(): void {
        const body = this.editorInstance?.getBody();
        if (!body) {
            this.headingElementMap.clear();
            this.headingNavigation = [];
            return;
        }

        const headingNodes = Array.from(body.querySelectorAll('h1, h2, h3')) as HTMLElement[];
        const tree: HeadingNavItem[] = [];
        const stack: HeadingNavItem[] = [];

        this.headingElementMap.clear();

        headingNodes.forEach((node, index) => {
            const level = Number(node.tagName.replace('H', ''));
            if (![1, 2, 3].includes(level)) return;

            const text = (node.innerText || node.textContent || '').trim() || 'Untitled heading';
            const headingId = `heading-${index}`;
            const headingItem: HeadingNavItem = { id: headingId, level, text, children: [] };

            this.headingElementMap.set(headingId, node);

            // Resolve hierarchy
            while (stack.length > 0 && stack[stack.length - 1].level >= level) {
                stack.pop();
            }

            if (stack.length === 0) {
                tree.push(headingItem);
            } else {
                stack[stack.length - 1].children.push(headingItem);
            }

            stack.push(headingItem);
        });

        this.headingNavigation = tree;
    }

    private openModalAndInsertContent<T>(
        component: any,
        options: NgbModalOptions,
        instanceInputs?: Partial<T>
    ): void {
        const modalRef = this.modalService.open(component, { backdrop: 'static', ...options });

        if (instanceInputs) {
            Object.assign(modalRef.componentInstance, instanceInputs);
        }

        modalRef.result
            .then((content: string) => {
                if (content && this.editorInstance) {
                    this.editorInstance.insertContent(content);
                }
            })
            .catch(() => undefined); // Ignore dismissals
    }

    private openPageMarginsDialog(): void {
        const modalRef = this.modalService.open(DocapiDocumentOptionsModalComponent, {
            size: 'xl',
            backdrop: 'static',
            scrollable: true
        });

        Object.assign(modalRef.componentInstance, {
            initialMargins: { ...this.pageMargins },
            initialCoverPage: normalizeCoverPage(this.contentForm.get('cover_page')?.value),
            initialHeader: normalizeHeader(this.contentForm.get('header')?.value),
            initialFooter: normalizeFooter(this.contentForm.get('footer')?.value),
            initialTableOfContents: normalizeTableOfContents(this.contentForm.get('table_of_contents')?.value),
            templateType: this.templateType,
            templateTypeId: this.templateTypeId,
            templateHelperData: this.templateHelperData
        });

        modalRef.result
            .then((result: DocumentOptionsModalResult) => {
                if (!result) return;

                this.pageMargins = result.margins;
                this.pageMarginsChanged.emit(result.margins);

                this.contentForm.patchValue({
                    cover_page: normalizeCoverPage(result.coverPage),
                    header: normalizeHeader(result.header),
                    footer: normalizeFooter(result.footer),
                    table_of_contents: normalizeTableOfContents(result.tableOfContents)
                });

                this.cdr.markForCheck();
            })
            .catch(() => undefined);
    }
}