targetScope = 'resourceGroup'

@description('Name of the existing Linux Web App with a system-assigned identity.')
param webAppName string

@description('Name of the existing Microsoft Foundry account.')
param foundryAccountName string

@description('Name of the existing Microsoft Foundry project.')
param foundryProjectName string

@description('Exact Web App system-assigned principal approved from fresh read-only evidence.')
param approvedWebAppPrincipalId string

@description('Exact Foundry project resource ID approved from fresh read-only evidence.')
param approvedFoundryProjectResourceId string

@description('Deterministic role-assignment name approved from fresh read-only evidence.')
param approvedRoleAssignmentName string

resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}

module foundryAgentConsumerRbac 'modules/foundry-agent-consumer-rbac.bicep' = {
  name: '${deployment().name}-assignment'
  params: {
    foundryAccountName: foundryAccountName
    foundryProjectName: foundryProjectName
    webAppPrincipalId: webApp.identity.principalId == approvedWebAppPrincipalId ? approvedWebAppPrincipalId : ''
    approvedFoundryProjectResourceId: foundryProject.id == approvedFoundryProjectResourceId ? approvedFoundryProjectResourceId : ''
    approvedRoleAssignmentName: approvedRoleAssignmentName
  }
}

output assignmentRequested bool = true
output webAppName string = webAppName
output foundryProjectName string = foundryProjectName
output roleLabel string = 'Foundry Agent Consumer'
output scopeType string = 'project'
