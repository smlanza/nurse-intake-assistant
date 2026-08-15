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

type appServiceAuthenticationDisabledConfiguration = {
  mode: 'disabled'
}

type appServiceAuthenticationEnabledConfiguration = {
  mode: 'enabled'
  @minLength(36)
  @maxLength(36)
  clientId: string
  @minLength(36)
  @maxLength(36)
  tenantId: string
}

@discriminator('mode')
type appServiceAuthenticationConfigurationType =
  | appServiceAuthenticationDisabledConfiguration
  | appServiceAuthenticationEnabledConfiguration

param location string
param appServicePlanName string
param webAppName string
@description('Deploy the App Service plan for initial creation. Set false to reconcile an existing Web App against the named existing plan.')
param deployAppServicePlan bool = true
param appServicePlanSkuName string = 'B1'
param pythonLinuxFxVersion string = 'PYTHON|3.12'
param hostedFoundryVerifierConfiguration hostedFoundryVerifierConfigurationType = {
  mode: 'disabled'
}
@description('Optional App Service Authentication v2 configuration. Disabled by default and requires an existing Entra application when enabled.')
param appServiceAuthenticationConfiguration appServiceAuthenticationConfigurationType = {
  mode: 'disabled'
}
param tags object = {}

var startupCommand = 'python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000'
var validatedHostedFoundryVerifierConfiguration = hostedFoundryVerifierConfiguration.mode == 'enabled' ? {
  mode: 'enabled'
  projectEndpoint: hostedFoundryVerifierConfiguration.projectEndpoint == trim(hostedFoundryVerifierConfiguration.projectEndpoint) ? hostedFoundryVerifierConfiguration.projectEndpoint : ''
  agentEndpoint: hostedFoundryVerifierConfiguration.agentEndpoint == trim(hostedFoundryVerifierConfiguration.agentEndpoint) ? hostedFoundryVerifierConfiguration.agentEndpoint : ''
  agentName: hostedFoundryVerifierConfiguration.agentName == trim(hostedFoundryVerifierConfiguration.agentName) ? hostedFoundryVerifierConfiguration.agentName : ''
  agentVersion: hostedFoundryVerifierConfiguration.agentVersion == trim(hostedFoundryVerifierConfiguration.agentVersion) ? hostedFoundryVerifierConfiguration.agentVersion : ''
  modelDeploymentName: hostedFoundryVerifierConfiguration.modelDeploymentName == trim(hostedFoundryVerifierConfiguration.modelDeploymentName) ? hostedFoundryVerifierConfiguration.modelDeploymentName : ''
} : {
  mode: 'disabled'
}
var hostedFoundryVerifierAppSettings = validatedHostedFoundryVerifierConfiguration.mode == 'enabled' ? [
  {
    name: 'AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT'
    value: validatedHostedFoundryVerifierConfiguration.projectEndpoint
  }
  {
    name: 'AZURE_AI_FOUNDRY_AGENT_ENDPOINT'
    value: validatedHostedFoundryVerifierConfiguration.agentEndpoint
  }
  {
    name: 'AZURE_AI_FOUNDRY_AGENT_NAME'
    value: validatedHostedFoundryVerifierConfiguration.agentName
  }
  {
    name: 'AZURE_AI_FOUNDRY_AGENT_VERSION'
    value: validatedHostedFoundryVerifierConfiguration.agentVersion
  }
  {
    name: 'AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME'
    value: validatedHostedFoundryVerifierConfiguration.modelDeploymentName
  }
] : []
var validatedAppServiceAuthenticationConfiguration = appServiceAuthenticationConfiguration.mode == 'enabled' ? {
  mode: 'enabled'
  clientId: appServiceAuthenticationConfiguration.clientId == trim(appServiceAuthenticationConfiguration.clientId) ? appServiceAuthenticationConfiguration.clientId : ''
  tenantId: appServiceAuthenticationConfiguration.tenantId == trim(appServiceAuthenticationConfiguration.tenantId) ? appServiceAuthenticationConfiguration.tenantId : ''
} : {
  mode: 'disabled'
}

module hostedFoundryVerifierConfigValidation 'hosted-foundry-verifier-config-validation.bicep' = if (hostedFoundryVerifierConfiguration.mode == 'enabled') {
  name: 'hosted-foundry-verifier-validation'
  params: {
    hostedFoundryVerifierConfiguration: validatedHostedFoundryVerifierConfiguration
  }
}

module appServiceAuthenticationConfigValidation 'app-service-authentication-config-validation.bicep' = if (appServiceAuthenticationConfiguration.mode == 'enabled') {
  name: 'app-service-authentication-validation'
  params: {
    appServiceAuthenticationConfiguration: validatedAppServiceAuthenticationConfiguration
  }
}

resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = if (deployAppServicePlan) {
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

var resolvedAppServicePlanResourceId = deployAppServicePlan
  ? appServicePlan!.id
  : resourceId('Microsoft.Web/serverfarms', appServicePlanName)

resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: resolvedAppServicePlanResourceId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: pythonLinuxFxVersion
      appCommandLine: startupCommand
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      healthCheckPath: '/health'
      appSettings: concat([
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
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'WEBSITE_SKIP_RUNNING_KUDUAGENT'
          value: 'false'
        }
      ], hostedFoundryVerifierAppSettings)
    }
  }
  tags: tags
  dependsOn: [
    hostedFoundryVerifierConfigValidation
  ]
}

module webAppAuthentication 'web-app-authentication.bicep' = if (validatedAppServiceAuthenticationConfiguration.mode == 'enabled') {
  name: 'web-app-authentication'
  params: {
    webAppName: webApp.name
    entraClientId: validatedAppServiceAuthenticationConfiguration.clientId
    entraTenantId: validatedAppServiceAuthenticationConfiguration.tenantId
  }
  dependsOn: [
    appServiceAuthenticationConfigValidation
  ]
}

output webAppName string = webApp.name
output defaultHostname string = webApp.properties.defaultHostName
output systemAssignedIdentityPrincipalId string = webApp.identity.principalId
