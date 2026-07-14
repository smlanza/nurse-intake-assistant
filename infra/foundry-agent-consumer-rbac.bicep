targetScope = 'resourceGroup'

@description('Name of the existing Linux Web App with a system-assigned identity.')
param webAppName string

@description('Name of the existing Microsoft Foundry account.')
param foundryAccountName string

@description('Name of the existing Microsoft Foundry project.')
param foundryProjectName string

resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
}

module foundryAgentConsumerRbac 'modules/foundry-agent-consumer-rbac.bicep' = {
  name: 'foundry-agent-consumer-rbac'
  params: {
    foundryAccountName: foundryAccountName
    foundryProjectName: foundryProjectName
    webAppPrincipalId: webApp.identity.principalId
  }
}

output assignmentRequested bool = true
output webAppName string = webAppName
output foundryProjectName string = foundryProjectName
output roleLabel string = 'Foundry Agent Consumer'
output scopeType string = 'project'
