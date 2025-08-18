import { Component, OnInit } from '@angular/core';
import { FormArray, FormBuilder, FormControl, FormGroup, Validators } from '@angular/forms';
import { AiAssistantService } from '../../services/ai-assistant.service';
import { AiAssistantMessage } from '../../models/ai-suggestion.model';
import { TypeAssistantResponse } from '../../models/ai-assistant-response.model';
import { TypeSelectionPayload, SectionSelection } from '../../models/ai-type-selection.models';
import { ToastService } from 'src/app/layout/toast/toast.service';

// Reuse your CmdbType shape (same as AI "formatted_data")
type CmdbTypeLike = any;
type SectionMeta  = any;
type FieldMeta    = any;

@Component({
  selector: 'cmdb-ai-prompt-page',
  templateUrl: './ai-prompt-page.component.html',
  standalone: false,
})
export class AiPromptPageComponent implements OnInit {

  promptForm = this.fb.group({
    prompt: this.fb.control('', { nonNullable: true, validators: [Validators.required] })
  });

  selectionForm = this.fb.group({
    sections: this.fb.array<FormGroup>([])
  });
  get sectionsFA(): FormArray<FormGroup> { return this.selectionForm.get('sections') as FormArray<FormGroup>; }

  loading = false;
  hasSchema = false;
  validationMessage = '';

  // cache
  private fieldByName = new Map<string, FieldMeta>();
  private schema: CmdbTypeLike | null = null;

  constructor(
    private fb: FormBuilder,
    private ai: AiAssistantService,
    private toast: ToastService
  ) {}

  ngOnInit(): void {}

  requestSchema(): void {
    if (this.promptForm.invalid) return;

    this.loading = true;
    this.validationMessage = '';
    this.hasSchema = false;

    const msg: AiAssistantMessage = { message: this.promptForm.value.prompt! };

    this.ai.postMessage(msg).subscribe({
      next: (resp: TypeAssistantResponse<CmdbTypeLike>) => {
        if (!resp?.is_valid_type) {
          this.loading = false;
          this.validationMessage = resp?.message || 'The generated type is not valid. Please refine your prompt.';
          this.toast.warning(this.validationMessage);
          return;
        }

        this.schema = resp.data;
        this.buildSelectionFrom(this.schema);
        this.hasSchema = true;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.toast.error('Failed to get schema from AI.');
      }
    });
  }

  // ── Build selection UI  ─────────
  private buildSelectionFrom(schema: CmdbTypeLike): void {
    // reset
    while (this.sectionsFA.length) this.sectionsFA.removeAt(0);
    this.fieldByName.clear();

    const fields: FieldMeta[] = schema?.fields ?? [];
    for (const f of fields) this.fieldByName.set(f.name, f);

    const sections: SectionMeta[] = schema?.render_meta?.sections ?? [];

    // Only render classic sections 
    const classicSections = sections
      .filter(s => s?.type === 'section')
      .map(s => ({ ...s, fields: (s.fields ?? []).slice() }))
      .filter(s => (s.fields?.length ?? 0) > 0);

    if (!classicSections.length) {
      this.validationMessage = 'No sections with fields were returned.';
      this.toast.warning(this.validationMessage);
      return;
    }

    for (const sec of classicSections) {
      const fieldChecksFA = this.fb.array<FormControl<boolean>>(
        (sec.fields ?? []).map(() => this.fb.control<boolean>(true))
      );
      this.sectionsFA.push(
        this.fb.group({
          includeSection: this.fb.control<boolean>(true),
          fieldChecks:    fieldChecksFA,
          meta:           this.fb.control<SectionMeta>(sec)
        })
      );
    }
  }

  // ── Labels/Types for display ───────────────────────────────────
  fieldLabel(fieldName: string): string {
    return this.fieldByName.get(fieldName)?.label ?? fieldName;
  }
  fieldKind(fieldName: string): string {
    return this.fieldByName.get(fieldName)?.type ?? '';
  }

  // ── Guards: keep ≥1 section & ≥1 field ────────────────────────
  private selectedSectionCount(): number {
    return this.sectionsFA.controls.reduce((acc, g) => acc + (g.value.includeSection ? 1 : 0), 0);
  }
  private selectedFieldCount(): number {
    return this.sectionsFA.controls.reduce((acc, g) => {
      if (!g.value.includeSection) return acc;
      const checks: boolean[] = g.value.fieldChecks;
      return acc + checks.filter(Boolean).length;
    }, 0);
  }
  disableSectionUncheck(index: number): boolean {
    const g = this.sectionsFA.at(index);
    if (!g.value.includeSection) return false;
    return this.selectedSectionCount() <= 1;
  }
  disableFieldUncheck(sIdx: number, fIdx: number): boolean {
    const g = this.sectionsFA.at(sIdx);
    if (!g.value.includeSection) return true;
    const current = (g.value.fieldChecks as boolean[])[fIdx];
    if (!current) return false;
    return this.selectedFieldCount() <= 1;
  }

  // ── Submit selection (optional) ────────────────────────────────
  submitSelection(): void {
    if (!this.hasSchema) return;

    if (this.selectedSectionCount() < 1 || this.selectedFieldCount() < 1) {
      this.toast.warning('Select at least one section and one field.');
      return;
    }

    const sections: SectionSelection[] = this.sectionsFA.controls
      .filter(g => g.value.includeSection)
      .map(g => {
        const meta = g.value.meta as SectionMeta;
        const kept = (meta.fields ?? []).filter((_, i) => (g.value.fieldChecks as boolean[])[i]);
        return { sectionName: meta.name, includeSection: true, includedFieldNames: kept };
      });

    const payload: TypeSelectionPayload = { sections };

    // If you have a backend step for this, use it; otherwise emit/console.
    this.ai.submitSelection(payload).subscribe({
      next: () => this.toast.success('Selection submitted.'),
      error: () => this.toast.error('Could not submit selection.')
    });
  }

  fieldChecks(section: FormGroup): FormArray<FormControl<boolean>> {
    return section.get('fieldChecks') as FormArray<FormControl<boolean>>;
  }
}
