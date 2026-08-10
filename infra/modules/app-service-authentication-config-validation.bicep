targetScope = 'resourceGroup'

type appServiceAuthenticationDisabledConfiguration = {
  mode: 'disabled'
}

type appServiceAuthenticationEnabledConfiguration = {
  mode: 'enabled'
  @minLength(36)
  @maxLength(36)
  clientId: string
  @minLength(36)
  @maxLength(36)
  tenantId: string
}

@discriminator('mode')
type appServiceAuthenticationConfigurationType =
  | appServiceAuthenticationDisabledConfiguration
  | appServiceAuthenticationEnabledConfiguration

param appServiceAuthenticationConfiguration appServiceAuthenticationConfigurationType

output configurationValidated bool = appServiceAuthenticationConfiguration.mode == 'disabled' || appServiceAuthenticationConfiguration.mode == 'enabled'
