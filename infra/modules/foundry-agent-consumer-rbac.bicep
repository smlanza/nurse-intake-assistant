targetScope = 'resourceGroup'

param foundryAccountName string
param foundryProjectName string
@minLength(1)
param webAppPrincipalId string
@minLength(1)
param approvedFoundryProjectResourceId string
@minLength(36)
param approvedRoleAssignmentName string

var foundryAgentConsumerRoleDefinitionGuid = 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'
var foundryAgentConsumerRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  foundryAgentConsumerRoleDefinitionGuid
)
var computedRoleAssignmentName = guid(
  foundryProject.id,
  webAppPrincipalId,
  foundryAgentConsumerRoleDefinitionId
)

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}

resource foundryAgentConsumerRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: foundryProject.id == approvedFoundryProjectResourceId && computedRoleAssignmentName == approvedRoleAssignmentName ? approvedRoleAssignmentName : ''
  scope: foundryProject
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: foundryAgentConsumerRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}
