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
import { Component, OnInit, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { combineLatest, Subscription } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { AutomationsService } from '../../services/automations.service';
import { ConnectorsService } from '../../../connectors/services/connectors.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Connector } from '../../../connectors/models/connector.model';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { InternalConnectorPasswordModalComponent } from '../internal-connector-password-modal/internal-connector-password-modal.component';

@Component({
  selector: 'app-automation-form',
  templateUrl: './automation-form.component.html',
  styleUrls: ['./automation-form.component.scss']
})
export class AutomationFormComponent implements OnInit, OnDestroy {
  mode: 'create' | 'edit' = 'create';
  id?: number;

  form!: FormGroup;
  templates: any[] = [];
  filteredTemplates: any[] = [];
  connectors: Connector[] = [];
  showConnectorField = false;
  connectorLabel = '';

  // Internal connector properties
  internalConnectorExists: boolean = false;
  internalConnectorDetails: any = null;
  isCheckingInternalConnector: boolean = false;
  isGettingInternalConnector: boolean = false;

  private formChangesSubscription?: Subscription;

  public isLoading$ = this.loaderService.isLoading$;

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private svc: AutomationsService,
    private connectorsService: ConnectorsService,
    private modalService: NgbModal,
    private toast: ToastService,
    private loaderService: LoaderService
  ) { 
  }

  ngOnInit(): void {
    this.mode = (this.route.snapshot.data['mode'] || 'create') as any;
    this.buildForm();
    this.loadInitData();

    if (this.mode === 'edit') {
      this.id = +this.route.snapshot.paramMap.get('id')!;
      
      // Check if automation was passed via state 
      const automation = history.state?.automation;
      if (automation) {
        this.patchForEdit(automation);
      } 
    }
  }

  ngOnDestroy(): void {
    if (this.formChangesSubscription) {
      this.formChangesSubscription.unsubscribe();
    }
  }

  private loadInitData(): void {
    console.log('Starting to load initial data...');
    this.svc.getInitData().subscribe({
      next: (initData) => {
        console.log('Initial data loaded successfully');
        this.connectors = initData.connectors || [];
        this.templates = initData.templates || [];
        this.filteredTemplates = [...this.templates];
        console.log('Loaded connectors count:', this.connectors.length, this.connectors);
        console.log('Loaded templates count:', this.templates.length, this.templates);
        
        // Set up form changes after data is loaded
        console.log('Setting up form changes subscription...');
        this.setupFormChanges();
        
        // Trigger initial update based on current form values
        const currentDirection = this.form.get('direction')?.value;
        const currentConnector = this.form.get('connector')?.value;
        console.log('Current direction value:', currentDirection);
        console.log('Current connector value:', currentConnector);
        
        console.log('Calling updateConnectorFieldVisibility with direction:', currentDirection);
        this.updateConnectorFieldVisibility(currentDirection);
        console.log('showConnectorField after update:', this.showConnectorField);
        console.log('connectorLabel after update:', this.connectorLabel);
        
        console.log('Calling filterTemplates with direction:', currentDirection, 'and connector:', currentConnector);
        this.filterTemplates(currentDirection, currentConnector);
        console.log('Filtered templates count after initial filter:', this.filteredTemplates.length);
        
        // Check if internal connector exists
        console.log('Checking for internal connector...');
        this.checkInternalConnector();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        console.log('Error loading initial data:', err?.error?.message);
      }
    });
  }

  private setupFormChanges(): void {
    console.log('Setting up form changes subscriptions...');
    
    // Separate subscription for direction changes to ensure label updates
    const directionSubscription = this.form.get('direction')!.valueChanges.subscribe(direction => {
      console.log(' DIRECTION CHANGED:', direction);
      this.updateConnectorFieldVisibility(direction);
    });

    // CombineLatest for template filtering
    const combineSubscription = combineLatest([
      this.form.get('direction')!.valueChanges,
      this.form.get('connector')!.valueChanges
    ]).subscribe(([direction, connector]) => {
      console.log(' COMBINE LATEST - Direction:', direction, 'Connector:', connector);
      this.filterTemplates(direction, connector);
    });

    // Store both subscriptions
    this.formChangesSubscription = new Subscription();
    this.formChangesSubscription.add(directionSubscription);
    this.formChangesSubscription.add(combineSubscription);
    
    console.log('Form changes subscriptions set up successfully');
  }

  private updateConnectorFieldVisibility(direction: string): void {
    console.log('updateConnectorFieldVisibility called with direction:', direction);
    this.showConnectorField = !!direction;
    console.log('showConnectorField set to:', this.showConnectorField);
    
    if (direction === 'outgoing') {
      this.connectorLabel = 'To Connector';
    } else if (direction === 'incoming') {
      this.connectorLabel = 'From Connector';
    } else {
      this.connectorLabel = '';
    }
    console.log('connectorLabel set to:', this.connectorLabel);
  }

  private filterTemplates(direction: string, connectorId: number): void {
    console.log('filterTemplates called with direction:', direction, 'connectorId:', connectorId);
    
    // If no direction or no connector, show empty list (waiting for user selection)
    if (!direction || !connectorId) {
      console.log('No direction or connector selected, showing empty template list');
      this.filteredTemplates = [];
      return;
    }

    const selectedConnector = this.connectors.find(c => c.connectorId === connectorId);
    console.log('Selected connector:', selectedConnector);
    
    if (!selectedConnector) {
      console.log('No selected connector found, showing empty template list');
      this.filteredTemplates = [];
      return;
    }

    console.log('Filtering templates for direction:', direction, 'and connector:', selectedConnector.invoker.name);
    
    this.filteredTemplates = this.templates.filter(template => {
      if (!template.connection) {
        console.log('Template has no connection:', template);
        return false;
      }

      console.log('Checking template:', template.name, 'with connection:', template.connection);
      
      if (direction === 'outgoing') {
        const matches = template.connection.fromConnector?.invoker?.name === 'DATAGerry' &&
               template.connection.toConnector?.invoker?.name === selectedConnector.invoker.name;
        console.log('Outgoing template match:', matches, 'for template:', template.name);
        console.log('  - From:', template.connection.fromConnector?.invoker?.name, 'Expected: DATAGerry');
        console.log('  - To:', template.connection.toConnector?.invoker?.name, 'Expected:', selectedConnector.invoker.name);
        return matches;
      } else if (direction === 'incoming') {
        const matches = template.connection.toConnector?.invoker?.name === 'DATAGerry' &&
               template.connection.fromConnector?.invoker?.name === selectedConnector.invoker.name;
        console.log('Incoming template match:', matches, 'for template:', template.name);
        console.log('  - To:', template.connection.toConnector?.invoker?.name, 'Expected: DATAGerry');
        console.log('  - From:', template.connection.fromConnector?.invoker?.name, 'Expected:', selectedConnector.invoker.name);
        return matches;
      }
      return false;
    });
    
    console.log('Final filtered templates count:', this.filteredTemplates.length);
    console.log('Final filtered templates:', this.filteredTemplates.map(t => t.name));
  }
  

  private buildForm(): void {
    console.log('Building form with default direction: incoming');
    this.form = this.fb.group({
      name: ['', Validators.required],
      description: [''],
      direction: ['incoming', Validators.required], // Set incoming as default
      connector: [''],
      business_template: ['', Validators.required]
    });
    console.log('Form built with direction control value:', this.form.get('direction')?.value);
  }

  private patchForEdit(automation: any): void {
    this.form.patchValue({
      name: automation.name,
      description: automation.description || '',
      direction: automation.direction,
      business_template: automation.business_template
    });
  }

  // Internal connector methods
  private checkInternalConnector(): void {
    this.isCheckingInternalConnector = true;
    console.log('Checking if internal connector exists...');

    this.connectorsService.checkConnectorExists('DataGerryInternal').subscribe({
      next: (exists) => {
        console.log('Internal connector exists:', exists);
        this.internalConnectorExists = exists;
        this.isCheckingInternalConnector = false;
        
        if (exists) {
          console.log('Internal connector exists, opening password modal...');
          this.openPasswordModal();
        } else {
          console.log('Internal connector does not exist, using hardcoded values');
        }
      },
      error: (err) => {
        console.error('Error checking internal connector:', err);
        this.toast.error('Failed to check internal connector existence');
        this.isCheckingInternalConnector = false;
        this.internalConnectorExists = false;
      }
    });
  }

  private openPasswordModal(): void {
    console.log('Opening password modal for internal connector...');
    const modalRef = this.modalService.open(InternalConnectorPasswordModalComponent, { 
      size: 'md',
      backdrop: 'static'
    });

    modalRef.result.then(
      (password: string) => {
        console.log('Password provided, getting internal connector details...');
        this.getInternalConnector(password);
      },
      (reason) => {
        console.log('Password modal dismissed:', reason);
        if (reason !== 'cancel') {
          this.toast.warning('Internal connector authentication cancelled');
        }
      }
    );
  }

  private getInternalConnector(password: string): void {
    this.isGettingInternalConnector = true;
    console.log('Getting internal connector details with password...');

    this.connectorsService.getInternalConnectorCredentials(password).subscribe({
      next: (connectorDetails) => {
        console.log('Internal connector details received:', connectorDetails);
        this.internalConnectorDetails = connectorDetails;
        this.isGettingInternalConnector = false;
        this.toast.success('Internal connector authenticated successfully');
      },
      error: (err) => {
        console.error('Error getting internal connector details:', err);
        this.isGettingInternalConnector = false;
        this.toast.error('Failed to authenticate internal connector. Please check the password.');
        
        // Reopen password modal on error
        const modalRef = this.modalService.open(InternalConnectorPasswordModalComponent, { 
          size: 'md',
          backdrop: 'static'
        });
        
        // Set error message on the modal
        modalRef.componentInstance.setError('Invalid password. Please try again.');
        
        modalRef.result.then(
          (newPassword: string) => {
            this.getInternalConnector(newPassword);
          },
          () => {
            this.toast.warning('Internal connector authentication cancelled');
          }
        );
      }
    });
  }

  // Action methods
  private toPayload(): any {
    const v = this.form.value;
    const selectedConnector = this.connectors.find(c => c.connectorId === v.connector?.connectorId);
    
    if (!selectedConnector) {
      throw new Error('Please select a connector');
    }

    // Determine which connector to use for DATAGerry (internal connector)
    let datagerryConnector;
    if (this.internalConnectorDetails) {
      console.log('Using actual internal connector details:', this.internalConnectorDetails);
      datagerryConnector = {
        connectorId: this.internalConnectorDetails.connectorId,
        invoker: this.internalConnectorDetails.invoker,
        methods: this.internalConnectorDetails.methods || [],
        operators: this.internalConnectorDetails.operators || []
      };
    } else {
      console.log('Using hardcoded DATAGerry connector details');
      datagerryConnector = {
        connectorId: 1, // DATAGerry connector ID (assuming 1 for DATAGerry)
        invoker: { name: 'DataGerry' },
        methods: [],
        operators: []
      };
    }

    // Build connection payload
    const connectionPayload = {
      title: v.name,
      description: v.description,
      fieldBinding: [],
      fromConnector: v.direction === 'outgoing' 
        ? datagerryConnector
        : {
            connectorId: selectedConnector.connectorId,
            invoker: selectedConnector.invoker,
            methods: [],
            operators: []
          },
      toConnector: v.direction === 'outgoing'
        ? {
            connectorId: selectedConnector.connectorId,
            invoker: selectedConnector.invoker,
            methods: [],
            operators: []
          }
        : datagerryConnector,
      ui: null
    };

    // Build scheduler payload
    const schedulerPayload = {
      title: v.name,
      debugMode: false,
      connectionId: this.id || 0, // Will be set by backend for create, existing ID for edit
      cronExp: '0 1 * * * ?', // Default cron expression (1 AM daily)
      status: 1 // Active
    };

    return {
      connection: connectionPayload,
      scheduler: schedulerPayload
    };
  }

  save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.toast.warning('Please fill in all required fields');
      return;
    }

    // Additional validation for connector when direction is selected
    if (this.showConnectorField && !this.form.get('connector')?.value) {
      this.toast.warning('Please select a connector');
      return;
    }

    try {
      const payload = this.toPayload();
      const req$ = this.mode === 'create'
        ? this.svc.createAutomation(payload)
        : this.svc.updateAutomation(this.id!, payload);

      this.loaderService.show();

      req$.pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: () => {
            this.toast.success(
              this.mode === 'create'
                ? 'Automation created successfully'
                : 'Automation updated successfully'
            );
            this.router.navigate(['/automations']);
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } catch (error) {
      this.toast.error((error as Error).message);
    }
  }

  cancel(): void {
    this.router.navigate(['../'], { relativeTo: this.route });
  }
}
