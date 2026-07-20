targetScope = 'resourceGroup'

@description('The explicit Foundry account name after repository-owned Azure naming validation.')
@minLength(2)
@maxLength(64)
param validatedFoundryAccountName string

output validated bool = !empty(validatedFoundryAccountName)
