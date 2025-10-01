import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { ConnectorsService } from '../../services/connectors.service';
import { Connector } from '../../models/connector.model';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Component({
  selector: 'app-connectors-list',
  templateUrl: './connectors-list.component.html',
  styleUrls: ['./connectors-list.component.scss'],
  standalone: false
})
export class ConnectorsListComponent implements OnInit {
  rows: Connector[] = [];
  loading = false;
  columns: any[];

  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

  constructor(
    private svc: ConnectorsService,
    private router: Router,
    private toast: ToastService
  ) {}

  ngOnInit(): void {
    this.columns = [
      { display: 'Public ID', name: 'connectorId', data: 'connectorId', sortable: true, style: { width: '100px', 'text-align': 'center' } },
      { display: 'Label', name: 'title', data: 'title', sortable: true },
      { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '100px', 'text-align': 'center' } }
    ];
    this.fetch();
  }

  fetch(): void {
    this.loading = true;
    this.svc.getConnectors().subscribe({
      next: (res) => { this.rows = res ?? []; this.loading = false; },
      error: () => { this.loading = false; this.toast.error('Failed to load connectors'); }
    });
  }

  add(): void { this.router.navigate(['/connectors/add']); }
  edit(row: Connector): void { this.router.navigate(['/connectors/edit', row.connectorId]); }

  delete(row: Connector): void {
    if (!confirm(`Delete connector "${row.title}"?`)) return;
    this.svc.deleteConnector(row.connectorId!).subscribe({
      next: () => { this.toast.success('Connector deleted'); this.fetch(); },
      error: () => this.toast.error('Delete failed')
    });
  }
  
}