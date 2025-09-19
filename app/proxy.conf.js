/*
 * Proxy for NetBox API to avoid CORS in the browser.
 * This file is used by the Angular dev server (ng serve) for both development and cloud modes.
 */

const NETBOX_TOKEN = 'f1fbeace6974dd42ff90b89231e2d4e97c4f9dc2';

module.exports = {
  '/netbox': {
    target: 'https://demo.netbox.dev',
    secure: true,
    changeOrigin: true,
    logLevel: 'debug',
    pathRewrite: { '^/netbox': '' },
    onProxyReq: (proxyReq, req, res) => {
      // Remove any existing Authorization header to avoid conflicts
      proxyReq.removeHeader('Authorization');
      // Set the NetBox Authorization header
      proxyReq.setHeader('Authorization', `Token ${NETBOX_TOKEN}`);
      proxyReq.setHeader('Accept', 'image/svg+xml');
      
      // Debug logging
      console.log('Proxy modifying request to NetBox with Authorization header');
    }
  },
};
