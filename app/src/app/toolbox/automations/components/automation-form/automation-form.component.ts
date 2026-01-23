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
import { AutomationsService } from '../../services/automations.service';
import { ConnectorsService } from '../../../connectors/services/connectors.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Connector } from '../../../connectors/models/connector.model';
import { AuthService } from 'src/app/modules/auth/services/auth.service';
import { InternalConnectorHelperService } from '../../../connectors/services/internal-connector-helper.service';

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
  existingCronExp: string | null = null;
  existingStatus: boolean | null = null;

  internalConnectorDetails: any = null;

  private formChangesSubscription?: Subscription;

  // Combined loading state for all operations
  public combinedLoading$ = this.loaderService.isLoading$;

  public isLoading$ = this.loaderService.isLoading$;

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private svc: AutomationsService,
    private connectorsService: ConnectorsService,
    private toast: ToastService,
    private loaderService: LoaderService,
    private authService: AuthService,
    private internalConnectorHelper: InternalConnectorHelperService
  ) {
  }


  ngOnInit(): void {
    this.mode = (this.route.snapshot.data['mode'] || 'create') as any;
    this.buildForm();

    // First check if internal connector exists
    this.internalConnectorHelper.checkInternalConnector({
      onExists: () => this.loadConnectorsAndInvokers(),
      redirectRoute: ['/automations/internal'],
      description: 'Internal DataGerry connector for automations',
      cancelRoute: ['/automations'],
      errorRoute: ['/automations']
    });

    if (this.mode === 'edit') {
      this.id = +this.route.snapshot.paramMap.get('connectorId')!;
    }
  }


  ngOnDestroy(): void {
    if (this.formChangesSubscription) {
      this.formChangesSubscription.unsubscribe();
    }
  }


  private loadConnectorsAndInvokers(): void {
    this.loaderService.show();
    
    // Load connectors and invokers in parallel
    combineLatest([
      this.connectorsService.getConnectors(),
      this.connectorsService.getInvokers()
    ])
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: ([connectors, invokers]) => {
          this.invokers = invokers || [];
          this.connectors = this.replaceConnectorInvokers(connectors || [], this.invokers);
          // Keep the internal connector in the list, but present a friendlier label
          this.externalConnectors = this.connectors.map(connector =>
            connector.title === 'DataGerryInternal'
              ? { ...connector, title: 'Built-in DataGerry' }
              : connector
          );

          // Set internal connector details from connectors list
          const internalConnector = this.connectors.find(c => c.title === 'DataGerryInternal');
          if (internalConnector) {
            this.internalConnectorDetails = internalConnector;
          } else {
            this.internalConnectorHelper.redirectToInternalConnectorSetup(
              ['/automations/internal'],
              'Internal DataGerry connector for automations'
            );
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


  private loadTemplates(): void {
    const sourceId = this.currentSourceConnectorId;
    const targetId = this.currentTargetConnectorId;

    // Only load templates if we have both connector IDs
    if (!sourceId || !targetId) {
      this.templates = [];
      return;
    }

    this.loaderService.show();
    
    this.svc.getTemplatesByConnectors(parseInt(sourceId), parseInt(targetId))
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (templates) => {
          this.templates = templates || [];
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
          this.templates = [];
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
    const previousSourceId = this.currentSourceConnectorId;
    const previousTargetId = this.currentTargetConnectorId;

    this.currentSourceConnectorId = this.getSourceConnectorId();
    this.currentTargetConnectorId = this.getTargetConnectorId();

    // Load templates if connector IDs have changed and both are available
    if ((this.currentSourceConnectorId !== previousSourceId || this.currentTargetConnectorId !== previousTargetId) &&
      this.currentSourceConnectorId && this.currentTargetConnectorId) {
      this.loadTemplates();
    } else if (!this.currentSourceConnectorId || !this.currentTargetConnectorId) {
      // Clear templates if one of the connector IDs is missing
      this.templates = [];
    }
  }

  private updateConnectorFieldVisibility(direction: string): void {
    this.showConnectorField = !!direction;

    if (direction === 'outgoing') {
      this.connectorLabel = 'Send data to Connector';
    } else if (direction === 'incoming') {
      this.connectorLabel = 'Get data from Connector';
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
      business_template: ['']
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
    this.existingCronExp = automation?.cronExp || automation?.scheduler?.cronExp || null;
    this.existingStatus = typeof automation?.status === 'boolean' ? automation.status : null;

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

  // Handle connection changes from OC Editor Component
  onConnectionChange(connection: any): void {
    this.currentConnection = connection;
  }

  // Handle save connection event from OC Editor Component
  onSaveConnection(connection: any): void {
    this.currentConnection = connection;
    this.save();
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

  // Check if required form fields are filled (only for create mode)
  areRequiredFieldsFilled(): boolean {
    if (this.mode !== 'create') {
      return true;
    }

    const name = this.form.get('name')?.value;
    const direction = this.form.get('direction')?.value;

    if (!name || !direction) {
      return false;
    }

    if (this.showConnectorField) {
      const connector = this.form.get('connector')?.value;
      if (!connector) {
        return false;
      }
    }

    return true;
  }

  // Action methods
  private toPayload(): any {
    const v = this.form.value;

    if (!this.currentConnection) {
      throw new Error('Connection data not available from OpenCelium editor');
    }


    // complete connection from opencelium editor, but override title and description from form
    const connectionPayload = {
      ...this.currentConnection,
      title: v.name,
      description: v.description
    };

    // Build scheduler payload
    const schedulerPayload: any = {
      title: v.name,
      debugMode: false,
      status: this.mode === 'edit' && this.existingStatus !== null ? (this.existingStatus ? 1 : 0) : 1 // Active
    };

    if (this.mode === 'edit' && this.existingCronExp) {
      schedulerPayload.cronExp = this.existingCronExp;
    } else if (this.mode === 'create') {
      schedulerPayload.cronExp = null;
    }

    return {
      connection: connectionPayload,
      scheduler: schedulerPayload
    };
  }

  onEditorLoad(): void {
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
        : this.svc.updateConnection(this.id!, payload);

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


    
  // Replace each connector's invoker with the full invoker object from the invokers list.
  private replaceConnectorInvokers(connectors: Connector[], invokers: any[]): Connector[] {
    const invokerMap = new Map<string, any>();
    invokers.forEach(invoker => {
      if (invoker?.name) {
        invokerMap.set(invoker.name, invoker);
      }
    });

    return connectors.map((connector: any) => {
      const invokerName = connector?.invoker?.name ?? connector?.invoker;
      if (!invokerName) {
        return connector;
      }

      const invoker = invokerMap.get(invokerName);
      if (!invoker) {
        return connector;
      }

      return { ...connector, invoker };
    });
  }

}
