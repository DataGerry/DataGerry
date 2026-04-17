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
import { Injectable } from '@angular/core';
import { faWandMagicSparkles } from '@fortawesome/free-solid-svg-icons';
import {
    DOCAPI_SUPPORTED_CSS_PROPERTIES,
    DOCAPI_UNSUPPORTED_CSS_PROPERTIES
} from '../constants/docapi-css-support.constants';
/* ------------------------------------------------------------------------------------------------------------------ */

declare var tinymce;

interface DocapiEditorConfigContext {
    isCloudMode: boolean;
    getTemplateType: () => string;
    getTemplateHelperData: () => any[];
    onPreviewRequested: () => void;
    onPageMarginsRequested: () => void;
    onEditorInitialized?: (editor: any) => void;
    onEditorContentChanged?: (editor: any) => void;
    onAiAssistantRequested?: (editor: any) => void;
    onExternalObjectsRequested?: (editor: any) => void;
    onRelationTemplateRequested?: (editor: any) => void;
    onReportTemplateRequested?: (editor: any) => void;
}

@Injectable({
    providedIn: 'root'
})
export class DocapiEditorConfigService {
    private static readonly CSS_SUPPORT_BUTTON_NAME = 'docapiCssSupport';

    public createConfig(context: DocapiEditorConfigContext): Record<string, unknown> {
        const objectTemplate = this.isObjectTemplate(context);
        const toolbar2 = this.resolveSecondaryToolbar(context.isCloudMode, objectTemplate);

        return {
            base_url: '/tinymce',
            suffix: '.min',
            height: 500,
            menubar: false,
            plugins: [
                'accordion', 'advlist', 'anchor', 'autolink', 'autosave', 'charmap', 'code',
                'codesample', 'directionality', 'emoticons', 'fullscreen', 'help', 'image',
                'importcss', 'insertdatetime', 'link', 'lists', 'media',
                'nonbreaking', 'noneditable', 'pagebreak', 'preview', 'quickbars', 'save', 'searchreplace',
                'table', 'visualblocks', 'visualchars', 'wordcount', 'hr'
            ],
            toolbar1:
                'undo redo | formatselect | bold italic underline forecolor backcolor removeformat | \
                alignleft aligncenter alignright alignjustify | \
                bullist numlist outdent indent | image table hr pagebreak | code ',
            toolbar2,
            noneditable_noneditable_class: 'mceNonEditable',
            paste_data_images: true,
            automatic_uploads: true,
            file_picker_types: 'image',
            file_picker_callback: (cb) => {
                const input = document.createElement('input');
                input.setAttribute('type', 'file');
                input.setAttribute('accept', 'image/png,image/jpeg');
                input.onchange = () => {
                    const file = input?.files?.[0];
                    if (!file) {
                        return;
                    }
                    const reader = new FileReader();
                    reader.onload = () => {
                        const id = 'blobid' + (new Date()).getTime();
                        const blobCache = tinymce?.activeEditor?.editorUpload?.blobCache;
                        const base64 = (reader?.result as string).split(',')[1];
                        const blobInfo = blobCache?.create(id, file, base64);
                        blobCache?.add(blobInfo);
                        cb(blobInfo.blobUri(), { title: file.name });
                    };
                    reader.readAsDataURL(file);
                };
                input.click();
            },
            pagebreak_separator: '<pdf:nextpage />',
            extended_valid_elements: 'pdf:barcode[*]',
            custom_elements: 'pdf:barcode',
            valid_children: '-pdf:barcode[*]',
            content_css: '/assets/css/tinymce_custom.css',
            setup: (editor) => this.setupEditor(editor, context)
        };
    }

    private setupEditor(editor: any, context: DocapiEditorConfigContext): void {
        const objectTemplate = this.isObjectTemplate(context);

        editor?.on('init', () => {
            this.installSourceCodeCommand(editor);
            context.onEditorInitialized?.(editor);
        });
        editor?.on('SetContent Change KeyUp Undo Redo', () => context.onEditorContentChanged?.(editor));

        if (context.isCloudMode) {
            const [faWidth, faHeight, , , faSvgPathData] = faWandMagicSparkles.icon;
            const aiAssistantPath = Array.isArray(faSvgPathData) ? faSvgPathData[0] : faSvgPathData;

            editor?.ui?.registry?.addIcon('aiassistant', `
                <svg width="24" height="24" viewBox="0 0 ${faWidth} ${faHeight}" aria-hidden="true">
                    <path d="${aiAssistantPath}" fill="currentColor"></path>
                </svg>
            `);
        }

        editor?.ui?.registry?.addMenuButton('cmdbdata', {
            text: 'CMDB Data',
            icon: 'plus',
            fetch: (callback) => callback(this.getCmdbDataMenuItems(editor, context))
        });

        if (!objectTemplate) {
            editor?.ui?.registry?.addMenuButton('placeholders', {
                text: 'Template Context',
                fetch: (callback) => callback(this.getPlaceholderMenuItems(editor))
            });
        }

        editor?.ui?.registry?.addButton('previewdoc', {
            text: 'Preview',
            icon: 'preview',
            tooltip: 'Preview Document',
            onAction: () => context.onPreviewRequested()
        });

        if (!objectTemplate) {
            editor?.ui?.registry?.addButton('pagemargins', {
                text: 'Document Options',
                tooltip: 'Configure document-level options',
                onAction: () => context.onPageMarginsRequested()
            });
        }

        if (context.isCloudMode && !objectTemplate) {
            editor?.ui?.registry?.addButton('aiassistant', {
                icon: 'aiassistant',
                tooltip: 'AI Assistant (using OpenAI API)',
                onAction: () => context.onAiAssistantRequested?.(editor)
            });
        }
    }

    private resolveSecondaryToolbar(isCloudMode: boolean, objectTemplate: boolean): string {
        if (objectTemplate) {
            return 'cmdbdata | previewdoc';
        }

        return isCloudMode
            ? 'cmdbdata placeholders pagemargins aiassistant | previewdoc'
            : 'cmdbdata placeholders pagemargins | previewdoc';
    }

    private isObjectTemplate(context: DocapiEditorConfigContext): boolean {
        return (context.getTemplateType?.() ?? '').toUpperCase() === 'OBJECT';
    }

    private installSourceCodeCommand(editor: any): void {
        if (!editor || editor.__docapiSourceCodeCommandInstalled) {
            return;
        }

        editor.addCommand('mceCodeEditor', () => this.openSourceCodeDialog(editor));
        editor.__docapiSourceCodeCommandInstalled = true;
    }

    private openSourceCodeDialog(editor: any): void {
        const editorContent = editor.getContent({ source_view: true });
        editor.windowManager.open({
            title: 'Source Code',
            size: 'large',
            body: {
                type: 'panel',
                items: [
                    {
                        type: 'textarea',
                        name: 'code'
                    }
                ]
            },
            buttons: [
                {
                    type: 'custom',
                    name: DocapiEditorConfigService.CSS_SUPPORT_BUTTON_NAME,
                    text: 'Show CSS compatibility details',
                    align: 'start'
                },
                {
                    type: 'cancel',
                    name: 'cancel',
                    text: 'Cancel'
                },
                {
                    type: 'submit',
                    name: 'save',
                    text: 'Save',
                    primary: true
                }
            ],
            initialData: {
                code: editorContent
            },
            onAction: (_dialogApi: any, details: any) => {
                if (details?.name === DocapiEditorConfigService.CSS_SUPPORT_BUTTON_NAME) {
                    this.openCssCompatibilityDialog(editor);
                }
            },
            onSubmit: (dialogApi: any) => {
                const html = dialogApi.getData()?.code ?? '';
                editor.focus();
                editor.undoManager.transact(() => {
                    editor.setContent(html);
                });
                editor.selection.setCursorLocation();
                editor.nodeChanged();
                dialogApi.close();
            }
        });
    }

    private openCssCompatibilityDialog(editor: any): void {
        editor?.windowManager?.open({
            title: 'CSS compatibility for PDF rendering',
            body: {
                type: 'panel',
                items: [
                    {
                        type: 'htmlpanel',
                        html: this.buildCssCompatibilityHtml()
                    }
                ]
            },
            buttons: [
                {
                    type: 'cancel',
                    text: 'Close',
                    primary: true
                }
            ]
        });
    }

    private buildCssCompatibilityHtml(): string {
        const supported = DOCAPI_SUPPORTED_CSS_PROPERTIES
            .map((property) => `<li>${property}</li>`)
            .join('');
        const unsupported = DOCAPI_UNSUPPORTED_CSS_PROPERTIES
            .map((property) => `<li>${property}</li>`)
            .join('');

        return `
            <div style="line-height:1.45;">
                <p style="margin:0 0 10px 0;">Only a limited CSS subset is supported by PDF rendering.</p>
                <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;">
                    <div style="min-width:260px;flex:1;">
                        <p style="margin:0 0 6px 0;font-weight:600;">Supported properties</p>
                        <ul style="margin:0;padding-left:18px;">${supported}</ul>
                    </div>
                    <div style="min-width:260px;flex:1;">
                        <p style="margin:0 0 6px 0;font-weight:600;">Not supported</p>
                        <ul style="margin:0;padding-left:18px;">${unsupported}</ul>
                    </div>
                </div>
            </div>
        `;
    }

    private getCmdbDataMenuItems(editor: any, context: DocapiEditorConfigContext): any[] {
        const items = [
            this.getBarcodeMenuItem(editor),
            {
                type: 'nestedmenuitem',
                text: 'Object Data',
                icon: 'code-sample',
                getSubmenuItems: () => this.getObjectDataMenuItems(editor, context.getTemplateHelperData(), true, context)
            }
        ];

        if (context.getTemplateType() === 'DEFAULT') {
            if (context.onExternalObjectsRequested) {
                items.push({
                    type: 'menuitem',
                    text: 'External objects',
                    icon: 'link',
                    onAction: () => context.onExternalObjectsRequested(editor)
                });
            }

            if (context.onReportTemplateRequested) {
                items.push({
                    type: 'menuitem',
                    text: 'Report',
                    icon: 'table',
                    onAction: () => context.onReportTemplateRequested(editor)
                });
            }
        }

        return items;
    }

    private getPlaceholderMenuItems(editor: any): any[] {
        return [
            {
                type: 'nestedmenuitem',
                text: 'Template Metadata',
                icon: 'info',
                getSubmenuItems: () => [
                    this.getPlaceholderTokenMenuItem(editor, 'author', 'Author'),
                    this.getPlaceholderTokenMenuItem(editor, 'template_label', 'Template Label'),
                    this.getPlaceholderTokenMenuItem(editor, 'user_display_name', 'User Display Name'),
                    this.getPlaceholderTokenMenuItem(editor, 'current_time', 'Current Time')
                ]
            },
            {
                type: 'nestedmenuitem',
                text: 'Pagination',
                icon: 'table',
                getSubmenuItems: () => [
                    this.getPlaceholderTokenMenuItem(editor, 'new_page', 'New Page'),
                    this.getPlaceholderTokenMenuItem(editor, 'current_page_count', 'Current Page Count'),
                    this.getPlaceholderTokenMenuItem(editor, 'total_page_count', 'Total Page Count')
                ]
            }
        ];
    }

    private getPlaceholderTokenMenuItem(editor: any, key: string, text: string): any {
        return {
            type: 'menuitem',
            text,
            onAction: () => editor.insertContent(`{{${key}}}`)
        };
    }

    private getObjectDataMenuItems(editor: any, templateHelperData: any[] = [], isRoot = false, context: DocapiEditorConfigContext): any[] {
        const data = Array.isArray(templateHelperData) ? templateHelperData : [];
        const items = [];

        for (const item of data) {
            if (item?.subdata) {
                items.push({
                    type: 'nestedmenuitem',
                    text: item.label,
                    icon: 'chevron-right',
                    getSubmenuItems: () => this.getObjectDataMenuItems(editor, item.subdata, false, context)
                });
                continue;
            }

            const icon = item?.label === 'Public ID' ? 'character-count' : 'sourcecode';
            items.push({
                type: 'menuitem',
                text: item?.label,
                icon,
                onAction: () => editor.insertContent(item?.templatedata)
            });
        }

        if (isRoot && context.getTemplateType() === 'DEFAULT' && context.onRelationTemplateRequested) {
            items.push({
                type: 'menuitem',
                text: 'Relations',
                icon: 'link',
                onAction: () => context.onRelationTemplateRequested(editor)
            });
        }

        return items;
    }

    private getBarcodeMenuItem(editor: any): any {
        return {
            type: 'menuitem',
            text: 'Barcode',
            icon: 'align-justify',
            onAction: () => {
                const selection = editor.selection.getNode();
                const preData = {};
                if (selection?.tagName === 'PDF:BARCODE') {
                    preData['type'] = selection?.attributes?.getNamedItem('type')?.value;
                    preData['content'] = selection?.attributes?.getNamedItem('value')?.value;
                }
                editor?.windowManager?.open({
                    title: 'Insert Barcode',
                    body: {
                        type: 'panel',
                        items: [
                            {
                                type: 'input',
                                name: 'content',
                                label: 'Barcode Content'
                            },
                            {
                                type: 'selectbox',
                                name: 'type',
                                label: 'Barcode Type',
                                items: [
                                    { value: 'qr', text: 'QR' },
                                    { value: 'code128', text: 'Code 128' }
                                ]
                            }
                        ]
                    },
                    buttons: [
                        {
                            type: 'submit',
                            text: 'OK'
                        }
                    ],
                    initialData: preData,
                    onSubmit: (dialogApi) => {
                        const barcodeContent = dialogApi?.getData()?.['content'];
                        const barcodeType = dialogApi?.getData()?.['type'];
                        const barcodeElementAttr = {
                            class: 'mceNonEditable',
                            type: barcodeType,
                            value: barcodeContent
                        };

                        if (barcodeType === 'qr') {
                            barcodeElementAttr['barwidth'] = '3cm';
                            barcodeElementAttr['barheight'] = '3cm';
                        }

                        const barcodeElement = editor?.dom?.create('pdf:barcode', barcodeElementAttr);
                        if (preData['content']) {
                            const selectionNext = editor?.selection?.getNode()?.nextSibling;
                            editor?.dom?.remove(selection);
                            if (selectionNext) {
                                editor?.selection?.setCursorLocation(selectionNext);
                            }
                        }
                        editor?.insertContent(barcodeElement?.outerHTML);
                        dialogApi?.close();
                    }
                });
            }
        };
    }
}
