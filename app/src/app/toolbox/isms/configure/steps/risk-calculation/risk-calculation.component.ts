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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, OnInit } from '@angular/core';
import { finalize } from 'rxjs/operators';

import { IsmsConfig } from '../../../models/isms-config.model';
import { Impact } from '../../../models/impact.model';
import { ImpactService } from '../../../services/impact.service';
import { Likelihood } from '../../../models/likelihood.model';
import { LikelihoodService } from '../../../services/likelihood.service';
import { RiskClass } from '../../../models/risk-class.model';
import { RiskClassService } from '../../../services/risk-class.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RiskMatrixService } from '../../../services/risk-matrix.service';
import { IsmsRiskMatrix, RiskMatrixCell } from 'src/app/toolbox/isms/models/risk-matrix.model';
import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';
@Component({
    selector: 'app-isms-risk-calculation',
    templateUrl: './risk-calculation.component.html',
    styleUrls: ['./risk-calculation.component.scss'],
    standalone: false
})
export class RiskCalculationComponent implements OnInit {
  @Input() config: IsmsConfig;

  // Collections from services
  public impacts: Impact[] = [];
  public likelihoods: Likelihood[] = [];
  public riskClasses: RiskClass[] = [];

  // The risk matrix from the backend.
  public riskMatrix: IsmsRiskMatrix | null = null;
  public selectedMatrixUnit = '';
  public hasChanges: boolean = false;


  // Ordered arrays to map rows to Likelihoods and columns to Impacts.
  public orderedLikelihoods: Likelihood[] = [];
  public orderedImpacts: Impact[] = [];

  public loading = false;
  public isLoading$ = this.loaderService.isLoading$;
  // Modal for assigning a risk class
  public showModal = false;
  public selectedCell: RiskMatrixCell | null = null;

  constructor(
    private impactService: ImpactService,
    private likelihoodService: LikelihoodService,
    private riskClassService: RiskClassService,
    private riskMatrixService: RiskMatrixService,
    private toast: ToastService,
    private loaderService: LoaderService
  ) { }


  ngOnInit(): void {
    this.loadAllData();
  }


  /**
   * loadAllData: Fetch Impacts, Likelihoods, Risk Classes, then load the Risk Matrix.
   */
  private loadAllData(): void {
    this.loading = true;
    this.loaderService.show();

    // 1) Load Impacts
    this.impactService.getImpacts({
      filter: '',
      limit: 0,
      page: 1,
      sort: 'calculation_basis',
      order: 1
    }).subscribe({
      next: (impResp) => {
        this.impacts = impResp.results;

        // 2) Load Likelihoods
        this.likelihoodService.getLikelihoods({
          filter: '',
          limit: 0,
          page: 1,
          sort: 'calculation_basis',
          order: 1
        }).subscribe({
          next: (lhResp) => {
            this.likelihoods = lhResp.results;

            // 3) Load Risk Classes
            this.riskClassService.getRiskClasses({
              filter: '',
              limit: 0,
              page: 1,
              sort: 'sort',
              order: 1
            }).subscribe({
              next: (rcResp) => {
                this.riskClasses = rcResp.results;
                // 4) Finally, load the matrix from the backend.
                this.loadMatrixFromBackend();
              },
              error: (error) => this.handleError(error?.error?.message)
            });
          },
          error: (error) => this.handleError(error?.error?.message)
        });
      },
      error: (error) => this.handleError(error?.error?.message)
    });
  }


  /**
   * loadMatrixFromBackend: Fetch the risk matrix, unwrap the result if needed, parse numeric values,
   * and build the row/column mappings.
   */
  private loadMatrixFromBackend(): void {
    this.riskMatrixService.getRiskMatrix(1)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (matrixData: any) => {
          // Unwrap if the backend response wraps data in "result"
          if (matrixData && matrixData.result) {
            this.riskMatrix = matrixData.result;
          } else {
            this.riskMatrix = matrixData;
          }

          // Set the matrix unit from the response if available
          if (this.riskMatrix && this.riskMatrix.matrix_unit) {
            this.selectedMatrixUnit = this.riskMatrix.matrix_unit;
          }
          // Convert string values to numbers for numeric fields.
          this.parseMatrixValues();
          // Build ordered arrays mapping rows to Likelihoods and columns to Impacts.
          this.buildRowColumnMappings();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * parseMatrixValues: Convert impact_value and likelihood_value from strings to numbers.
   */
  private parseMatrixValues(): void {
    if (!this.riskMatrix) return;
    for (const cell of this.riskMatrix.risk_matrix) {
      if (typeof cell.impact_value === 'string') {
        cell.impact_value = parseFloat(cell.impact_value);
      }
      if (typeof cell.likelihood_value === 'string') {
        cell.likelihood_value = parseFloat(cell.likelihood_value);
      }
    }
  }


  /**
   * buildRowColumnMappings: Construct ordered arrays for rows (Likelihoods) and columns (Impacts)
   * based on distinct row and column indices in the risk matrix.
   */
  private buildRowColumnMappings(): void {
    if (!this.riskMatrix || !this.riskMatrix.risk_matrix.length) {
      this.orderedLikelihoods = [];
      this.orderedImpacts = [];
      return;
    }

    // Build distinct row indices and sort descending (so the lowest row number is at the bottom).
    const rowIndices = Array.from(new Set(this.riskMatrix.risk_matrix.map(c => c.row)));
    rowIndices.sort((a, b) => b - a);
    this.orderedLikelihoods = rowIndices.map(rIndex => {
      // Use the cell with column=0 to identify the Likelihood.
      const rowCell = this.riskMatrix!.risk_matrix.find(c => c.row === rIndex && c.column === 0);
      if (rowCell) {
        const lhId = rowCell.likelihood_id;
        const lhObj = this.likelihoods.find(lh => lh.public_id === lhId);
        return lhObj || {
          public_id: lhId,
          name: `LH#${lhId}`,
          description: '',
          calculation_basis: 0,
          sort: 0
        } as Likelihood;
      }
    });

    // Build distinct column indices and sort ascending.
    const colIndices = Array.from(new Set(this.riskMatrix.risk_matrix.map(c => c.column)));
    colIndices.sort((a, b) => a - b);
    this.orderedImpacts = colIndices.map(cIndex => {
      // Use the cell with row=0 to identify the Impact.
      const colCell = this.riskMatrix!.risk_matrix.find(cell => cell.column === cIndex && cell.row === 0);
      if (colCell) {
        const impId = colCell.impact_id;
        const impObj = this.impacts.find(i => i.public_id === impId);
        return impObj || {
          public_id: impId,
          name: `IMP#${impId}`,
          description: '',
          calculation_basis: 0,
          sort: 0
        } as Impact;
      }
    });
  }


  /**
   * handleError: Generic error handler that displays a toast message and logs the error.
   */
  private handleError(message: string): void {
    this.toast.error(message);
    this.loading = false;
    this.loaderService.hide();
  }


  /**
   * Get row count from orderedLikelihoods.
   */
  public get rowCount(): number {
    return this.orderedLikelihoods.length;
  }


  /**
   * Get column count from orderedImpacts.
   */
  public get columnCount(): number {
    return this.orderedImpacts.length;
  }


  /**
   * getLikelihoodForRow: Return the Likelihood for a given row index.
   */
  public getLikelihoodForRow(rowIndex: number): Likelihood {
    // if (rowIndex < 0 || rowIndex >= this.orderedLikelihoods.length) {
    //   return { public_id: -999, name: 'Invalid LH Index', description: '', calculation_basis: 0, sort: 0 } as Likelihood;
    // }
    return this.orderedLikelihoods[rowIndex];
  }


  /**
   * getImpactForColumn: Return the Impact for a given column index.
   */
  public getImpactForColumn(colIndex: number): Impact {
    // if (colIndex < 0 || colIndex >= this.orderedImpacts.length) {
    //   return { public_id: -999, name: 'Invalid IMP Index', description: '', calculation_basis: 0, sort: 0 } as Impact;
    // }
    return this.orderedImpacts[colIndex];
  }


  /**
   * getCell: Find the matrix cell for the given row (Likelihood) and column (Impact).
   */
  public getCell(rowIndex: number, colIndex: number): RiskMatrixCell | null {
    if (!this.riskMatrix) return null;
    const lhId = this.getLikelihoodForRow(rowIndex).public_id;
    const impId = this.getImpactForColumn(colIndex).public_id;
    const cell = this.riskMatrix.risk_matrix.find(
      c => c.likelihood_id === lhId && c.impact_id === impId
    );
    return cell || null;
  }

  /**
   * getCellColor: Return background color for a cell based on its risk_class_id.
   * If unassigned (0), returns light grey.
   */
  public getCellColor(cell: RiskMatrixCell | null): string {
    if (!cell || cell.risk_class_id === 0) return '#f5f5f5';
    const rc = this.riskClasses.find(r => r.public_id === cell.risk_class_id);
    return rc?.color || '#f5f5f5';
  }


  /**
   * getRiskClassName: Return the risk class name for a cell, or 'Unassigned'.
   */
  public getRiskClassName(cell: RiskMatrixCell | null): string {
    if (!cell || cell.risk_class_id === 0) return 'Unassigned';
    const rc = this.riskClasses.find(r => r.public_id === cell.risk_class_id);
    return rc ? rc.name : 'Unknown';
  }


  /**
   * openRiskClassModal: Open the modal to assign a risk class for a cell.
   */
  public openRiskClassModal(cell: RiskMatrixCell | null): void {
    if (!cell) return;
    this.selectedCell = cell;
    this.showModal = true;
  }


  /**
   * closeModal: Close the risk class selection modal.
   */
  public closeModal(): void {
    this.showModal = false;
    this.selectedCell = null;
  }


  /**
   * assignRiskClass: Assign the selected risk class to the selected cell.
   */
  public assignRiskClass(riskClass: RiskClass): void {
    if (!this.selectedCell) return;
    this.selectedCell.risk_class_id = riskClass.public_id;
    this.hasChanges = true;
    this.closeModal();
  }


  /**
   * saveMatrix: Save the updated risk matrix to the backend.
   * The current matrix_unit (from the dropdown) is included in the payload.
   */
  public saveMatrix(): void {
    if (!this.riskMatrix) return;
    this.riskMatrix.matrix_unit = this.selectedMatrixUnit;
    this.loaderService.show();
    this.riskMatrixService.updateRiskMatrix(this.riskMatrix)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Risk calculation settings saved successfully');
          this.hasChanges = false;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * getCellColor: Return background and text color for a cell based on its risk_class_id.
   * If unassigned (0), returns light grey with default text color.
   */
  public getCellStyles(cell: RiskMatrixCell | null): { backgroundColor: string; color: string } {
    if (!cell || cell.risk_class_id === 0) {
      return { backgroundColor: '#f5f5f5', color: '#000' }; // Default grey background with black text
    }

    const rc = this.riskClasses.find(r => r.public_id === cell.risk_class_id);
    const backgroundColor = rc?.color || '#f5f5f5';
    const textColor = getTextColorBasedOnBackground(backgroundColor);

    return { backgroundColor, color: textColor };
  }

  /**
 * isMatrixComplete: Returns true if every cell in the risk matrix
 * has a risk_class_id different than 0.
 */
  public isMatrixComplete(): boolean {
    if (!this.riskMatrix || !this.riskMatrix.risk_matrix.length) return false;
    return this.riskMatrix.risk_matrix.every(cell => cell.risk_class_id !== 0);
  }

    /**
     * Called when the matrix unit is changed.
     */
    public onMatrixUnitChange(value: string): void {
      this.hasChanges = true;
    }

  /**
   * Wrapper for getTextColorBasedOnBackground to make it accessible in the template.
   */
  public getTextColor(color: string): string {
    return getTextColorBasedOnBackground(color);
  }
}