export interface Connector {
    connector_id?: number;
    name: string;
    type: string;
    configuration: any;
    status?: string;
    created_at?: string;
    updated_at?: string;
}

export interface ConnectorTestResult {
    success: boolean;
    message: string;
    details?: any;
}
