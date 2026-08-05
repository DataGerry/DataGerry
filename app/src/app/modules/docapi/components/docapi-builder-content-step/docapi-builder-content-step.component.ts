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
    inject,
    Input,
    OnDestroy,
    Output,
} from '@angular/core';
import { CdkDragDrop } from '@angular/cdk/drag-drop';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';

import { TemplateHelperService } from '../../../../settings/services/template-helper.service';
import { CmdbMode } from '../../../../framework/modes.enum';
import { ExternalObjectSelectorModalComponent } from '../external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from '../relation-template-selector-modal/relation-template-selector-modal.component';
import { ReportTemplateSelectorModalComponent } from '../report-template-selector-modal/report-template-selector-modal.component';
import {
    createPageConfigFromMargins,
    DEFAULT_PAGE_MARGINS,
    PageConfig,
    PageMargins,
    parseMarginValue,
    parsePageMarginsFromPageConfig,
    parsePageMarginsFromStyle
} from '../../utils/page-margins.util';
import {
    DocapiDocumentOptionsModalComponent,
    DocumentOptionsModalResult
} from '../docapi-document-options/docapi-document-options-modal/docapi-document-options-modal.component';
import { DocapiAiAssistantModalComponent } from '../docapi-ai-assistant-modal/docapi-ai-assistant-modal.component';
import { DocapiEditorConfigService } from '../../services/docapi-editor-config.service';
import { DEFAULT_COVER_PAGE, normalizeCoverPage } from '../../utils/cover-page.util';
import { DEFAULT_FOOTER, DEFAULT_HEADER, normalizeFooter, normalizeHeader } from '../../utils/page-section.util';
import { DEFAULT_TABLE_OF_CONTENTS, normalizeTableOfContents } from '../../utils/table-of-contents.util';
import { OutlineContextMenuState, OutlineDropListData, OutlineNavItem } from '../../models/docapi-outline.model';
import { buildOutlineTree } from '../../utils/docapi-outline-tree.util';
import { duplicateSectionById } from '../../utils/docapi-outline-duplicate.util';
import { deleteSectionById } from '../../utils/docapi-outline-delete.util';
import { moveItemInTree, serializeTreeToHtml } from '../../utils/docapi-outline-tree-move.util';
import { DocapiOutlineContextMenuService } from '../../services/docapi-outline-context-menu.service';

interface EditorInstance {
    getBody: () => HTMLElement;
    getContent: (args?: { format: 'html' }) => string;
    setContent: (content: string) => void;
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
    page_config?: unknown;
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
    host: {
        '(document:click)': 'onDocumentClick()',
        '(document:keydown.escape)': 'onEscapePressed()'
    },
    standalone: false
})
export class DocapiBuilderContentStepComponent implements OnDestroy {
    @Input() public mode: CmdbMode;

    @Input()
    set preData(data: TemplateInputData | undefined) {
        if (!data) return;

        const pageConfigMargins = parsePageMarginsFromPageConfig(data.page_config, this.defaultPageMargins);
        const styleMargins = parsePageMarginsFromStyle(data.template_style, this.defaultPageMargins);
        const hasPageConfigMargins = this.hasPersistedPageConfigMargins(data.page_config);
        this.pageMargins = hasPageConfigMargins ? pageConfigMargins : styleMargins;

        this.contentForm.patchValue({
            template_data: data.template_data ?? '',
            cover_page: normalizeCoverPage(data.cover_page),
            header: normalizeHeader(data.header),
            footer: normalizeFooter(data.footer),
            table_of_contents: normalizeTableOfContents(data.table_of_contents),
            page_config: createPageConfigFromMargins(this.pageMargins)
        });
    }

    @Input()
    set typeParam(data: TypeParamData | undefined) {
        if (!data) return;

        this.templateType = data.templateType;
        this.templateTypeId = data.parameters?.type ?? null;
        this.initEditorConfig();

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

    public readonly modes = CmdbMode;
    public contentForm: FormGroup;
    public editorConfig: Record<string, unknown> | null = null;

    public templateHelperData: any[] = [];
    public templateType = 'DEFAULT';
    public templateTypeId: number | null = null;

    public headingNavigation: OutlineNavItem[] = [];
    public activeHeadingId: string | null = null;
    public outlineCollapsed = false;
    public outlineContextMenu: OutlineContextMenuState = {
        visible: false,
        x: 0,
        y: 0,
        headingId: null
    };

    private readonly headingSyncDebounceMs = 160;
    private readonly defaultPageMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };
    private readonly headingElementMap = new Map<string, HTMLElement>();
    private readonly templateHelperService = inject(TemplateHelperService);
    private readonly modalService = inject(NgbModal);
    private readonly editorConfigService = inject(DocapiEditorConfigService);
    private readonly outlineContextMenuService = inject(DocapiOutlineContextMenuService);
    private readonly cdr = inject(ChangeDetectorRef);

    private pageMargins: PageMargins = { ...this.defaultPageMargins };
    private headingSyncTimeout?: number;
    private editorInstance?: EditorInstance;


    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        this.initForm();
    }

    public ngOnDestroy(): void {
        this.clearHeadingSyncTimeout();
        this.headingElementMap.clear();
    }


    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onDocumentClick(): void {
        this.closeOutlineContextMenu();
    }

    public onEscapePressed(): void {
        this.closeOutlineContextMenu();
    }


    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get content(): FormControl<string> | null {
        return this.contentForm.get('template_data') as FormControl<string>;
    }

    public jumpToHeading(item: OutlineNavItem): void {
        this.closeOutlineContextMenu();

        const target = this.headingElementMap.get(item.id);
        if (!target || !this.editorInstance) return;

        this.editorInstance.focus();
        this.editorInstance.selection.select(target);
        this.editorInstance.selection.scrollIntoView(target, true);
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });

        this.activeHeadingId = item.id;
        this.cdr.markForCheck();
    }

    public openOutlineContextMenu(event: MouseEvent, item: OutlineNavItem): void {
        event.preventDefault();
        event.stopPropagation();

        this.outlineContextMenu = this.outlineContextMenuService.createOpenedStateFromPointer(event.clientX, event.clientY, item.id);
        this.cdr.markForCheck();
    }

    public onOutlineItemKeydown(event: KeyboardEvent, item: OutlineNavItem): void {
        const nextState = this.outlineContextMenuService.tryCreateOpenedStateFromKeyboard(event, item.id);
        if (!nextState) {
            return;
        }

        this.outlineContextMenu = nextState;
        this.cdr.markForCheck();
    }

    public onContextMenuContainerClick(event: MouseEvent): void {
        event.stopPropagation();
    }

    public duplicateFromContextMenu(): void {
        const headingId = this.outlineContextMenu.headingId;
        this.closeOutlineContextMenu();

        if (!headingId || !this.editorInstance) {
            return;
        }

        const htmlContent = this.getEditorHtmlContent();
        const duplicatedContent = duplicateSectionById(htmlContent, headingId);
        if (duplicatedContent === htmlContent) {
            return;
        }

        this.applyEditorHtmlContent(duplicatedContent);
    }

    public deleteFromContextMenu(): void {
        const headingId = this.outlineContextMenu.headingId;
        this.closeOutlineContextMenu();

        if (!headingId || !this.editorInstance) {
            return;
        }

        const htmlContent = this.getEditorHtmlContent();
        const contentAfterDelete = deleteSectionById(htmlContent, headingId);
        if (contentAfterDelete === htmlContent) {
            return;
        }

        this.applyEditorHtmlContent(contentAfterDelete);
        this.activeHeadingId = null;
    }

    public closeOutlineContextMenu(): void {
        const nextState = this.outlineContextMenuService.closeIfOpen(this.outlineContextMenu);
        if (nextState === this.outlineContextMenu) {
            return;
        }

        this.outlineContextMenu = nextState;
        this.cdr.markForCheck();
    }

    public trackByHeadingId(_index: number, item: OutlineNavItem): string {
        return item.id;
    }

    public createDropListData(
        items: OutlineNavItem[],
        parentHeadingId: string | null,
        parentLevel: number
    ): OutlineDropListData {
        return { items, parentHeadingId, parentLevel };
    }

    public onOutlineDrop(event: CdkDragDrop<OutlineDropListData>): void {
        if (!this.editorInstance) {
            return;
        }

        const currentList = event.container.data;
        if (!currentList) {
            return;
        }

        const movedItem = event.item.data as OutlineNavItem;
        if (!movedItem) {
            return;
        }

        const htmlContent = this.getEditorHtmlContent();
        const nextTree = moveItemInTree(
            this.headingNavigation,
            movedItem.id,
            currentList.parentHeadingId,
            event.currentIndex
        );
        const contentAfterMove = serializeTreeToHtml(nextTree, htmlContent);

        if (contentAfterMove === htmlContent) {
            return;
        }

        this.applyEditorHtmlContent(contentAfterMove);
        this.headingNavigation = nextTree;
        this.activeHeadingId = movedItem.id;
    }


    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

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
            }),
            page_config: new FormControl<PageConfig>(createPageConfigFromMargins(this.defaultPageMargins))
        });
    }

    private initEditorConfig(): void {
        this.editorConfig = this.editorConfigService.createConfig({
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

        const outlineTree = buildOutlineTree(body);
        this.headingElementMap.clear();
        outlineTree.elementMap.forEach((element, id) => this.headingElementMap.set(id, element));
        this.headingNavigation = outlineTree.tree;
    }

    private getEditorHtmlContent(): string {
        const body = this.editorInstance?.getBody();
        return body?.innerHTML ?? '';
    }

    private applyEditorHtmlContent(content: string): void {
        if (!this.editorInstance) {
            return;
        }

        this.editorInstance.setContent(content);
        this.scheduleHeadingSync(0);
    }


    /* ----------------------------------------------------- MODALS ---------------------------------------------------- */

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

                this.contentForm.patchValue({
                    cover_page: normalizeCoverPage(result.coverPage),
                    header: normalizeHeader(result.header),
                    footer: normalizeFooter(result.footer),
                    table_of_contents: normalizeTableOfContents(result.tableOfContents),
                    page_config: createPageConfigFromMargins(result.margins)
                });

                this.cdr.markForCheck();
            })
            .catch(() => undefined);
    }

    private hasPersistedPageConfigMargins(pageConfig: unknown): boolean {
        if (!pageConfig || typeof pageConfig !== 'object') {
            return false;
        }

        const margin = (pageConfig as PageConfig).margin;
        if (!margin || typeof margin !== 'object') {
            return false;
        }

        return (
            parseMarginValue(margin['margin-top']) !== null
            && parseMarginValue(margin['margin-bottom']) !== null
            && parseMarginValue(margin['margin-left']) !== null
            && parseMarginValue(margin['margin-right']) !== null
        );
    }
}
