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
    this.checkInternalConnector();

    if (this.mode === 'edit') {
      this.id = +this.route.snapshot.paramMap.get('connectorId')!;
    }
  }

  ngOnDestroy(): void {
    if (this.formChangesSubscription) {
      this.formChangesSubscription.unsubscribe();
    }
  }

  private loadInitData(): void {
    this.svc.getInitData().subscribe({
      next: (initData) => {
        this.connectors = initData.connectors || [];
        // Filter out the internal connector from the list of selectable connectors
        this.externalConnectors = this.connectors.filter(connector => connector.title !== 'DataGerryInternal');
        this.templates = initData.templates || [];
        this.filteredTemplates = [...this.templates];

        
        // Set internal connector details from init data
        const internalConnector = this.connectors.find(c => c.title === 'DataGerryInternal');
        if (internalConnector) {
          this.internalConnectorDetails = internalConnector;
        } else {
          this.redirectToInternalConnectorSetup();
          return;
        }
        
        // Set up form changes after data is loaded
        this.setupFormChanges();
        
        // Handle edit mode after data is loaded
        if (this.mode === 'edit') {
          // Check if automation was passed via state 
          const automation = history.state?.automation;
          if (automation) {
            this.patchForEdit(automation);
          } else {
            this.toast.warning('Automation data not found. Please try editing again.');
          }
        } else {
          // For create mode, trigger initial update based on current form values
          const currentDirection = this.form.get('direction')?.value;
          const currentConnector = this.form.get('connector')?.value;

          
          this.updateConnectorFieldVisibility(currentDirection);

          this.filterTemplates(currentDirection, currentConnector);
        }
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.router.navigate(['/automations']);
      }
    });
  }

  private setupFormChanges(): void {
    
    // Separate subscription for direction changes to ensure label updates
    const directionSubscription = this.form.get('direction')!.valueChanges.subscribe(direction => {
      this.updateConnectorFieldVisibility(direction);
    });

    // CombineLatest for template filtering
    const combineSubscription = combineLatest([
      this.form.get('direction')!.valueChanges,
      this.form.get('connector')!.valueChanges
    ]).subscribe(([direction, connector]) => {
      this.filterTemplates(direction, connector);
    });

    // Store both subscriptions
    this.formChangesSubscription = new Subscription();
    this.formChangesSubscription.add(directionSubscription);
    this.formChangesSubscription.add(combineSubscription);
    
  }

  private updateConnectorFieldVisibility(direction: string): void {
    this.showConnectorField = !!direction;
    
    if (direction === 'outgoing') {
      this.connectorLabel = 'To Connector';
    } else if (direction === 'incoming') {
      this.connectorLabel = 'From Connector';
    } else {
      this.connectorLabel = '';
    }
    
    // Reset connector selection when direction changes to prevent auto-selection issues
    this.form.patchValue({ connector: '' });
  }

  private filterTemplates(direction: string, connectorId: number): void {
    
    // If no direction or no connector, show empty list (waiting for user selection)
    if (!direction || !connectorId) {
      this.filteredTemplates = [];
      return;
    }

    const selectedConnector = this.connectors.find(c => c.connectorId === connectorId);
    
    if (!selectedConnector) {
      this.filteredTemplates = [];
      return;
    }

    
    const filtered = this.templates.filter(template => {
      if (!template.connection) {
        return false;
      }

      
      if (direction === 'outgoing') {
        const matches = template.connection.fromConnector?.invoker?.name === 'DataGerry' &&
               template.connection.toConnector?.invoker?.name === selectedConnector.invoker.name;

        return matches;
      } else if (direction === 'incoming') {
        const matches = template.connection.toConnector?.invoker?.name === 'DataGerry' &&
               template.connection.fromConnector?.invoker?.name === selectedConnector.invoker.name;
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
    

  }
  

  private buildForm(): void {
    this.form = this.fb.group({
      name: ['', Validators.required],
      description: [''],
      direction: ['incoming', Validators.required], // Set incoming as default
      connector: [''],
      business_template: ['', Validators.required]
    });
  }

  private patchForEdit(automation: any): void {
    
    // Patch basic fields - use root level fields from automation
    this.form.patchValue({
      name: automation.title || automation.connection?.title || '', // Use title from root or connection
      description: automation.description || automation.connection?.description || '',
      direction: automation.direction,
      business_template: '' // Set to empty since it's not in automation data, will be selected by user
    });

    this.id = automation.schedulerId;

    // Determine and set the connector value based on direction and connection data
    let connectorId: number | null = null;
    
    if (automation.direction === 'outgoing') {
      // For outgoing, connector is the toConnector
      connectorId = automation.connection?.toConnector?.connectorId;
    } else if (automation.direction === 'incoming') {
      // For incoming, connector is the fromConnector  
      connectorId = automation.connection?.fromConnector?.connectorId;
    }

    // Only set connector if we found a valid connector ID and it's not the internal connector
    if (connectorId) {
      const selectedConnector = this.connectors.find(c => c.connectorId === connectorId);
      if (selectedConnector && selectedConnector.title !== 'DataGerryInternal') {
        this.form.patchValue({ connector: connectorId });
        
        // Trigger template filtering with the selected connector
        setTimeout(() => {
          this.filterTemplates(automation.direction, connectorId);
        }, 100);
      } else {
      }
    } else {
    }

  }

  // Internal connector methods
  private checkInternalConnector(): void {
    this.isCheckingInternalConnector = true;

    this.connectorsService.checkConnectorExists('DataGerryInternal').subscribe({
      next: (exists) => {
        this.internalConnectorExists = exists;
        this.isCheckingInternalConnector = false;
        
        if (exists) {
          this.loadInitData();
        } else {
          this.showInternalConnectorModal();
        }
      },
      error: (error) => {
        this.toast.error(error?.error?.message);
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

    
    const selectedConnector = this.connectors.find(c => c.connectorId === v.connector);
    
    if (!selectedConnector) {
      throw new Error('Please select a connector');
    }

    // Determine which connector to use for DataGerry (internal connector)
    let datagerryConnector;
    if (this.internalConnectorDetails) {
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
    this.router.navigate(['/automations'], { relativeTo: this.route });
  }
}
