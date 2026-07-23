targetScope = 'resourceGroup'

type hostedFoundryVerifierDisabledConfiguration = {
  mode: 'disabled'
}

type hostedFoundryVerifierEnabledConfiguration = {
  mode: 'enabled'
  @minLength(1)
  projectEndpoint: string
  @minLength(1)
  agentEndpoint: string
  @minLength(1)
  agentName: string
  @minLength(1)
  agentVersion: string
  @minLength(1)
  modelDeploymentName: string
}

@discriminator('mode')
type hostedFoundryVerifierConfigurationType =
  | hostedFoundryVerifierDisabledConfiguration
  | hostedFoundryVerifierEnabledConfiguration

param location string
param appServicePlanName string
param webAppName string
param pythonLinuxFxVersion string = 'PYTHON|3.12'
param hostedFoundryVerifierConfiguration hostedFoundryVerifierConfigurationType = {
  mode: 'disabled'
}
param tags object = {}

resource existingAppServicePlan 'Microsoft.Web/serverfarms@2024-04-01' existing = {
  name: appServicePlanName
}

module webApp 'modules/web-app.bicep' = {
  name: 'web-app-reconciliation'
  params: {
    location: location
    appServicePlanName: appServicePlanName
    appServicePlanResourceId: existingAppServicePlan.id
    webAppName: webAppName
    pythonLinuxFxVersion: pythonLinuxFxVersion
    hostedFoundryVerifierConfiguration: hostedFoundryVerifierConfiguration
    tags: tags
  }
}

output webAppName string = webApp.outputs.webAppName
output webAppDefaultHostname string = webApp.outputs.defaultHostname
