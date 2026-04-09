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
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
export class DocTemplate {
    public public_id: number;
    public name: string;
    public label: string;
    public author_id: number;
    public active: boolean;
    public description: string;
    public template_data: string;
    public template_style: string;
    public template_type: string;
    public template_parameters: object;
    public header: DocTemplatePageSection;
    public footer: DocTemplatePageSection;
    public table_of_contents: DocTemplateTableOfContents;
    public cover_page: DocTemplateCoverPage;
    public page_config?: DocTemplatePageConfig;
}

export interface DocTemplatePageConfigMargin {
    'margin-top': number;
    'margin-bottom': number;
    'margin-left': number;
    'margin-right': number;
}

export interface DocTemplatePageConfig {
    margin?: Partial<DocTemplatePageConfigMargin>;
}

export interface DocTemplateCoverPage {
    activated: boolean;
    content: string;
    config: Record<string, unknown>;
}

export interface DocTemplatePageSectionConfig {
    height: number;
}

export interface DocTemplatePageSection {
    activated: boolean;
    content: string;
    config: DocTemplatePageSectionConfig;
}

export type DocTemplateTocFontStyle = 'normal' | 'italic';
export type DocTemplateTocFontWeight = 'normal' | 'bold';

export interface DocTemplateTocBaseStyle {
    'font-size'?: number;
    'line-height'?: number;
    'margin-left'?: number;
    'margin-top'?: number;
    'margin-bottom'?: number;
    'padding-bottom'?: number;
    color?: string;
    'font-style'?: DocTemplateTocFontStyle;
    'font-weight'?: DocTemplateTocFontWeight;
}

export interface DocTemplateTableOfContentsConfig {
    pdftoc: Required<Pick<DocTemplateTocBaseStyle, 'line-height'>>;
    level0: DocTemplateTocBaseStyle;
    level1: DocTemplateTocBaseStyle;
    level2: DocTemplateTocBaseStyle;
    level3: DocTemplateTocBaseStyle;
    level4: DocTemplateTocBaseStyle;
    level5: DocTemplateTocBaseStyle;
}

export interface DocTemplateTableOfContents {
    activated: boolean;
    config: DocTemplateTableOfContentsConfig;
}

export interface DocTemplateUpdateResponse {
    body: DocTemplate;
    status: number;
    statusText: string;
    url: string;
    ok: boolean;
}
