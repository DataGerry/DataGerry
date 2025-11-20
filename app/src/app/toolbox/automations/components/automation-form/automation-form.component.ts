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
import { AuthService } from 'src/app/modules/auth/services/auth.service';

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
  connectors: Connector[] = [];
  externalConnectors: Connector[] = []; // Connectors excluding the internal one
  invokers: any[] = [];
  showConnectorField = false;
  connectorLabel = '';
  currentSourceConnectorId = '';
  currentTargetConnectorId = '';
  selectedTemplate: any = null;
  initConnection: any = null;
  currentConnection: any = null;

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
    private modalService: NgbModal,
    private authService: AuthService
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
    // Load init data and invokers in parallel
    combineLatest([
      this.svc.getInitData(),
      this.connectorsService.getInvokers()
    ]).subscribe({
      next: ([initData, invokers]) => {
        this.connectors = initData.connectors || [];
        // Filter out the internal connector from the list of selectable connectors
        this.externalConnectors = this.connectors.filter(connector => connector.title !== 'DataGerryInternal');
        this.templates = initData.templates || [];
        this.invokers = invokers || [];

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
          this.updateConnectorFieldVisibility(currentDirection);
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
      this.updateConnectorIds();
    });

    // Subscription for connector changes
    const connectorSubscription = this.form.get('connector')!.valueChanges.subscribe(() => {
      this.updateConnectorIds();
    });

    // Subscription for template selection
    const templateSubscription = this.form.get('business_template')!.valueChanges.subscribe(templateId => {
      this.updateSelectedTemplate(templateId);
    });

    // Store subscriptions
    this.formChangesSubscription = new Subscription();
    this.formChangesSubscription.add(directionSubscription);
    this.formChangesSubscription.add(connectorSubscription);
    this.formChangesSubscription.add(templateSubscription);
    
    // Set initial connector IDs
    this.updateConnectorIds();
  }


  private updateSelectedTemplate(templateId: string): void {
    if (templateId) {
      this.selectedTemplate = this.templates.find(t => t.templateId === templateId) || null;
    } else {
      this.selectedTemplate = null;
    }
  }


  private updateConnectorIds(): void {
    this.currentSourceConnectorId = this.getSourceConnectorId();
    this.currentTargetConnectorId = this.getTargetConnectorId();
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
    
    // Store the complete connection data for edit mode
    this.initConnection = automation.connection || null;

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

  // Dynamic connector ID methods
  getSourceConnectorId(): string {
    const direction = this.form.get('direction')?.value;
    const selectedConnectorId = this.form.get('connector')?.value;
    
    if (!direction || !selectedConnectorId) {
      return '';
    }

    if (direction === 'outgoing') {
      // For outgoing, source is DataGerry (internal connector)
      return this.internalConnectorDetails?.connectorId?.toString() || '';
    } else {
      // For incoming, source is the selected external connector
      return selectedConnectorId.toString();
    }
  }

  getTargetConnectorId(): string {
    const direction = this.form.get('direction')?.value;
    const selectedConnectorId = this.form.get('connector')?.value;
    
    if (!direction || !selectedConnectorId) {
      return '';
    }

    if (direction === 'outgoing') {
      // For outgoing, target is the selected external connector
      return selectedConnectorId.toString();
    } else {
      // For incoming, target is DataGerry (internal connector)
      return this.internalConnectorDetails?.connectorId?.toString() || '';
    }
  }

  // Handle connection changes from React component
  onConnectionChange(connection: any): void {
    this.currentConnection = connection;
  }

  getUserToken(): string {
    const token = this.authService.currentUserTokenValue?.token;
    return token ? `Bearer ${token}` : '';
  }

  // Check if all required data for the editor is ready
  isEditorDataReady(): boolean {
    if (this.mode === 'edit') {
      // For edit mode, we need initConnection, token, and data arrays
      return !!this.initConnection && 
             !!this.getUserToken() &&
             this.templates.length > 0 &&
             this.connectors.length > 0 &&
             this.invokers.length > 0;
    } else {
      // For create mode, we need all the data arrays and token
      return this.templates.length > 0 && 
             this.connectors.length > 0 && 
             this.invokers.length > 0 &&
             !!this.internalConnectorDetails &&
             !!this.getUserToken();
    }
  }

  // Action methods
  private toPayload(): any {
    const v = this.form.value;

    if (!this.currentConnection) {
      throw new Error('Connection data not available from OpenCelium editor');
    }

    
    // Use the complete connection from opencelium editor, but override title and description from form
    const connectionPayload = {
      ...this.currentConnection,
      title: v.name,
      description: v.description
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
