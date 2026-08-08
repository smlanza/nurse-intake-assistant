targetScope = 'resourceGroup'

@description('Name of the existing repository-owned Key Vault.')
param keyVaultName string

@description('Existing Web App system-assigned managed-identity principal ID.')
@minLength(1)
param webAppPrincipalId string

var keyVaultSecretsUserRoleDefinitionGuid = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  keyVaultSecretsUserRoleDefinitionGuid
)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultSecretsUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    keyVault.id,
    webAppPrincipalId,
    keyVaultSecretsUserRoleDefinitionId
  )
  scope: keyVault
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}
