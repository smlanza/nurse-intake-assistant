targetScope = 'resourceGroup'

param location string = resourceGroup().location
param projectName string = 'nurse-intake'
param environmentName string = 'daily'
@description('Optional explicit globally unique daily Foundry account name. Existing resources must pass separate ownership and drift verification.')
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

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    foundryAccountName: foundryAccountName
    foundryProjectName: foundryProjectName
    foundryProjectDisplayName: foundryProjectDisplayName
    foundryProjectDescription: foundryProjectDescription
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelPublisherFormat: modelPublisherFormat
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    tags: tags
  }
}

output foundryResourceName string = foundry.outputs.foundryResourceName
output foundryProjectName string = foundry.outputs.foundryProjectName
output foundryProjectEndpoint string = foundry.outputs.foundryProjectEndpoint
output modelDeploymentName string = foundry.outputs.modelDeploymentName
