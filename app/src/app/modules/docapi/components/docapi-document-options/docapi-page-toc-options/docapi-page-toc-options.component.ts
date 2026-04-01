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


import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

interface TocPreviewItem {
    level: number;
    title: string;
    page: number;
}

@Component({
    selector: 'cmdb-docapi-page-toc-options',
    templateUrl: './docapi-page-toc-options.component.html',
    styleUrls: ['./docapi-page-toc-options.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class DocapiPageTocOptionsComponent {
    @Input() public tocForm!: UntypedFormGroup;

    public selectedLevel = 0;
    public showAdvancedSpacing = false;

    public readonly levels = [0, 1, 2, 3, 4, 5];

    private static readonly LEVEL_DEFAULTS: Record<number, Record<string, string | number>> = {
        0: { 'font-size': 13.6, 'margin-left': 0, 'margin-top': 10, 'margin-bottom': 4, 'padding-bottom': 2, 'color': '#111827', 'font-style': 'normal', 'font-weight': 'bold' },
        1: { 'font-size': 12, 'margin-left': 10, 'margin-top': 6, 'margin-bottom': 2, 'padding-bottom': 1, 'color': '#111827', 'font-style': 'normal', 'font-weight': 'bold' },
        2: { 'font-size': 11, 'margin-left': 20, 'margin-top': 4, 'margin-bottom': 2, 'padding-bottom': 1, 'color': '#374151', 'font-style': 'normal', 'font-weight': 'normal' },
        3: { 'font-size': 10.5, 'margin-left': 30, 'margin-top': 3, 'margin-bottom': 1, 'padding-bottom': 1, 'color': '#374151', 'font-style': 'italic', 'font-weight': 'normal' },
        4: { 'font-size': 10, 'margin-left': 40, 'margin-top': 2, 'margin-bottom': 1, 'padding-bottom': 0, 'color': '#4b5563', 'font-style': 'italic', 'font-weight': 'normal' },
        5: { 'font-size': 9.5, 'margin-left': 50, 'margin-top': 2, 'margin-bottom': 1, 'padding-bottom': 0, 'color': '#6b7280', 'font-style': 'normal', 'font-weight': 'normal' },
    };

    private static readonly GENERAL_DEFAULTS = {
        pdftoc: { 'font-size': 12, 'line-height': 1.9 },
        spacing: { 'margin-top': 2 },
    };

    public readonly previewItems: TocPreviewItem[] = [
        { level: 0, title: 'H1 Introduction', page: 2 },
        { level: 1, title: 'H2 Scope', page: 3 },
        { level: 2, title: 'H3 Overview', page: 4 },
        { level: 3, title: 'H4 Details', page: 5 },
        { level: 4, title: 'H5 Notes', page: 6 },
        { level: 5, title: 'H6 Appendix', page: 7 },
    ];


    public get selectedLevelForm(): UntypedFormGroup | null {
        const group = this.tocForm?.get(`table_of_contents_config.level${this.selectedLevel}`);
        return group instanceof UntypedFormGroup ? group : null;
    }


    public get pdftocGroup(): UntypedFormGroup | null {
        const group = this.tocForm?.get('table_of_contents_config.pdftoc');
        return group instanceof UntypedFormGroup ? group : null;
    }


    public get spacingGroup(): UntypedFormGroup | null {
        const group = this.tocForm?.get('table_of_contents_config.spacing');
        return group instanceof UntypedFormGroup ? group : null;
    }


    public get indentValue(): number {
        return this.asNumber(this.selectedLevelForm?.get('margin-left')?.value, 0);
    }


    public get indentPercent(): number {
        return Math.min((this.indentValue / 60) * 100, 100);
    }


    public selectLevel(level: number): void {
        this.selectedLevel = level;
        this.showAdvancedSpacing = false;
    }


    public toggleAdvancedSpacing(): void {
        this.showAdvancedSpacing = !this.showAdvancedSpacing;
    }


    public toggleBold(): void {
        const control = this.selectedLevelForm?.get('font-weight');
        if (!control) return;
        control.setValue(control.value === 'bold' ? 'normal' : 'bold');
        control.markAsDirty();
    }


    public toggleItalic(): void {
        const control = this.selectedLevelForm?.get('font-style');
        if (!control) return;
        control.setValue(control.value === 'italic' ? 'normal' : 'italic');
        control.markAsDirty();
    }


    public stepValue(controlName: string, delta: number, group: UntypedFormGroup | null): void {
        if (!group) return;
        const control = group.get(controlName);
        if (!control) return;
        const current = this.asNumber(control.value, 0);
        const next = parseFloat((current + delta).toFixed(2));
        control.setValue(next);
        control.markAsDirty();
    }


    public stepLevelValue(controlName: string, delta: number): void {
        this.stepValue(controlName, delta, this.selectedLevelForm);
    }


    public onIndentChange(event: Event): void {
        const raw = parseFloat((event.target as HTMLInputElement).value);
        const value = Math.min(60, Math.max(0, raw));
        this.selectedLevelForm?.get('margin-left')?.setValue(value);
        this.selectedLevelForm?.get('margin-left')?.markAsDirty();
    }


    public getPreviewStyle(item: TocPreviewItem): Record<string, string> {
        const levelGroup = this.tocForm?.get(`table_of_contents_config.level${item.level}`);
        const spacing = this.asNumber(
            this.tocForm?.get('table_of_contents_config.spacing.margin-top')?.value, 0
        );

        return {
            'font-size': `${this.asNumber(levelGroup?.get('font-size')?.value, 10)}pt`,
            'margin-left': `${this.asNumber(levelGroup?.get('margin-left')?.value, 0)}pt`,
            'margin-top': `${this.asNumber(levelGroup?.get('margin-top')?.value, 0) + spacing}pt`,
            'margin-bottom': `${this.asNumber(levelGroup?.get('margin-bottom')?.value, 0)}pt`,
            'padding-bottom': `${this.asNumber(levelGroup?.get('padding-bottom')?.value, 0)}pt`,
            'line-height': `${this.asNumber(this.tocForm?.get('table_of_contents_config.pdftoc.line-height')?.value, 1.4)}`,
            'font-style': `${levelGroup?.get('font-style')?.value || 'normal'}`,
            'font-weight': `${levelGroup?.get('font-weight')?.value || 'normal'}`,
            'color': `${levelGroup?.get('color')?.value || '#000000'}`,
        };
    }


    public resetCurrentLevel(): void {
        const defaults = DocapiPageTocOptionsComponent.LEVEL_DEFAULTS[this.selectedLevel];
        if (!defaults || !this.selectedLevelForm) return;
        this.selectedLevelForm.patchValue(defaults);
        this.selectedLevelForm.markAsDirty();
    }


    public resetGeneralSettings(): void {
        const { pdftoc, spacing } = DocapiPageTocOptionsComponent.GENERAL_DEFAULTS;
        this.pdftocGroup?.patchValue(pdftoc);
        this.spacingGroup?.patchValue(spacing);
        this.pdftocGroup?.markAsDirty();
        this.spacingGroup?.markAsDirty();
    }


    private asNumber(value: unknown, fallback: number): number {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }
}
