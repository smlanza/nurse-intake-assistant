targetScope = 'resourceGroup'

@description('Name of the existing Linux Web App with a system-assigned identity.')
param webAppName string

@description('Name of the existing repository-owned Key Vault.')
param keyVaultName string

resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

module keyVaultSecretsUserRbac 'modules/key-vault-secrets-user-rbac.bicep' = {
  name: '${deployment().name}-assignment'
  params: {
    keyVaultName: keyVault.name
    webAppPrincipalId: webApp.identity.principalId
  }
}
