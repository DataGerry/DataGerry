export interface Connector {
    connectorId?: number;              // present for edit/view
    title: string;
    description?: string;
    invoker: { name: string };
    sslCert: boolean;
    timeout: number;
    requestData: Record<string, any>;  // dynamic credentials per invoker
  }
  