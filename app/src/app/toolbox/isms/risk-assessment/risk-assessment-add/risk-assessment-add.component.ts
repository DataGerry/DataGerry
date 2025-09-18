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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
  Component,
  inject,
  Input,
  OnInit,
  ViewChild
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  FormArray,
  FormBuilder,
  FormGroup,
  Validators
} from '@angular/forms';
import { BehaviorSubject, forkJoin, Observable, of } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

import { RiskAssessmentService } from '../../services/risk-assessment.service';
import { RiskAssessment } from '../../models/risk-assessment.model';

// reference-data services
import { RiskService } from 'src/app/toolbox/isms/services/risk.service';
import { ImpactCategoryService } from 'src/app/toolbox/isms/services/impact-category.service';
import { ImpactService } from 'src/app/toolbox/isms/services/impact.service';
import { LikelihoodService } from 'src/app/toolbox/isms/services/likelihood.service';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';

import { ObjectService } from 'src/app/framework/services/object.service';
import { ObjectGroupService } from 'src/app/framework/services/object-group.service';
import { PersonService } from '../../services/person.service';
import { PersonGroupService } from '../../services/person-group.service';

import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { SortDirection } from 'src/app/layout/table/table.types';
import { RiskMatrixService } from '../../services/risk-matrix.service';
import { RiskClassService } from '../../services/risk-class.service';
import { RiskClass } from '../../models/risk-class.model';
import { Location } from '@angular/common';
import { ControlMeasureService } from '../../services/control-measure.service';
import { RiskAssessmentTreatmentComponent } from '../risk-assessment-treatment/risk-assessment-treatment.component';
import { ControlMeasureAssignmentService } from '../../services/control‑measure‑assignment.service';
import { IsmsValidationService } from '../../services/isms-validation.service';

/* ------------------------------------------------------------------------------------ */
/*  Small enum for string literals                                                      */
/* ------------------------------------------------------------------------------------ */
export enum IdRefType {
  OBJECT = 'OBJECT',
  OBJECT_GROUP = 'OBJECT_GROUP',
  PERSON = 'PERSON'
}

type Expanded = Record<'top' | 'before' | 'treatment' | 'after' | 'audit', boolean>;

@Component({
  selector: 'app-risk-assessment-add',
  templateUrl: './risk-assessment-add.component.html',
  styleUrls: ['./risk-assessment-add.component.scss'],
})
export class RiskAssessmentAddComponent implements OnInit {

  @ViewChild('treatmentBlock')
  private treatmentBlock!: RiskAssessmentTreatmentComponent;


  /* ──────────────────────────────────────────────────────────────────────────
   *  Dependencies – initialise FIRST so later properties may read them
   * ────────────────────────────────────────────────────────────────────────── */
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly toast = inject(ToastService);
  private readonly loader = inject(LoaderService);

  private readonly riskAssessmentSrv = inject(RiskAssessmentService);
  private readonly riskSrv = inject(RiskService);
  private readonly objectSrv = inject(ObjectService);
  private readonly objectGroupSrv = inject(ObjectGroupService);
  private readonly personSrv = inject(PersonService);
  private readonly personGroupSrv = inject(PersonGroupService);
  private readonly impactCategorySrv = inject(ImpactCategoryService);
  private readonly impactSrv = inject(ImpactService);
  private readonly likelihoodSrv = inject(LikelihoodService);
  private readonly extendableOptionSrv = inject(ExtendableOptionService);
  private readonly riskMatrixSrv = inject(RiskMatrixService);
  private readonly riskClassSrv = inject(RiskClassService);
  private readonly controlMeasureSrv = inject(ControlMeasureService);
  private readonly cmaSrv = inject(ControlMeasureAssignmentService);
  private readonly ismsValidationService = inject(IsmsValidationService);

  public loading = false;
  public configurationIsValid: boolean = true;
  private initialized = false;


  /* ──────────────────────────────────────────────────────────────────────────
   *  Flags derived from route
   * ────────────────────────────────────────────────────────────────────────── */
  readonly fromRisk = this.route.snapshot.paramMap.has('riskId');
  readonly fromObject = this.route.snapshot.paramMap.has('objectId');
  readonly fromObjectGroup = this.route.snapshot.paramMap.has('groupId');
  readonly fromReport = !!this.router.getCurrentNavigation()?.extras?.state?.['fromReport'];

  // Added flags for view, edit, and duplicate modes
  readonly isEditMode = this.router.url.includes('/edit/');
  readonly isView = this.router.url.includes('/view/');
  readonly riskAssessmentId = (this.isEditMode || this.isView) ? Number(this.route.snapshot.paramMap.get('id')) : undefined;

  /* ──────────────────────────────────────────────────────────────────────────
   *  Reactive form
   * ────────────────────────────────────────────────────────────────────────── */
  readonly form: FormGroup = this.buildForm(this.fb);

  /* ──────────────────────────────────────────────────────────────────────────
   *  Collections (kept loosely typed until proper interfaces are exported)
   * ────────────────────────────────────────────────────────────────────────── */
  allRisks: any[] = [];
  allObjects: any[] = [];
  allObjectGroups: any[] = [];
  allPersons: any[] = [];
  allPersonGroups: any[] = [];
  impactCategories: any[] = [];
  impacts: any[] = [];
  likelihoods: any[] = [];
  implementationStates: any[] = [];
  riskMatrix: any;
  riskClasses: RiskClass[] = [];
  allControlMeasures: { public_id: number; title: string }[] = [];


  @Input() objectSummary: string | null = null;
  @Input() riskName: string | null = null;


  /* ──────────────────────────────────────────────────────────────────────────
   *  UI helpers
   * ────────────────────────────────────────────────────────────────────────── */
  readonly expandedSections: Expanded = {
    top: true, before: false, treatment: false, after: false, audit: false
  };
  readonly loading$ = new BehaviorSubject<boolean>(false);

  /* ══════════════════════════════════════════════════════════════════════════
   *  Lifecycle
   * ═════════════════════════════════════════════════════════════════════════ */

  constructor(private location: Location) { }

  ngOnInit(): void {
    if (this.initialized) return;
    this.initialized = true;
    this.ismsValidationService.checkConfigSilently().subscribe({
      next: (isValid) => {
        this.configurationIsValid = isValid;
        if (!isValid) return;
        this.applyRouteDefaults();
        this.loadReferenceData();
        const navigation = this.router.getCurrentNavigation();
        const state = navigation?.extras?.state as { objectSummary?: string, riskName?: string };
        this.objectSummary = state?.objectSummary || null;
        this.riskName = state?.riskName || null;
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
      }
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
   *  Public UI actions
   * ══════════════════════════════════════════════════════════════════════════ */

  /*
  * Toggles the visibility of a section.
  * @returns {void}
  */
  toggleSection(section: keyof Expanded): void {
    this.expandedSections[section] = !this.expandedSections[section];
  }

  /*
  * Handles the save action.
  * @returns {void}
  */
  onSave(): void {

    // Prevent saving in view mode
    if (this.isView) return;
  
    const payload = this.form.getRawValue() as RiskAssessment;
    delete payload.naming; // Remove naming object from payload
  
    if (this.isEditMode && this.riskAssessmentId) {
      // EDIT MODE → use diff
      payload.control_measure_assignments =
        this.treatmentBlock.buildAssignmentsPayload();
  
      this
        .doWithLoader(this.riskAssessmentSrv.updateRiskAssessment(this.riskAssessmentId, payload))
        .subscribe({
          next: () => {
            this.toast.success('Risk Assessment updated!');
            this.location.back();
          },
          error: this.handleError('Update error')
        });
  
    } else {
      // CREATE MODE → use raw form-array value (list of objects)
      payload.control_measure_assignments =
        this.form.get('control_measure_assignments')?.value ?? [];
  
      // Clean up extra fields
      delete payload.public_id;
      delete payload.risk_calculation_before.risk_level_value;
      delete payload.risk_calculation_after.risk_level_value;
      const parsedCost = parseFloat(String(payload.costs_for_implementation));
      payload.costs_for_implementation = parsedCost;
  
      this
        .doWithLoader(this.riskAssessmentSrv.createRiskAssessment(payload))
        .subscribe({
          next: () => {
            this.toast.success('Risk Assessment created!');
            this.location.back();
          },
          error: this.handleError('Creation error')
        });
    }
  }
  

  /*
  * Handles the cancel action.
  * @returns {void}
  */
  onCancel(): void {
    this.location.back();
  }

  /* ══════════════════════════════════════════════════════════════════════════
   *  Helpers
   * ══════════════════════════════════════════════════════════════════════════ */

  /*
  * Builds the form structure.
  * @returns {FormGroup}
  */
  private buildForm(fb: FormBuilder): FormGroup {
    const riskCalcGroup = () => fb.group({
      impacts: fb.array([]),
      likelihood_id: [null],
      likelihood_value: 0,
      maximum_impact_id: [null],
      maximum_impact_value: 0,
      risk_level_value: 0
    });

    return fb.group({
      public_id: null,
      /* ── TOP ── */
      risk_id: [null, Validators.required],
      object_id_ref_type: [IdRefType.OBJECT, Validators.required],
      object_id: [null, Validators.required],

      /* ── BEFORE ── */
      risk_calculation_before: riskCalcGroup(),
      risk_assessor_id: null,
      risk_owner_id_ref_type: [null, Validators.required],
      risk_owner_id: null,
      interviewed_persons: [[]],
      risk_assessment_date: [null, Validators.required],
      additional_info: '',

      /* ── TREATMENT ── */
      risk_treatment_option: null,
      responsible_persons_id_ref_type: [IdRefType.PERSON],
      responsible_persons_id: null,
      risk_treatment_description: '',
      planned_implementation_date: null,
      implementation_status: [null],
      finished_implementation_date: null,
      required_resources: '',
      costs_for_implementation: 0,
      costs_for_implementation_currency: '',
      priority: [null],
      control_measure_assignments: fb.array([]),
      selected_cm_assignment_ids: [],

      /* ── AFTER ── */
      risk_calculation_after: riskCalcGroup(),

      /* ── AUDIT ── */
      audit_done_date: null,
      auditor_id_ref_type: [IdRefType.PERSON],
      auditor_id: null,
      audit_result: '',

      naming: this.fb.group({
        risk_id_name: [{ value: '', disabled: true }],
        object_group_id_name: [{ value: '', disabled: true }],
        object_id_name: [{ value: '', disabled: false }],
        interviewed_persons_names: [{ value: '', disabled: true }],
        responsible_persons_id_names: [{ value: '', disabled: true }]
      })
    });

  }

  /*
  * Applies route parameters to the form.
  * @returns {void}
  */
  private applyRouteDefaults(): void {
    const patch: Partial<RiskAssessment> = {};

    if (this.fromRisk) {
      patch.risk_id = Number(this.route.snapshot.paramMap.get('riskId'));
    }
    if (this.fromObject) {
      patch.object_id_ref_type = IdRefType.OBJECT;
      patch.object_id = Number(this.route.snapshot.paramMap.get('objectId'));
    }
    if (this.fromObjectGroup) {
      patch.object_id_ref_type = IdRefType.OBJECT_GROUP;
      patch.object_id = Number(this.route.snapshot.paramMap.get('groupId'));
    }

    this.form.patchValue(patch, { emitEvent: false });
  }

  /*
  * Loads reference data for the form.
  * @returns {void}
  */
  private loadReferenceData(): void {
    const baseParams: CollectionParameters = {
      filter: '',
      limit: 0,
      page: 1,
      sort: 'public_id',
      order: SortDirection.ASCENDING
    };

    const shouldLoadObjects = !(this.fromObject || this.fromObjectGroup || this.isView);

    this
      .doWithLoader(
        forkJoin({
          risks: this.riskSrv.getRisks(baseParams),
          // objects: shouldLoadObjects ? this.objectSrv.getObjects(baseParams) : of({ results: [] }),
          objectGroups: this.objectGroupSrv.getObjectGroups(baseParams),
          persons: this.personSrv.getPersons(baseParams),
          personGroups: this.personGroupSrv.getPersonGroups(baseParams),
          impactCategories: this.impactCategorySrv.getImpactCategories({ ...baseParams, sort: 'sort' }),
          impacts: this.impactSrv.getImpacts({ ...baseParams, sort: 'calculation_basis' }),
          likelihoods: this.likelihoodSrv.getLikelihoods({ ...baseParams, sort: 'calculation_basis' }),
          implementationStates: this.extendableOptionSrv.getExtendableOptionsByType('IMPLEMENTATION_STATE'),
          riskMatrix: this.riskMatrixSrv.getRiskMatrix(1),
          riskClasses: this.riskClassSrv.getRiskClasses(baseParams),
          controlMeasures   : this.controlMeasureSrv.getControlMeasures(baseParams)
        })
      )
      .subscribe({
        next: (res: any) => {
          /* reference data */
          this.allRisks = res.risks.results;
          // this.allObjects = res.objects.results;
          this.allObjectGroups = res.objectGroups.results;
          this.allPersons = res.persons.results;
          this.allPersonGroups = res.personGroups.results;
          this.impacts = res.impacts.results;
          this.likelihoods = res.likelihoods.results;
          this.implementationStates = res.implementationStates.results;
          this.riskMatrix = res.riskMatrix;
          this.riskClasses = res.riskClasses.results;
          this.allControlMeasures  = res.controlMeasures.results;



          /* impact categories + build sliders */
          this.impactCategories = res.impactCategories.results;
          this.buildImpactFormArrays(this.impactCategories);


          const state = history.state;
          if (this.isEditMode || this.isView) {
            if (state && state.riskAssessment) {
              this.patchFormWithData(state.riskAssessment);
              if (this.isView) {
                this.form.disable({ emitEvent: false });
              }
              if (this.riskAssessmentId) {
                this.loadCurrentAssignments(this.riskAssessmentId);
              }
            } else {
              this.router.navigate(['/isms/risk-assessments']);
              this.toast.error('No risk assessment data provided.');
            }
          } else if (state && state.riskAssessment) {
            // Duplicate mode
            const data = { ...state.riskAssessment };
            delete data.public_id;
            this.patchFormWithData(data);
          }
        },
        error: this.handleError('Failed to load reference data')
      });
  }

  private buildImpactFormArrays(categories: any[]): void {
    const beforeArr = this.form.get('risk_calculation_before.impacts') as FormArray;
    const afterArr = this.form.get('risk_calculation_after.impacts') as FormArray;

    categories.forEach(cat => {
      const g = this.fb.group({
        impact_category_id: [cat.public_id],
        impact_id: [null]
      });
      beforeArr.push(g);
      afterArr.push(this.fb.group({ ...g.getRawValue() }));
    });
  }

  private patchFormWithData(data: any): void {
    // Patch top-level fields like likelihood_id
    this.form.patchValue(data, { emitEvent: false });

    const patchImpacts = (formArray: FormArray, impacts: any[]): void => {
      const impactMap = new Map(impacts.map(i => [i.impact_category_id, i.impact_id]));

      // Update each control in the existing FormArray
      formArray.controls.forEach(control => {
        const categoryId = control.get('impact_category_id').value;
        const impactId = impactMap.get(categoryId); // Use null if category not in data
        control.get('impact_id').setValue(impactId, { emitEvent: false });
      });
    };

    patchImpacts(
      this.form.get('risk_calculation_before.impacts') as FormArray,
      data.risk_calculation_before.impacts
    );
    patchImpacts(
      this.form.get('risk_calculation_after.impacts') as FormArray,
      data.risk_calculation_after.impacts
    );
  }

  /* ──────────────────────────────────────────────────────────────────────────
   *  Utility wrappers
   * ────────────────────────────────────────────────────────────────────────── */
  private doWithLoader<T>(stream$: Observable<T>): Observable<T> {
    this.loader.show();
    this.loading = true;
    this.loading$.next(true);

    return stream$.pipe(
      finalize(() => {
        this.loader.hide();
        this.loading = false;
        this.loading$.next(false);
      })
    );
  }

  private handleError =
    (fallback: string) =>
      (err: unknown): void =>
        this.toast.error((err as any)?.error?.message ?? fallback);

  get CurrentMode(): string {
    if (this.isEditMode) {
      return 'EDIT';
    } else if (this.isView) {
      return 'VIEW';
    } else {
      return 'add';
    }
  }


  /** EDIT / VIEW: download CM-assignments once reference data are loaded */
  private loadCurrentAssignments(raId: number): void {
    this.loader.show();
    this.cmaSrv.getAssignments({
      filter: { risk_assessment_id: raId },
      limit : 0,
      page  : 1,
      sort  : 'public_id',
      order : SortDirection.ASCENDING
    })
    .pipe(finalize(() => this.loader.hide()))
    .subscribe({
      next: (res: any) => {
        
        const arr = this.form.get('control_measure_assignments') as FormArray;
        arr.clear();
        res.results.forEach((row: any) => arr.push(this.fb.group(row)));
  
        this.treatmentBlock.setInlineToEditMode();
  
  
        res.results.forEach((row: any) => {
          this.treatmentBlock.updateInlineAvailableCMs(row.control_measure_id);
        });
      },
      error: this.handleError('Failed to load control-measure assignments')
    });
  }
}