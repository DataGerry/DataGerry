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
import {
    Component, OnInit, OnChanges, SimpleChanges, Input,
    TemplateRef, ViewChild, DestroyRef
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize, map } from 'rxjs/operators';
import { forkJoin, Observable } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { RiskAssessmentService } from '../../services/risk-assessment.service';
import { PersonService } from '../../services/person.service';
import { PersonGroupService } from '../../services/person-group.service';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { RiskMatrixService } from '../../services/risk-matrix.service';
import { RiskClassService } from '../../services/risk-class.service';

import { RiskAssessment } from '../../models/risk-assessment.model';
import { RiskClass } from '../../models/risk-class.model';

import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';
import { DuplicateRiskAssessmentModalComponent } from './duplicate-risk-assessment-modal/duplicate-risk-assessment.modal';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { IsmsValidationService } from '../../services/isms-validation.service';

const GREY = '#f5f5f5';

@Component({
    selector: 'app-risk-assessment-list',
    templateUrl: './risk-assessment-list.component.html',
    styleUrls: ['./risk-assessment-list.component.scss'],
    standalone: false
})
export class RiskAssessmentListComponent implements OnInit, OnChanges {

    /* ────────── incoming filters (embedding) ────────── */
    @Input() riskId?: number;
    @Input() objectId?: number;
    @Input() groupId?: number;
    @Input() assessmentIds: number[] = null;
    @Input() fromReport = false;
    @Input() riskSummaryLine: string = '';
    @Input() objectGroupName: string = '';

    /* ────────── column templates ────────── */
    @ViewChild('actionTpl', { static: true }) actionTpl!: TemplateRef<any>;
    @ViewChild('riskTpl', { static: true }) riskTpl!: TemplateRef<any>;
    @ViewChild('beforeTpl', { static: true }) beforeTpl!: TemplateRef<any>;
    @ViewChild('afterTpl', { static: true }) afterTpl!: TemplateRef<any>;
    @ViewChild('implTpl', { static: true }) implTpl!: TemplateRef<any>;
    @ViewChild('respTpl', { static: true }) respTpl!: TemplateRef<any>;
    // Table Custom Template: Link add button
    @ViewChild('addButtonTemplate', { static: true }) addButtonTemplate: TemplateRef<any>;

    /* ────────── table state ────────── */
    rows: RiskAssessment[] = [];
    total = 0;
    page = 1;
    limit = 10;
    sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING };
    loading = false;
    isLoading$ = this.loader.isLoading$;
    public filter = '';
    public configurationIsValid: boolean = false;

    columns: Column[] = [];
    initialVisibleColumns: string[] = [];

    /* ────────── look-up maps ────────── */
    private personNameMap = new Map<number, string>();
    private groupNameMap = new Map<number, string>();
    private implStateMap = new Map<number, string>();
    private riskMatrixFlat: any[] = [];
    private riskClassMap = new Map<number, RiskClass>();

    constructor(
        private readonly route: ActivatedRoute,
        private readonly router: Router,
        private readonly destroyRef: DestroyRef,

        private readonly riskAssessmentService: RiskAssessmentService,
        private readonly personService: PersonService,
        private readonly personGroupService: PersonGroupService,
        private readonly optionService: ExtendableOptionService,
        private readonly riskMatrixService: RiskMatrixService,
        private readonly riskClassService: RiskClassService,
        private readonly filterBuilder: FilterBuilderService,
        private readonly ismsValidationService: IsmsValidationService,


        private readonly loader: LoaderService,
        private readonly toast: ToastService,
        private readonly modal: NgbModal,
        public activeModal: NgbActiveModal

    ) { }

    /* ══════════════════ life-cycle ══════════════════ */
    ngOnInit(): void {

        this.ismsValidationService.checkConfigSilently().subscribe({
            next: (isValid) => {
                this.configurationIsValid = isValid;
                if (!isValid) return;
                this.readFiltersFromRoute();
                this.columns = this.buildColumns();
                this.initialVisibleColumns = this.columns.filter(c => !c.hidden)
                    .map(c => c.name);

                this.loadReferenceData()
                    .subscribe({ next: () => this.loadRows() });
            },
            error: (err) => {
                this.toast.error(err?.error?.message);
            }
        })


    }

    ngOnChanges(ch: SimpleChanges): void {
        if (ch['riskId'] || ch['objectId'] || ch['groupId']) {
            this.page = 1;
            this.loadRows();
        }
    }

    /* ══════════════════ private helpers ══════════════════ */

    private readFiltersFromRoute(): void {
        const p = this.route.snapshot.paramMap;
        this.riskId ??= p.get('riskId') ? +p.get('riskId')! : undefined;
        this.objectId ??= p.get('objectId') ? +p.get('objectId')! : undefined;
        this.groupId ??= p.get('groupId') ? +p.get('groupId')! : undefined;
    }

    private buildColumns(): Column[] {
        return [
            { display: 'Risk', name: 'risk', data: 'risk_id', template: this.riskTpl, style: { 'text-align': 'center' } },
            {
                display: 'Risk before treatment',
                name: 'risk_before', data: 'public_id',
                template: this.beforeTpl,
                style: { width: '170px', 'text-align': 'center' }
            },
            {
                display: 'Risk after treatment',
                name: 'risk_after', data: 'public_id',
                template: this.afterTpl,
                style: { width: '170px', 'text-align': 'center' }
            },
            {
                display: 'Implementation state',
                name: 'implementation_status',
                data: 'implementation_status', template: this.implTpl,
                style: { 'text-align': 'center' }
            },
            {
                display: 'Responsible',
                name: 'responsible',
                data: 'responsible_persons_id',
                template: this.respTpl,
                style: { 'text-align': 'center' }
            },
            {
                display: 'Actions',
                name: 'actions', data: 'public_id', fixed: true,
                template: this.actionTpl,
                style: { width: '140px', 'text-align': 'center' }
            }
        ];
    }

    /* ───── build filter object for API ───── */
    private buildFilter(): any {
        if (this.riskId) { return { risk_id: this.riskId }; }

        if (this.objectId) {
            return {
                $and: [
                    { object_id_ref_type: 'OBJECT' },
                    { object_id: this.objectId }
                ]
            };
        }
        if (this.groupId) {
            return {
                $and: [
                    { object_id_ref_type: 'OBJECT_GROUP' },
                    { object_id: this.groupId }
                ]
            };
        }
        if (this.assessmentIds) {
            return { public_id: { $in: this.assessmentIds } };
        }
        return {};
    }

    /* ───── dictionaries (names, matrix, classes) ───── */
    private loadReferenceData(): Observable<void> {

        this.loader.show(); this.loading = true;

        const base: CollectionParameters = {
            filter: '', limit: 0, page: 1,
            sort: 'public_id', order: SortDirection.ASCENDING
        };

        return forkJoin({
            persons: this.personService.getPersons(base),
            groups: this.personGroupService.getPersonGroups(base),
            implOpt: this.optionService.getExtendableOptionsByType('IMPLEMENTATION_STATE'),
            matrix: this.riskMatrixService.getRiskMatrix(1).pipe(
                map((r: any) => r.result?.risk_matrix ?? r.risk_matrix ?? []),
                map((arr: any[]) => arr.map(c => ({
                    ...c,
                    impact_value: +c.impact_value,
                    likelihood_value: +c.likelihood_value
                })))
            ),
            classes: this.riskClassService.getRiskClasses(base)
        }).pipe(
            map(res => {
                // res.risks.results.forEach((r: any) => this.riskNameMap.set(r.public_id, r.name));
                res.persons.results.forEach((p: any) => this.personNameMap.set(p.public_id, p.display_name));
                res.groups.results.forEach((g: any) => this.groupNameMap.set(g.public_id, g.name));
                res.implOpt.results.forEach((o: any) => this.implStateMap.set(o.public_id, o.value));
                res.classes.results.forEach((c: RiskClass) => this.riskClassMap.set(c.public_id, c));
                this.riskMatrixFlat = res.matrix;
            }),
            finalize(() => { this.loader.hide(); this.loading = false; }),
            takeUntilDestroyed(this.destroyRef)
        );
    }

    /* ───── rows ───── */

    /* ───── rows ───── */
    private loadRows(): void {
        this.loader.show();
        this.loading = true;

        const ctxFilter: Record<string, any> = this.buildFilter();   // {} if none

        /*  Search filter from the global box */
        let searchFilter: Record<string, any> = {};
        if (this.filter.trim().length) {
            const raw = this.filterBuilder.buildFilter(
                this.filter,
                [
                    { name: 'naming.risk_id_name' },
                    { name: 'naming.object_id_name' },
                    { name: 'naming.responsible_persons_id_names' },
                    { name: 'public_id' }
                ]
            );

            // buildFilter() may return string | object | any[]
            try {
                if (typeof raw === 'string') {
                    searchFilter = JSON.parse(raw);        // string -> object
                } else if (Array.isArray(raw)) {
                    searchFilter = { $or: raw };           // array -> wrap in $or
                } else if (raw && typeof raw === 'object') {
                    searchFilter = raw;                    // already an object
                }
            } catch (e) {
                searchFilter = {};
            }
        }

        /* 4 ▪ Merge filters (ignore empties, flatten nested $and) */
        const parts: Record<string, any>[] = [];

        const push = (part: Record<string, any>) => {
            if (!part || !Object.keys(part).length) { return; }

            if (part.$and && Array.isArray(part.$and)) {
                part.$and.forEach(p => push(p));         // flatten
            } else {
                parts.push(part);
            }
        };

        push(ctxFilter);
        push(searchFilter);

        const finalFilter =
            parts.length > 1 ? { $and: parts } :
                parts.length === 1 ? parts[0] : {};

        /* 5 ▪ Call backend */
        const params: CollectionParameters = {
            filter: finalFilter,    
            page: this.page,
            limit: this.limit,
            sort: this.sort.name,
            order: this.sort.order
        };

        this.riskAssessmentService.getRiskAssessments(params)
            .pipe(finalize(() => {
                this.loader.hide();
                this.loading = false;
            }))
            .subscribe({
                next: res => {
                    this.rows = res.results;
                    this.total = res.total;
                },
                error: err => this.toast.error(err?.error?.message)
            });
    }




    /* ───── table events ───── */
    onPageChange(p: number) { this.page = p; this.loadRows(); }
    onPageSizeChange(l: number) { this.limit = l; this.page = 1; this.loadRows(); }
    onSortChange(s: Sort) { this.sort = s; this.loadRows(); }
    onSearchChange(search: string): void {
        this.filter = search.trim();
        this.page = 1;       // reset paging so the user sees results immediately
        this.loadRows();
    }

    /* ───── look-ups ───── */
    riskName(row: RiskAssessment): string {
        return row.naming?.risk_id_name || '–';
    }
    implState(id: number) { return this.implStateMap.get(id) ?? id; }

    responsible(row: RiskAssessment): string {
        return row.naming?.responsible_persons_id_names || '–';
    }

    /* ───── colour helpers ───── */
    private colour(maxImpact: number, lh: number): string {
        if (!this.riskMatrixFlat.length || !maxImpact || !lh) { return GREY; }

        const cell = this.riskMatrixFlat.find(
            (c: any) => c.impact_value === maxImpact && c.likelihood_value === lh
        );
        const cls = cell ? this.riskClassMap.get(cell.risk_class_id) : undefined;
        return cls?.color ?? GREY;
    }

    riskBeforeColour(row: RiskAssessment) {
        return this.colour(
            row.risk_calculation_before?.maximum_impact_value ?? 0,
            row.risk_calculation_before?.likelihood_value ?? 0
        );
    }
    riskAfterColour(row: RiskAssessment) {
        return this.colour(
            row.risk_calculation_after?.maximum_impact_value ?? 0,
            row.risk_calculation_after?.likelihood_value ?? 0
        );
    }

    riskBeforeValue(row: RiskAssessment) {
        return (row.risk_calculation_before?.maximum_impact_value ?? 0) *
            (row.risk_calculation_before?.likelihood_value ?? 0);
    }
    riskAfterValue(row: RiskAssessment) {
        return (row.risk_calculation_after?.maximum_impact_value ?? 0) *
            (row.risk_calculation_after?.likelihood_value ?? 0);
    }

    /* ───── actions ───── */
    onEdit(row: RiskAssessment): void {
        this.activeModal.dismiss();
        switch (this.ctx()) {
            case 'RISK':
                this.router.navigate(
                    [`/isms/risks/${this.riskId}/risk-assessments/edit`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'OBJECT':
                this.router.navigate(
                    [`/isms/objects/${this.objectId}/risk-assessments/edit`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'GROUP':
                this.router.navigate(
                    [`/isms/object-groups/${this.groupId}/risk-assessments/edit`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'REPORT':
                this.router.navigate(
                    [`/isms/risk-assessments/edit`, row.public_id],
                    { state: { riskAssessment: row, fromReport: true } }
                );
                return;

            default:
                this.router.navigate(
                    ['/isms/risk-assessments/edit', row.public_id],
                    { state: { riskAssessment: row } });
        }
    }


    onDuplicate(row: RiskAssessment): void {
        const ref = this.modal.open(DuplicateRiskAssessmentModalComponent, { size: 'lg' });
        ref.componentInstance.ctx = this.ctx();    // OBJECT | GROUP | RISK
        ref.componentInstance.item = row;
        ref.componentInstance.objectSummaryLine = row.naming?.object_id_name ?? '';
        ref.componentInstance.objectGroupName = this.objectGroupName ?? '';
        ref.componentInstance.riskSummaryLine = this.riskSummaryLine ?? '';

        ref.result.then(() => this.loadRows()).catch(() => {/* dismissed */ });
    }


    onView(row: RiskAssessment): void {
        this.activeModal.dismiss();
        switch (this.ctx()) {
            case 'RISK':
                this.router.navigate(
                    [`/isms/risks/${this.riskId}/risk-assessments/view`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'OBJECT':
                this.router.navigate(
                    [`/isms/objects/${this.objectId}/risk-assessments/view`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'GROUP':
                this.router.navigate(
                    [`/isms/object-groups/${this.groupId}/risk-assessments/view`, row.public_id],
                    { state: { riskAssessment: row } });
                return;

            case 'REPORT':
                this.router.navigate(
                    [`/isms/risk-assessments/view`, row.public_id],
                    { state: { riskAssessment: row, fromReport: true } }
                );
                return;

            default:
                this.router.navigate(
                    ['/isms/risk-assessments/view', row.public_id],
                    { state: { riskAssessment: row } });
        }
    }


    /* ───── DELETE helper ───── */
    onDelete(row: RiskAssessment): void {

        const ref = this.modal.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
        ref.componentInstance.title = 'Delete Risk-Assessment';
        ref.componentInstance.item = row;
        ref.componentInstance.itemType = 'Risk-Assessment';
        ref.componentInstance.itemName = `#${row.public_id}`;

        ref.result.then(result => {
            if (result !== 'confirmed') { return; }

            this.loader.show();
            this.riskAssessmentService
                .deleteRiskAssessment(row.public_id!)
                .pipe(finalize(() => this.loader.hide()))
                .subscribe({
                    next: () => { this.toast.success('Deleted'); this.loadRows(); },
                    error: err => this.toast.error(err?.error?.message)
                });
        }).catch(() => { /* dismissed */ });
    }

    private ctx(): 'RISK' | 'OBJECT' | 'GROUP' | 'REPORT' | 'NONE' {
        if (this.riskId) { return 'RISK'; }
        if (this.objectId) { return 'OBJECT'; }
        if (this.groupId) { return 'GROUP'; }
        if (this.assessmentIds) return 'REPORT';
        return 'NONE';
    }


    onAddAssessment(): void {
        if (this.objectId) {
            this.router.navigate(
                ['/isms/objects', this.objectId, 'risk-assessments', 'add'],
            );
        } else if (this.riskId) {
            this.router.navigate(
                ['/isms/risks', this.riskId, 'risk-assessments', 'add'],
                { state: { riskName: this.riskSummaryLine } }
            );
        } else if (this.groupId) {
            this.router.navigate(
                ['/isms/object-groups', this.groupId, 'risk-assessments', 'add'],
                { state: { objectGroupName: this.objectGroupName } }
            );
        }


        else {
            this.router.navigate(['/isms/risk-assessments/add']);
        }
    }

    isEditable(item: RiskAssessment): boolean {
        // If viewing from Group then always editable
        if (this.groupId) return true;

        if (this.riskId) return true;

        // If not OBJECT_GROUP then editable
        return item?.object_id_ref_type !== 'OBJECT_GROUP' && this.objectId !== undefined;
    }

    showInheritedBadge(item: RiskAssessment): boolean {
        // Show badge only if OBJECT_GROUP and NOT coming from Group context
        return item?.object_id_ref_type === 'OBJECT_GROUP' && !this.groupId && this.objectId !== undefined;
    }


    /**
     * Wrapper for getTextColorBasedOnBackground to make it accessible in the template.
     */
    public getTextColor(color: string): string {
        return getTextColorBasedOnBackground(color);
    }
}