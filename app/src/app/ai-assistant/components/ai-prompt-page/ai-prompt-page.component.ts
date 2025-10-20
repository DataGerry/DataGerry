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
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit
} from '@angular/core';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  UntypedFormControl,
  UntypedFormGroup,
  Validators
} from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { CdkDragDrop, moveItemInArray, transferArrayItem } from '@angular/cdk/drag-drop';

import { AiAssistantService } from '../../services/ai-assistant.service';
import { AiAssistantMessage } from '../../models/ai-suggestion.model';
import { TypeAssistantResponse } from '../../models/ai-assistant-response.model';
import {
  SpeechRecognitionService,
  SpeechRecognitionResult,
  SpeechRecognitionError
} from '../../services/speech-recognition.service';

import { checkTypeExistsValidator, TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { alphanumericValidator } from 'src/app/framework/type/type-builder/type-basic-step/alphanumeric-validator';

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
export interface SectionRow {
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
  public form: UntypedFormGroup;

  promptForm = this.fb.group({
    prompt: this.fb.control<string>('', { nonNullable: true, validators: [Validators.required] })
  });

  selectionForm = this.fb.group({
    sections: this.fb.array<FormGroup>([])
  });

  /** dynamic rows the table renders */
  sectionRows: SectionRow[] = [];

  /** UI state */
  loading = false;
  hasSchema = false;
  validationMessage = '';
  public isLoading$ = this.loaderService.isLoading$;

  /** caches / schema */
  private fieldByName = new Map<string, FieldMeta>();
  private schema: AiGeneratedType | null = null;

  private valueSub?: Subscription;

  /** Voice */
  isRecording = false;
  speechStatus: 'idle' | 'recording' | 'processing' | 'error' = 'idle';
  speechError = '';

  /** Summary + CI Explorer */
  summarySelected = new Set<string>();
  ciExplorerLabel: string | null = null;

  constructor(
    private fb: FormBuilder,
    private ai: AiAssistantService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
    private router: Router,
    private typeService: TypeService,
    private sidebarService: SidebarService,
    private loaderService: LoaderService,
    private speechRecognition: SpeechRecognitionService
  ) {
    this.form = new UntypedFormGroup({
      name: new UntypedFormControl('', [Validators.required, alphanumericValidator()])
    });
  }

  ngOnInit(): void {
    this.setupSpeechRecognition();
  }

  ngOnDestroy(): void {
    this.valueSub?.unsubscribe();
    this.speechRecognition.stopListening();
  }

  /** convenience */
  get sectionsFA(): FormArray<FormGroup> {
    return this.selectionForm.get('sections') as FormArray<FormGroup>;
  }

  trackByIndex = (i: number) => i;

  fieldLabel = (fieldName: string): string => this.fieldByName.get(fieldName)?.label ?? fieldName;
  fieldKind  = (fieldName: string): string => this.fieldByName.get(fieldName)?.type  ?? '';

  /** totals for guards */
  totalSelectedFields(): number {
    return this.sectionRows.reduce((acc, r) => {
      if (!r.form.value.includeSection) return acc;
      const checks: boolean[] = r.form.value.fieldChecks;
      return acc + checks.filter(Boolean).length;
    }, 0);
  }

  /** =========================
   *  Prompt -> Schema
   *  ========================= */
  requestSchema(): void {
    if (this.promptForm.invalid) return;

    this.loaderService.show();
    this.loading = true;
    this.validationMessage = '';
    this.hasSchema = false;
    this.cdr.markForCheck();

    const message: AiAssistantMessage = { message: this.promptForm.value.prompt! };

    this.ai.postMessage(message)
      .pipe(take(1), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (resp: TypeAssistantResponse<AiGeneratedType>) => {
          if (!resp?.is_valid_type) {
            this.validationMessage = resp?.error || 'The AI did not return a valid type schema.';
            this.loading = false;
            this.toast.warning(this.validationMessage);
            this.cdr.markForCheck();
            return;
          }

          this.schema = resp.data;
          this.buildSelectionFrom(this.schema);

          // Prefill type name + async validator
          this.form.patchValue({ name: this.schema.name });
          this.form.markAllAsTouched();
          this.form.get('name')!.setAsyncValidators(checkTypeExistsValidator(this.typeService));

          // Prefill summary + ci explorer label
          this.summarySelected = new Set<string>(this.schema.render_meta?.summary?.fields ?? []);
          this.ciExplorerLabel = this.schema.ci_explorer_label ?? null;

          this.hasSchema = true;
          this.loading = false;
          this.cdr.markForCheck();
        },
        error: (err) => {
          this.loading = false;
          this.toast.error(err?.error?.message || 'Failed to get AI schema.');
          this.cdr.markForCheck();
        }
      });
  }

  /** =========================
   *  Build Selection Form
   *  ========================= */
  private buildSelectionFrom(schema: AiGeneratedType): void {
    // reset
    this.selectionForm.setControl('sections', this.fb.array<FormGroup>([]));
    const sectionsFA = this.sectionsFA;

    // cache fields
    this.fieldByName = new Map<string, FieldMeta>((schema.fields ?? []).map(f => [f.name, f]));

    // sections that actually have fields
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

    // Build FormGroup per section
    const rows: SectionRow[] = sections.map(sec => {
      const fieldChecksFA = this.fb.array<FormControl<boolean>>(
        (sec.fields ?? []).map(() => this.fb.control<boolean>(true))
      );
      const fieldLabelsFA = this.fb.array<FormControl<string>>(
        (sec.fields ?? []).map((fname) =>
          this.fb.control<string>(this.fieldLabel(fname), {
            nonNullable: true,
            validators: [Validators.required, Validators.maxLength(120)]
          })
        )
      );

      const form = this.fb.group({
        includeSection: this.fb.control<boolean>(true),
        fieldChecks:    fieldChecksFA,
        fieldLabels:    fieldLabelsFA,
        sectionLabel:   this.fb.control<string>(sec.label || sec.name, {
                           nonNullable: true,
                           validators: [Validators.required, Validators.maxLength(120)]
                         }),
        meta:           this.fb.control<SectionMeta>(sec),
        filter:         this.fb.control<string>('') // local filter box
      });

      sectionsFA.push(form);
      return { form, meta: sec };
    });

    this.sectionRows = rows;

    // live change marks
    this.valueSub?.unsubscribe();
    this.valueSub = this.selectionForm.valueChanges.subscribe(() => this.cdr.markForCheck());
  }

  /** =========================
   *  Guards used by rows
   *  ========================= */
  isSectionDisabled = (rowIndex: number): boolean => {
    const row = this.sectionRows[rowIndex];
    if (!row) return false;
    if (!row.form.value.includeSection) return false;
    const selectedCount = this.sectionRows.reduce((acc, r) => acc + (r.form.value.includeSection ? 1 : 0), 0);
    return selectedCount <= 1; // prevent unchecking the last selected section
  };

  isFieldDisabled = (_rowIndex: number, _fieldIndex: number): boolean => {
    return this.totalSelectedFields() <= 1; // prevent unchecking the very last field globally
  };

  /** =========================
   *  DnD handlers (sections & fields)
   *  ========================= */
  dropSection(event: CdkDragDrop<SectionRow[]>) {
    if (event.previousIndex === event.currentIndex) return;
    moveItemInArray(this.sectionRows, event.previousIndex, event.currentIndex);

    // Also reorder form array to keep indexes aligned
    const fa = this.sectionsFA;
    const ctrl = fa.at(event.previousIndex);
    fa.removeAt(event.previousIndex);
    fa.insert(event.currentIndex, ctrl);
    this.cdr.markForCheck();
  }

  dropField(rowIndex: number, event: CdkDragDrop<string[]>) {
    const row = this.sectionRows[rowIndex];
    if (!row) return;

    // Reorder in meta.fields
    moveItemInArray(row.meta.fields!, event.previousIndex, event.currentIndex);

    // Reorder fieldChecks + fieldLabels in the FormArray
    const checksFA = row.form.get('fieldChecks') as FormArray<FormControl<boolean>>;
    const labelsFA = row.form.get('fieldLabels') as FormArray<FormControl<string>>;
    const cCtrl = checksFA.at(event.previousIndex);
    const lCtrl = labelsFA.at(event.previousIndex);
    checksFA.removeAt(event.previousIndex);
    labelsFA.removeAt(event.previousIndex);
    checksFA.insert(event.currentIndex, cCtrl);
    labelsFA.insert(event.currentIndex, lCtrl);

    this.cdr.markForCheck();
  }

  /** =========================
   *  Summary & CI Explorer picks
   *  ========================= */
  toggleSummaryField(fieldName: string, checked: boolean) {
    if (checked) this.summarySelected.add(fieldName);
    else this.summarySelected.delete(fieldName);
  }

  setCiExplorerLabel(fieldName: string) {
    this.ciExplorerLabel = fieldName;
  }

  /** =========================
   *  Helpers wired to child
   *  ========================= */
  onSelectAll(rowIndex: number, select: boolean) {
    const row = this.sectionRows[rowIndex];
    if (!row) return;
    const checksFA = row.form.get('fieldChecks') as FormArray<FormControl<boolean>>;
    checksFA.controls.forEach((c) => c.setValue(select, { emitEvent: false }));
    // guard: never let global selected drop to 0
    if (this.totalSelectedFields() === 0) {
      checksFA.at(0).setValue(true, { emitEvent: false });
    }
    this.cdr.markForCheck();
  }

  /** =========================
   *  Build payload with edits
   *  ========================= */
  private buildCreatePayload(): any {
    if (!this.schema) throw new Error('Schema not loaded');
    const draft: AiGeneratedType = JSON.parse(JSON.stringify(this.schema));

    const keptSections: SectionMeta[] = [];
    const keptFieldNames = new Set<string>();

    // 1) sections in CURRENT order, with updated label + filtered field arrays (also in CURRENT order)
    for (const row of this.sectionRows) {
      if (!row.form.value.includeSection) continue;

      const checks: boolean[] = row.form.value.fieldChecks;
      const labels: string[]  = row.form.value.fieldLabels;
      const originalNames = row.meta.fields ?? [];

      // keep fields that are checked, preserving current order
      const keptNames = originalNames.filter((_, i) => !!checks[i]);
      if (!keptNames.length) continue;

      // apply updated field labels back into draft.fields
      keptNames.forEach((fname) => {
        const idx = originalNames.indexOf(fname);
        const newLabel = labels[idx];
        const target = draft.fields.find(f => f.name === fname);
        if (target && newLabel && target.label !== newLabel) target.label = newLabel;
      });

      // push section with updated label + kept fields
      const newSectionLabel = row.form.value.sectionLabel?.trim() || row.meta.label || row.meta.name;
      keptSections.push({ ...row.meta, label: newSectionLabel, fields: keptNames });

      keptNames.forEach(n => keptFieldNames.add(n));
    }

    // 2) filter draft.fields to only kept
    draft.fields = (draft.fields ?? []).filter(f => keptFieldNames.has(f.name));

    // 3) keep sections (and their new order)
    draft.render_meta.sections = keptSections;

    // 4) type name from form
    draft.name = this.form.value.name!;

    // 5) summary selection — keep only kept fields
    const summaryKept = Array.from(this.summarySelected).filter(n => keptFieldNames.has(n));
    draft.render_meta.summary = { fields: summaryKept };

    // 6) CI explorer label — clear if not kept
    draft.ci_explorer_label = (this.ciExplorerLabel && keptFieldNames.has(this.ciExplorerLabel))
      ? this.ciExplorerLabel
      : null;

    return draft;
  }

  /** =========================
   *  Submit
   *  ========================= */
  submitSelection(): void {
    if (!this.hasSchema) return;

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

  get name() { return this.form.get('name'); }

  goBack() {
    this.schema = null;
    this.hasSchema = false;
    this.sectionRows = [];
    this.promptForm.reset();
    this.selectionForm.reset();
    this.summarySelected.clear();
    this.ciExplorerLabel = null;
    this.validationMessage = '';
    this.cdr.markForCheck();
  }

  /** =========================
   *  Speech recognition
   *  ========================= */
  private setupSpeechRecognition(): void {
    this.speechRecognition.getTranscript().subscribe((result: SpeechRecognitionResult) => {
      if (result.isFinal) {
        const currentPrompt = this.promptForm.value.prompt || '';
        const newPrompt = currentPrompt + (currentPrompt ? ' ' : '') + result.transcript;
        this.promptForm.patchValue({ prompt: newPrompt });
        this.speechStatus = 'idle';
      } else {
        this.speechStatus = 'processing';
      }
      this.cdr.markForCheck();
    });

    this.speechRecognition.getStatus().subscribe((status: string) => {
      this.speechStatus = status as any;
      this.isRecording = status === 'recording';
      this.cdr.markForCheck();
    });

    this.speechRecognition.getErrors().subscribe((error: SpeechRecognitionError) => {
      this.speechStatus = 'error';
      this.speechError = error.message;
      this.toast.error(this.speechError);
      this.cdr.markForCheck();
    });
  }

  toggleSpeechRecognition(): void {
    if (this.isRecording) this.stopSpeechRecognition();
    else this.startSpeechRecognition();
  }
  startSpeechRecognition(): void { this.speechError = ''; this.speechRecognition.startListening(); }
  stopSpeechRecognition(): void { this.speechRecognition.stopListening(); }

  getSpeechButtonIcon(): string {
    switch (this.speechStatus) {
      case 'recording': return 'microphone-slash';
      case 'processing': return 'circle-notch';
      case 'error': return 'exclamation-triangle';
      default: return 'microphone';
    }
  }
  getSpeechButtonClass(): string {
    switch (this.speechStatus) {
      case 'recording': return 'btn-danger recording-pulse';
      case 'processing': return 'btn-warning';
      case 'error': return 'btn-danger';
      default: return 'btn-outline-secondary';
    }
  }
  getSpeechButtonTooltip(): string {
    switch (this.speechStatus) {
      case 'recording': return 'Stop recording';
      case 'processing': return 'Processing speech...';
      case 'error': return 'Speech recognition error';
      default: return 'Start voice input';
    }
  }
  isSpeechSupported(): boolean {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    return !!SR;
  }
}
