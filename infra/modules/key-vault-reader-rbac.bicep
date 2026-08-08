targetScope = 'resourceGroup'

@description('Name of the existing repository-owned Key Vault.')
param keyVaultName string

@description('Privately resolved current Azure operator principal ID.')
@minLength(1)
param operatorPrincipalId string

var keyVaultReaderRoleDefinitionGuid = '21090545-7ca7-4776-b22c-e363652d74d2'
var keyVaultReaderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  keyVaultReaderRoleDefinitionGuid
)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    keyVault.id,
    operatorPrincipalId,
    keyVaultReaderRoleDefinitionId
  )
  scope: keyVault
  properties: {
    principalId: operatorPrincipalId
    roleDefinitionId: keyVaultReaderRoleDefinitionId
    principalType: 'User'
  }
}
