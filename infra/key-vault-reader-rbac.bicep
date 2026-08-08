targetScope = 'resourceGroup'

@description('Name of the existing repository-owned Key Vault.')
param keyVaultName string

@description('Privately resolved current Azure operator principal ID.')
@minLength(1)
param operatorPrincipalId string

module keyVaultReaderRbac 'modules/key-vault-reader-rbac.bicep' = {
  name: '${deployment().name}-assignment'
  params: {
    keyVaultName: keyVaultName
    operatorPrincipalId: operatorPrincipalId
  }
}
