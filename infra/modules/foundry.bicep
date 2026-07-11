targetScope = 'resourceGroup'

param location string
param projectName string
param environmentName string
param foundryProjectName string
param foundryProjectDisplayName string
param foundryProjectDescription string
param modelDeploymentName string
param modelName string
param modelVersion string
param modelPublisherFormat string
param modelSkuName string
param modelCapacity int
param tags object = {}

var suffix = uniqueString(resourceGroup().id, projectName, environmentName)
var foundryResourceName = take(toLower('${projectName}-${environmentName}-ai-${suffix}'), 64)

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryResourceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryResourceName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: foundryProjectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: foundryProjectDisplayName
    description: foundryProjectDescription
  }
  tags: tags
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundryAccount
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: modelPublisherFormat
      name: modelName
      version: modelVersion
    }
  }
}

output foundryResourceName string = foundryAccount.name
output foundryProjectName string = foundryProject.name
output foundryProjectEndpoint string = 'https://${foundryAccount.name}.services.ai.azure.com/api/projects/${foundryProject.name}'
output modelDeploymentName string = modelDeployment.name
