/*
* DataGerry - OpenSource Enterprise CMDB
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
import { combineLatest, Subscription, BehaviorSubject } from 'rxjs';
import { finalize, map } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { AutomationsService } from '../../services/automations.service';
import { ConnectorsService } from '../../../connectors/services/connectors.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Connector } from '../../../connectors/models/connector.model';
import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';

@Component({
  selector: 'app-automation-form',
  templateUrl: './automation-form.component.html',
  styleUrls: ['./automation-form.component.scss'],
  standalone: false
})
export class AutomationFormComponent implements OnInit, OnDestroy {
  mode: 'create' | 'edit' = 'create';
  id?: number;

  form!: FormGroup;
  templates: any[] = [];
  filteredTemplates: any[] = [];
  connectors: Connector[] = [];
  externalConnectors: Connector[] = []; // Connectors excluding the internal one
  showConnectorField = false;
  connectorLabel = '';

  // Internal connector properties
  internalConnectorExists: boolean = false;
  internalConnectorDetails: any = null;
  isCheckingInternalConnector: boolean = false;
  isGettingInternalConnector: boolean = false;

  private formChangesSubscription?: Subscription;

  // Combined loading state for all operations
  public combinedLoading$ = combineLatest([
    this.loaderService.isLoading$,
    new BehaviorSubject(this.isCheckingInternalConnector),
    new BehaviorSubject(this.isGettingInternalConnector)
  ]).pipe(
    map(([loaderLoading, checking, getting]) => loaderLoading || checking || getting)
  );

  public isLoading$ = this.loaderService.isLoading$;

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private svc: AutomationsService,
    private connectorsService: ConnectorsService,
    private toast: ToastService,
    private loaderService: LoaderService,
    private modalService: NgbModal
  ) { 
  }

  ngOnInit(): void {
    this.mode = (this.route.snapshot.data['mode'] || 'create') as any;
    this.buildForm();

    // First check if internal connector exists
    console.log('Checking internal connector existence...');
    this.checkInternalConnector();

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
        // Filter out the internal connector from the list of selectable connectors
        this.externalConnectors = this.connectors.filter(connector => connector.title !== 'DataGerryInternal');
        this.templates = initData.templates || [];
        this.filteredTemplates = [...this.templates];
        console.log('Loaded connectors count:', this.connectors.length, this.connectors);
        console.log('Loaded external connectors count:', this.externalConnectors.length, this.externalConnectors);
        console.log('Loaded templates count:', this.templates.length, this.templates);
        
        // Set internal connector details from init data
        const internalConnector = this.connectors.find(c => c.title === 'DataGerryInternal');
        if (internalConnector) {
          console.log('Internal connector details set from init data:', internalConnector);
          this.internalConnectorDetails = internalConnector;
        } else {
          console.log('Internal connector not found in init data, redirecting to setup...');
          this.redirectToInternalConnectorSetup();
          return;
        }
        
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
      },
      error: (err) => {
        this.toast.error(err?.error?.message || 'Failed to load initial data');
        console.log('Error loading initial data:', err?.error?.message);
        this.router.navigate(['/automations']);
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
    
    // Reset connector selection when direction changes to prevent auto-selection issues
    this.form.patchValue({ connector: '' });
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
    
    const filtered = this.templates.filter(template => {
      if (!template.connection) {
        console.log('Template has no connection:', template);
        return false;
      }

      console.log('Checking template:', template.name, 'with connection:', template.connection);
      
      if (direction === 'outgoing') {
        const matches = template.connection.fromConnector?.invoker?.name === 'DataGerry' &&
               template.connection.toConnector?.invoker?.name === selectedConnector.invoker.name;
        console.log('Outgoing template match:', matches, 'for template:', template.name);
        console.log('  - From:', template.connection.fromConnector?.invoker?.name, 'Expected: DataGerry');
        console.log('  - To:', template.connection.toConnector?.invoker?.name, 'Expected:', selectedConnector.invoker.name);
        return matches;
      } else if (direction === 'incoming') {
        const matches = template.connection.toConnector?.invoker?.name === 'DataGerry' &&
               template.connection.fromConnector?.invoker?.name === selectedConnector.invoker.name;
        console.log('Incoming template match:', matches, 'for template:', template.name);
        console.log('  - To:', template.connection.toConnector?.invoker?.name, 'Expected: DataGerry');
        console.log('  - From:', template.connection.fromConnector?.invoker?.name, 'Expected:', selectedConnector.invoker.name);
        return matches;
      }
      return false;
    });
    
    // Map filtered templates to the expected format for the select component
    this.filteredTemplates = filtered.map(template => ({
      label: template.name,
      value: template.templateId,
      ...template // Keep the full template object for any other needs
    }));
    
    console.log('Final filtered templates count:', this.filteredTemplates.length);
    console.log('Final filtered templates:', this.filteredTemplates.map(t => t.label));
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
          console.log('Internal connector exists, loading init data...');
          this.loadInitData();
        } else {
          console.log('Internal connector does not exist, showing configuration modal...');
          this.showInternalConnectorModal();
        }
      },
      error: (err) => {
        console.error('Error checking internal connector:', err);
        this.toast.error('Failed to check internal connector existence');
        this.isCheckingInternalConnector = false;
        this.internalConnectorExists = false;
        this.router.navigate(['/automations']);
      }
    });
  }


  private showInternalConnectorModal(): void {
    const modalRef = this.modalService.open(CoreConfirmationModalComponent, {
      centered: true,
      backdrop: 'static'
    });

    modalRef.componentInstance.title = 'Internal Connector Required';
    modalRef.componentInstance.message = 'Internal connector is not configured. Do you want to configure it now?';
    modalRef.componentInstance.confirmButtonText = 'Configure';
    modalRef.componentInstance.cancelButtonText = 'Cancel';
    modalRef.componentInstance.confirmButtonClass = 'btn-primary';

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.redirectToInternalConnectorSetup();
        }
      },
      (dismissReason) => {
        // User dismissed the modal (clicked cancel or outside)
        this.router.navigate(['/automations']);
      }
    );
  }

  private redirectToInternalConnectorSetup(): void {
    console.log('Redirecting to connector form for internal connector setup...');
    this.router.navigate(['/automations/connectors/internal'], { 
      state: { 
        connectorExists: false, // Internal connector doesn't exist, so we're creating it
        connector: {
          title: 'DataGerryInternal',
          description: 'Internal DataGerry connector for automations',
          invoker: { name: 'DataGerry' },
          sslCert: false,
          timeout: 1000
        }
      }
    });
  }

  // Action methods
  private toPayload(): any {
    const v = this.form.value;
    console.log('toPayload - Form values:', v);
    console.log('toPayload - Available connectors:', this.connectors);
    console.log('toPayload - Looking for connector with ID:', v.connector);
    
    const selectedConnector = this.connectors.find(c => c.connectorId === v.connector);
    console.log('toPayload - Found connector:', selectedConnector);
    
    if (!selectedConnector) {
      console.log('toPayload - No connector found with ID:', v.connector);
      throw new Error('Please select a connector');
    }

    // Determine which connector to use for DataGerry (internal connector)
    let datagerryConnector;
    if (this.internalConnectorDetails) {
      console.log('Using actual internal connector details:', this.internalConnectorDetails);
      datagerryConnector = {
        connectorId: this.internalConnectorDetails.connectorId,
        invoker: { name: this.internalConnectorDetails.invoker.name },
        icon: "",
        methods: this.internalConnectorDetails.methods || [],
        operators: this.internalConnectorDetails.operators || []
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
            invoker: { name: selectedConnector.invoker.name },
            icon: "",
            methods: [],
            operators: []
          },
      toConnector: v.direction === 'outgoing'
        ? {
            connectorId: selectedConnector.connectorId,
            invoker: { name: selectedConnector.invoker.name },
            icon: "",
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

    console.log('toPayload - Final connection payload:', connectionPayload);
    console.log('toPayload - Final scheduler payload:', schedulerPayload);

    return {
      connection: connectionPayload,
      scheduler: schedulerPayload
    };
  }

  save(): void {
    console.log('SAVE METHOD CALLED - Form values:', this.form.value);
    console.log('SAVE - showConnectorField:', this.showConnectorField);
    console.log('SAVE - connector value:', this.form.get('connector')?.value);
    console.log('SAVE - form valid:', this.form.valid);
    console.log('SAVE - form invalid:', this.form.invalid);
    
    if (this.form.invalid) {
      console.log('SAVE - Form is invalid, marking all as touched');
      this.form.markAllAsTouched();
      this.toast.warning('Please fill in all required fields');
      return;
    }

    // Additional validation for connector when direction is selected
    if (this.showConnectorField && !this.form.get('connector')?.value) {
      console.log('SAVE - No connector selected, showing warning');
      this.toast.warning('Please select a connector');
      return;
    }

    try {
      console.log('SAVE - Building payload...');
      const payload = this.toPayload();
      console.log('SAVE - Payload built successfully:', payload);
      
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
      console.log('SAVE - Error in toPayload:', error);
      this.toast.error((error as Error).message);
    }
  }

  cancel(): void {
    this.router.navigate(['../'], { relativeTo: this.route });
  }
}
