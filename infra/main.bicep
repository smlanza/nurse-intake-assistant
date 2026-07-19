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

@description('Short environment name, such as dev, test, or demo.')
@minLength(3)
@maxLength(10)
param environmentName string = 'dev'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short project name used in resource names.')
@minLength(3)
@maxLength(20)
param projectName string = 'nurse-intake'

@description('Cosmos SQL database name.')
param cosmosDatabaseName string = 'nurse-intake'

@description('Cosmos SQL container name for case documents.')
param cosmosContainerName string = 'cases'

@description('Deploy Microsoft Foundry resources with the full application stack.')
param deployFoundry bool = false

@description('Deploy an Azure Linux Web App for the Nurse Intake Assistant.')
param deployApp bool = false

@description('Optional App Service plan name. A deterministic name is used when empty.')
param appServicePlanName string = ''

@description('Optional Web App name. A deterministic name is used when empty.')
param webAppName string = ''

@description('App Service plan SKU for optional application hosting.')
param appServicePlanSkuName string = 'B1'

@description('Linux runtime stack for optional Python application hosting.')
param pythonLinuxFxVersion string = 'PYTHON|3.12'

@description('Optional complete hosted metadata-verifier configuration; disabled for ordinary Web App deployment.')
param hostedFoundryVerifierConfiguration hostedFoundryVerifierConfigurationType = {
  mode: 'disabled'
}

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

param foundryProjectName string = 'nurse-intake-project'
param foundryProjectDisplayName string = 'Nurse Intake Assistant'
param foundryProjectDescription string = 'Microsoft Foundry project for the Nurse Intake Assistant.'
param modelDeploymentName string = 'configure-when-foundry-enabled'
param modelName string = 'configure-when-foundry-enabled'
param modelVersion string = 'configure-when-foundry-enabled'
param modelPublisherFormat string = 'OpenAI'
param modelSkuName string = 'GlobalStandard'
param modelCapacity int = 1
param foundryTags object = {}

var suffix = uniqueString(resourceGroup().id, projectName, environmentName)
var cosmosAccountName = toLower('${projectName}-${environmentName}-${suffix}')
var storageAccountName = 'st${suffix}'
var logAnalyticsWorkspaceName = '${projectName}-${environmentName}-logs-${suffix}'
var appInsightsName = '${projectName}-${environmentName}-appi-${suffix}'
var resolvedAppServicePlanName = empty(appServicePlanName) ? take(toLower('${projectName}-${environmentName}-plan-${suffix}'), 40) : appServicePlanName
var resolvedWebAppName = empty(webAppName) ? take(toLower('${projectName}-${environmentName}-web-${suffix}'), 60) : webAppName

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: cosmosDatabaseName
  properties: {
    resource: {
      id: cosmosDatabaseName
    }
  }
}

resource casesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: cosmosContainerName
  properties: {
    resource: {
      id: cosmosContainerName
      partitionKey: {
        paths: [
          '/createdDate'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

module webApp 'modules/web-app.bicep' = if (deployApp) {
  name: 'web-app'
  params: {
    location: location
    appServicePlanName: resolvedAppServicePlanName
    webAppName: resolvedWebAppName
    appServicePlanSkuName: appServicePlanSkuName
    pythonLinuxFxVersion: pythonLinuxFxVersion
    hostedFoundryVerifierConfiguration: validatedHostedFoundryVerifierConfiguration
  }
}

module foundry 'modules/foundry.bicep' = if (deployFoundry) {
  name: 'foundry'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    foundryProjectName: foundryProjectName
    foundryProjectDisplayName: foundryProjectDisplayName
    foundryProjectDescription: foundryProjectDescription
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelPublisherFormat: modelPublisherFormat
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    tags: foundryTags
  }
}

output cosmosAccountName string = cosmosAccount.name
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = cosmosDatabaseName
output containerName string = cosmosContainerName
output applicationInsightsName string = applicationInsights.name
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString
output appHostingRequested bool = deployApp
output webAppName string = deployApp ? webApp!.outputs.webAppName : ''
output webAppDefaultHostname string = deployApp ? webApp!.outputs.defaultHostname : ''
output foundryResourceName string = deployFoundry ? foundry!.outputs.foundryResourceName : ''
output foundryProjectName string = deployFoundry ? foundry!.outputs.foundryProjectName : ''
output foundryProjectEndpoint string = deployFoundry ? foundry!.outputs.foundryProjectEndpoint : ''
output modelDeploymentName string = deployFoundry ? foundry!.outputs.modelDeploymentName : ''
