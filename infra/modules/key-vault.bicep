targetScope = 'resourceGroup'

@description('Azure region for the Key Vault.')
param location string

@description('Repository-owned deterministic Key Vault name.')
@minLength(3)
@maxLength(24)
param keyVaultName string

param tags object = {}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
  }
  tags: tags
}

output keyVaultName string = keyVault.name
