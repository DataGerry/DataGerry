export const environment = {
  production: true,
  cloudMode: false,
  preCloudMode: false,
  featurePreviewMode: false,
  protocol: window["env"]["apiProtocol"] || 'http',
  apiUrl: window["env"]["apiUrl"] || 'localhost', // API URL
  apiPort: window["env"]["apiPort"] ||4000
}; 
