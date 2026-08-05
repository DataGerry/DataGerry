import * as ReactDOM from 'react-dom';
import React from 'react';
import {
  Component,
  inject,
  ElementRef,
  Input,
  Output,
  EventEmitter,
  AfterViewInit,
  OnChanges,
  OnDestroy,
  SimpleChanges,
} from '@angular/core';
import { ConnectionService } from 'src/app/modules/connect/services/connection.service';
import { environment } from 'src/environments/environment';


@Component({
  selector: 'opencelium-editor',
  standalone: false,
  template: `<div></div>`,
})
export class OpenCeliumEditorComponent
  implements AfterViewInit, OnChanges, OnDestroy {
  @Input() token = '';
  @Input() sourceConnectorId = '';
  @Input() targetConnectorId = '';
  @Input() templates: any[] = [];
  @Input() template: any = null;
  @Input() connectors: any[] = [];
  @Input() invokers: any[] = [];
  @Input() initConnection: any = null;
  @Output() connectionChange = new EventEmitter<any>();
  @Output() saveConnection = new EventEmitter<any>();
  @Output() editorLoad = new EventEmitter<void>();

  private container?: HTMLElement;
  private ConnectionEditor?: any;

  private static readonly styleIdPrefix = 'opencelium-editor-style';
  private static readonly styleIdSuffixes = [
    'connection-editor-css',
    'fonts-css',
    'graphiql-module-css'
  ];
  private static readonly styleIds = OpenCeliumEditorComponent.styleIdSuffixes.map(
    suffix => `${OpenCeliumEditorComponent.styleIdPrefix}-${suffix}`
  );

  
  private readonly host = inject(ElementRef);
  private readonly connectionService = inject(ConnectionService);


  async ngAfterViewInit() {
    this.container = this.host.nativeElement.querySelector('div');
    this.integrateStyles();
    const module = await import('../../../../assets/connection_editor/connection-editor.js');
    this.ConnectionEditor = (module as any).default ?? module;
    this.render();
  }


  /** Re-render when inputs change */
  ngOnChanges(changes: SimpleChanges) {
    if (this.container) {
      ReactDOM.unmountComponentAtNode(this.container);
    }

    if (this.container && this.ConnectionEditor) {
      this.render();
    }
  }


  /** Unmount React when Angular destroys the component */
  ngOnDestroy() {
    if (this.container) {
      ReactDOM.unmountComponentAtNode(this.container);
    }
    this.removeStyles();
    document
      .querySelectorAll('.react-scope, #oc_xml_modal, #oc_generator_modal')
      .forEach(el => el.remove());
  }


  /** Mount or re-render the React component */
  private render() {
    if (!this.container || !this.ConnectionEditor) {
      return;
    }

    // Always send these properties
    const props: any = {
      token: this.token,
      templates: this.templates,
      template: this.template,
      initConnection: this.initConnection,
      connectors: this.connectors,
      invokers: this.invokers,
      baseUrl: this.getBaseUrl(),
      onChange: (connection: any) => {
        this.connectionChange.emit(connection);
      },
      saveConnection: async (connection: any) => {
        this.saveConnection.emit(connection);
      },
      onLoad: () => { this.editorLoad.emit(); }
    };

    // Only send connector IDs in create mode
    if (!this.initConnection) {
      props.sourceConnectorId = this.sourceConnectorId;
      props.targetConnectorId = this.targetConnectorId;
    }

    ReactDOM.render(
      React.createElement(this.ConnectionEditor, props),
      this.container
    );

  }


  private getBaseUrl(): string {
    if (environment.cloudMode) {
      const host = environment.apiUrl.replace(/^https?:\/\//, '');
      const port =
        environment.protocol === 'https' ? 443 : environment.apiPort;
      const base = port
        ? `${environment.protocol}://${host}:${port}`
        : `${environment.protocol}://${host}`;
      return `${base}/rest/open_celium/`;
    }

    return `${this.connectionService.getApiBaseUrl()}/rest/open_celium/`;
  }


  private integrateStyles() {
    const stylePaths = [
      'assets/connection_editor/connection-editor.css',
      'assets/fonts/fonts.css',
      'assets/connection_editor/styles/graphiql.module.css'
    ];

    // Load each file once
    stylePaths.forEach((path, index) => {
      const id = OpenCeliumEditorComponent.styleIds[index];

      if (!document.getElementById(id)) {
        const link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = path;

        document.head.appendChild(link);
      }
    });
  }


  private removeStyles() {
    OpenCeliumEditorComponent.styleIds.forEach(id => {
      const link = document.getElementById(id);
      if (link) {
        link.remove();
      }
    });
  }
}
