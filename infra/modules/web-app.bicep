targetScope = 'resourceGroup'

param location string
param appServicePlanName string
param webAppName string
param appServicePlanSkuName string = 'B1'
param pythonLinuxFxVersion string = 'PYTHON|3.12'
param tags object = {}

var startupCommand = 'python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000'

resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: appServicePlanSkuName
  }
  properties: {
    reserved: true
  }
  tags: tags
}

resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: pythonLinuxFxVersion
      appCommandLine: startupCommand
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      healthCheckPath: '/health'
      appSettings: [
        {
          name: 'APP_MODE'
          value: 'mock'
        }
        {
          name: 'AI_PROVIDER'
          value: 'mock'
        }
        {
          name: 'AGENT_PROVIDER'
          value: 'mock'
        }
        {
          name: 'SPEECH_PROVIDER'
          value: 'mock'
        }
        {
          name: 'EMAIL_PROVIDER'
          value: 'mock'
        }
        {
          name: 'SMS_PROVIDER'
          value: 'mock'
        }
        {
          name: 'DEMO_SUPPRESS_NOTIFICATIONS'
          value: 'true'
        }
      ]
    }
  }
  tags: tags
}

output webAppName string = webApp.name
output defaultHostname string = webApp.properties.defaultHostName
output systemAssignedIdentityPrincipalId string = webApp.identity.principalId
