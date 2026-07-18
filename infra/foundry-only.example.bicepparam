using './foundry-only.bicep'

param location = 'centralus'
param projectName = 'fictional-intake'
param environmentName = 'daily'
param foundryProjectName = 'fictional-intake-project'
param foundryProjectDisplayName = 'Fictional Intake Daily Validation'
param foundryProjectDescription = 'Disposable Foundry project using fictional validation data only.'
param modelDeploymentName = 'fictional-model-deployment'
param modelName = 'replace-with-available-model-name'
param modelVersion = 'replace-with-available-model-version'
param modelPublisherFormat = 'OpenAI'
param modelSkuName = 'GlobalStandard'
param modelCapacity = 1
param tags = {
  purpose: 'fictional-daily-validation'
}
