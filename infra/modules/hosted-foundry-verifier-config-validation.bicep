targetScope = 'resourceGroup'

type hostedFoundryVerifierDisabledConfiguration = {
  mode: 'disabled'
}

type hostedFoundryVerifierEnabledConfiguration = {
  mode: 'enabled'
  @minLength(1)
  projectEndpoint: string
  @minLength(1)
  agentEndpoint: string
  @minLength(1)
  agentName: string
  @minLength(1)
  agentVersion: string
  @minLength(1)
  modelDeploymentName: string
}

@discriminator('mode')
type hostedFoundryVerifierConfigurationType =
  | hostedFoundryVerifierDisabledConfiguration
  | hostedFoundryVerifierEnabledConfiguration

param hostedFoundryVerifierConfiguration hostedFoundryVerifierConfigurationType

output configurationValidated bool = hostedFoundryVerifierConfiguration.mode == 'disabled' || hostedFoundryVerifierConfiguration.mode == 'enabled'
