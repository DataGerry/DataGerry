/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { FormArray, FormBuilder, FormControl, FormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { finalize, take } from 'rxjs/operators';

import { AiAssistantService } from '../../services/ai-assistant.service';
import { AiAssistantMessage } from '../../models/ai-suggestion.model';
import { TypeAssistantResponse } from '../../models/ai-assistant-response.model';

import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';

/** Minimal shapes for the AI-returned schema */
interface FieldMeta {
  type: string;
  name: string;
  label?: string;
  options?: Array<{ name: string; label: string }>;
  [key: string]: unknown;
}
interface SectionMeta {
  type: 'section' | string;
  name: string;
  label: string;
  fields?: string[];
  [key: string]: unknown;
}
interface AiGeneratedType {
  name: string;
  label?: string;
  version: string;
  description?: string | null;
  fields: FieldMeta[];
  render_meta: {
    icon?: string;
    sections: SectionMeta[];
    externals?: unknown[];
    summary?: { fields?: string[] };
  };
  ci_explorer_label?: string | null;
  [key: string]: unknown;
}

/** Row model for the table */
interface SectionRow {
  form: FormGroup;
  meta: SectionMeta;
}

@Component({
  selector: 'cmdb-ai-prompt-page',
  templateUrl: './ai-prompt-page.component.html',
  styleUrls: ['./ai-prompt-page.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AiPromptPageComponent implements OnInit, OnDestroy {

  promptForm = this.fb.group({
    prompt: this.fb.control<string>('', { nonNullable: true, validators: [Validators.required] })
  });

  selectionForm = this.fb.group({
    sections: this.fb.array<FormGroup>([])
  });

  sectionRows: SectionRow[] = [];

  /** UI state */
  loading = false;
  hasSchema = false;
  validationMessage = '';
  public isLoading$ = this.loaderService.isLoading$;

  /** Caches */
  private fieldByName = new Map<string, FieldMeta>();
  private schema: AiGeneratedType | null = null;

  /** subscription to keep guard counts fresh (optional) */
  private valueSub?: Subscription;


  constructor(
    private fb: FormBuilder,
    private ai: AiAssistantService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
    private router: Router,
    private typeService: TypeService,
    private sidebarService: SidebarService,
    private loaderService: LoaderService
  ) {}

  ngOnInit(): void {}
  ngOnDestroy(): void { this.valueSub?.unsubscribe(); }

  /** Convenience getter */
  get sectionsFA(): FormArray<FormGroup> {
    return this.selectionForm.get('sections') as FormArray<FormGroup>;
  }

  /** Template helpers */
  fieldChecksOf(row: SectionRow) {
    return row.form.get('fieldChecks') as FormArray<FormControl<boolean>>;
  }
  trackByIndex = (i: number) => i;

  fieldLabel = (fieldName: string): string => this.fieldByName.get(fieldName)?.label ?? fieldName;
  fieldKind  = (fieldName: string): string => this.fieldByName.get(fieldName)?.type  ?? '';

  /** Prompt -> Schema */
  requestSchema(): void {
    if (this.promptForm.invalid) return;

    this.loaderService.show();
    this.loading = true;
    this.validationMessage = '';
    this.hasSchema = false;
    this.cdr.markForCheck();

    const message: AiAssistantMessage = { message: this.promptForm.value.prompt! };

    this.ai.postMessage(message).pipe(take(1), finalize(() => { this.loaderService.hide()})).subscribe({
      next: (resp: TypeAssistantResponse<AiGeneratedType>) => {
        if (!resp?.is_valid_type) {
          this.loading = false;
          this.validationMessage = resp?.message;
          this.toast.warning(this.validationMessage);
          this.cdr.markForCheck();
          return;
        }
        this.schema = resp.data;
        this.buildSelectionFrom(this.schema);
        this.hasSchema = true;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: (err: any) => {
        this.loading = false;
        this.toast.error(err.error?.message);
        this.cdr.markForCheck();
      }
    });
  }

  /** Build selection form + rows */
  private buildSelectionFrom(schema: AiGeneratedType): void {
    // reset form array with a new instance
    this.selectionForm.setControl('sections', this.fb.array<FormGroup>([]));
    const sectionsFA = this.sectionsFA;

    // cache fields
    this.fieldByName = new Map<string, FieldMeta>((schema.fields ?? []).map(f => [f.name, f]));

    // only normal sections (ignore multi-data)
    const sections = (schema.render_meta?.sections ?? [])
      .filter(s => s?.type === 'section')
      .map<SectionMeta>(s => ({ ...s, fields: (s.fields ?? []).slice() }))
      .filter(s => (s.fields?.length ?? 0) > 0);

    if (!sections.length) {
      this.validationMessage = 'No sections with fields were returned.';
      this.toast.warning(this.validationMessage);
      this.sectionRows = [];
      return;
    }

    const rows: SectionRow[] = sections.map(sec => {
      const fieldChecksFA = this.fb.array<FormControl<boolean>>(
        (sec.fields ?? []).map(() => this.fb.control<boolean>(true))
      );
      const form = this.fb.group({
        includeSection: this.fb.control<boolean>(true),
        fieldChecks:    fieldChecksFA,
        meta:           this.fb.control<SectionMeta>(sec)
      });
      sectionsFA.push(form);
      return { form, meta: sec };
    });

    this.sectionRows = rows;

    // optional: keep guards reactive
    this.valueSub?.unsubscribe();
    this.valueSub = this.selectionForm.valueChanges.subscribe(() => this.cdr.markForCheck());
  }

  /** Disable helpers as arrow props so they're always available to template */
  isSectionDisabled = (rowIndex: number): boolean => {
    const row = this.sectionRows[rowIndex];
    if (!row) return false;
    if (!row.form.value.includeSection) return false;   // already unchecked
    const selectedCount = this.sectionRows.reduce((acc, r) => acc + (r.form.value.includeSection ? 1 : 0), 0);
    return selectedCount <= 1; // prevent unchecking the last selected section
  };

  isFieldDisabled = (rowIndex: number, fieldIndex: number): boolean => {
    const row = this.sectionRows[rowIndex];
    if (!row) return true;
    if (!row.form.value.includeSection) return true;

    const current = (row.form.value.fieldChecks as boolean[])[fieldIndex];
    if (!current) return false;

    const totalSelectedFields = this.sectionRows.reduce((acc, r) => {
      if (!r.form.value.includeSection) return acc;
      const checks: boolean[] = r.form.value.fieldChecks;
      return acc + checks.filter(Boolean).length;
    }, 0);

    return totalSelectedFields <= 1; // prevent unchecking the very last field globally
  };


  /** Prune the AI schema to only selected sections/fields */
  private buildCreatePayload(): any {
    if (!this.schema) throw new Error('Schema not loaded');
    const draft: AiGeneratedType = JSON.parse(JSON.stringify(this.schema));

    const keptSections: SectionMeta[] = [];
    const keptFieldNames = new Set<string>();

    for (const row of this.sectionRows) {
      if (!row.form.value.includeSection) continue;

      const checks: boolean[] = row.form.value.fieldChecks;
      const originalNames = row.meta.fields ?? [];
      const filteredNames = originalNames.filter((_, i) => !!checks[i]);

      if (!filteredNames.length) continue;

      keptSections.push({ ...row.meta, fields: filteredNames });
      filteredNames.forEach(n => keptFieldNames.add(n));
    }

    draft.render_meta.sections = keptSections;
    draft.fields = (draft.fields ?? []).filter(f => keptFieldNames.has(f.name));

    if (draft.render_meta?.summary?.fields?.length) {
      draft.render_meta.summary.fields = draft.render_meta.summary.fields.filter(n => keptFieldNames.has(n));
    }
    if (draft.ci_explorer_label && !keptFieldNames.has(draft.ci_explorer_label)) {
      draft.ci_explorer_label = null;
    }
    return draft;
  }


  /** Submit - create Type */
  submitSelection(): void {
    if (!this.hasSchema) return;

    // basic guard
    const atLeastOneSection = this.sectionRows.some(r => r.form.value.includeSection);
    const atLeastOneField = this.sectionRows.some(r =>
      r.form.value.includeSection && (r.form.value.fieldChecks as boolean[]).some(Boolean)
    );
    if (!atLeastOneSection || !atLeastOneField) {
      this.toast.warning('Select at least one section and one field.');
      return;
    }

    const saveTypeInstance = this.buildCreatePayload();
    let newTypeID = 0;

    this.loaderService.show();
    this.typeService.postType(saveTypeInstance)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (typeResp: CmdbType) => {
          newTypeID = +typeResp?.public_id;
          this.router.navigate(['/framework/type/'], { queryParams: { typeAddSuccess: newTypeID } });
          this.sidebarService.loadCategoryTree();
          this.toast.success(`Type was successfully created: TypeID: ${newTypeID}`);
        },
        error: (e) => {
          this.toast.error(e?.error?.message || 'Could not create type.');
        }
      });
  }
}
