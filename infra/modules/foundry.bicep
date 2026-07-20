targetScope = 'resourceGroup'

param location string
param projectName string
param environmentName string
@description('Optional explicit Foundry account name. Empty preserves the deterministic repository naming contract.')
@maxLength(64)
param foundryAccountName string = ''
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
var foundryResourceName = empty(foundryAccountName) ? take(toLower('${projectName}-${environmentName}-ai-${suffix}'), 64) : foundryAccountName
var foundryAccountNameWithoutA = replace(toLower(foundryAccountName), 'a', '')
var foundryAccountNameWithoutB = replace(foundryAccountNameWithoutA, 'b', '')
var foundryAccountNameWithoutC = replace(foundryAccountNameWithoutB, 'c', '')
var foundryAccountNameWithoutD = replace(foundryAccountNameWithoutC, 'd', '')
var foundryAccountNameWithoutE = replace(foundryAccountNameWithoutD, 'e', '')
var foundryAccountNameWithoutF = replace(foundryAccountNameWithoutE, 'f', '')
var foundryAccountNameWithoutG = replace(foundryAccountNameWithoutF, 'g', '')
var foundryAccountNameWithoutH = replace(foundryAccountNameWithoutG, 'h', '')
var foundryAccountNameWithoutI = replace(foundryAccountNameWithoutH, 'i', '')
var foundryAccountNameWithoutJ = replace(foundryAccountNameWithoutI, 'j', '')
var foundryAccountNameWithoutK = replace(foundryAccountNameWithoutJ, 'k', '')
var foundryAccountNameWithoutL = replace(foundryAccountNameWithoutK, 'l', '')
var foundryAccountNameWithoutM = replace(foundryAccountNameWithoutL, 'm', '')
var foundryAccountNameWithoutN = replace(foundryAccountNameWithoutM, 'n', '')
var foundryAccountNameWithoutO = replace(foundryAccountNameWithoutN, 'o', '')
var foundryAccountNameWithoutP = replace(foundryAccountNameWithoutO, 'p', '')
var foundryAccountNameWithoutQ = replace(foundryAccountNameWithoutP, 'q', '')
var foundryAccountNameWithoutR = replace(foundryAccountNameWithoutQ, 'r', '')
var foundryAccountNameWithoutS = replace(foundryAccountNameWithoutR, 's', '')
var foundryAccountNameWithoutT = replace(foundryAccountNameWithoutS, 't', '')
var foundryAccountNameWithoutU = replace(foundryAccountNameWithoutT, 'u', '')
var foundryAccountNameWithoutV = replace(foundryAccountNameWithoutU, 'v', '')
var foundryAccountNameWithoutW = replace(foundryAccountNameWithoutV, 'w', '')
var foundryAccountNameWithoutX = replace(foundryAccountNameWithoutW, 'x', '')
var foundryAccountNameWithoutY = replace(foundryAccountNameWithoutX, 'y', '')
var foundryAccountNameWithoutZ = replace(foundryAccountNameWithoutY, 'z', '')
var foundryAccountNameWithout0 = replace(foundryAccountNameWithoutZ, '0', '')
var foundryAccountNameWithout1 = replace(foundryAccountNameWithout0, '1', '')
var foundryAccountNameWithout2 = replace(foundryAccountNameWithout1, '2', '')
var foundryAccountNameWithout3 = replace(foundryAccountNameWithout2, '3', '')
var foundryAccountNameWithout4 = replace(foundryAccountNameWithout3, '4', '')
var foundryAccountNameWithout5 = replace(foundryAccountNameWithout4, '5', '')
var foundryAccountNameWithout6 = replace(foundryAccountNameWithout5, '6', '')
var foundryAccountNameWithout7 = replace(foundryAccountNameWithout6, '7', '')
var foundryAccountNameWithout8 = replace(foundryAccountNameWithout7, '8', '')
var foundryAccountNameWithout9 = replace(foundryAccountNameWithout8, '9', '')
var foundryAccountNameInvalidCharacters = replace(foundryAccountNameWithout9, '-', '')
var explicitFoundryAccountNameValid = empty(foundryAccountName) || (length(foundryAccountName) >= 2 && length(foundryAccountName) <= 64 && foundryAccountName == trim(foundryAccountName) && foundryAccountName == toLower(foundryAccountName) && !startsWith(foundryAccountName, '-') && !endsWith(foundryAccountName, '-') && empty(foundryAccountNameInvalidCharacters))

module foundryAccountNameValidation 'foundry-account-name-validation.bicep' = if (!empty(foundryAccountName)) {
  name: 'foundry-account-name-validation'
  params: {
    validatedFoundryAccountName: explicitFoundryAccountNameValid ? foundryAccountName : ''
  }
}

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
  dependsOn: [
    foundryAccountNameValidation
  ]
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
