![Image](app/src/assets/img/datagerry_logo.svg)
DataGerry is an OpenSource CMDB & Asset Management Tool, which completely leaves the definition of a data model to the user.

Key Functions:
* Define your own object types (e.g. router, server, location) in a simple webfrontend
* Add objects manually or import them from a CSV, Excel, XML, JSON file
* Define automated exports to external systems (e.g. Monitoring Systems, Config Management, Backup, Ticket Systems, DNS, ...)
* Use one of our APIs to integrate your systems
* **AI Assistant** - Get intelligent help and suggestions using Google's Generative AI
* ...and many many more features on the roadmap - we just started

Key Facts:
* Define your own data model
* Automate your IT with exporting assets to external systems
* OpenSource (AGPLv3)
* AI-powered assistance for enhanced productivity

See [DataGerry website](https://www.datagerry.com) for more details!


## Getting Started
|Useful Links |
|-----|
|[Getting Started](https://www.datagerry.com) |
|[Documentation](https://docs.datagerry.com)|
|[Issue Tracker](https://issues.datagerry.com)|
|[Community Support](https://community.datagerry.com)|


## AI Assistant Setup

DataGerry includes an AI Assistant feature that provides intelligent help and suggestions. To use this feature, you need to configure a Google API key.

### Step 1: Obtain a Google API Key

1. Go to [Google AI Studio API Keys](https://aistudio.google.com/app/api-keys)
2. Sign in with your Google account if prompted
3. Click "Create API Key" to generate a new API key
4. Select the project you want to use or create a new one
5. Copy the generated API key

### Step 2: Configure the API Key

1. Navigate to your DataGerry installation directory
2. Locate or create the `.env` file in the root directory
3. Add the following line to the `.env` file:
   ```
   GOOGLE_API_KEY=your_actual_api_key_here
   ```
   Replace `your_actual_api_key_here` with the API key you obtained in Step 1.

### Step 3: Restart the Backend

After setting the API key, restart your DataGerry backend to apply the changes.


### Troubleshooting

If the AI Assistant isn't working:
- Verify the API key is correctly set in the `.env` file
- Check that the Generative Language API is enabled in Google Cloud Console
- Ensure there are no typos in the API key
- Restart the backend after making changes

## Continous Integration
| Service        | development      | master       |
| -------------- |----------------- | ------------ |
| Github Actions | ![Continous Integration](https://github.com/DATAGerry/DATAGerry/workflows/Continous%20Integration/badge.svg?branch=development) | ![Continous Integration](https://github.com/DATAGerry/DATAGerry/workflows/Continous%20Integration/badge.svg?branch=master) |
