targetScope = 'resourceGroup'

@minLength(2)
@maxLength(60)
param webAppName string

@minLength(36)
@maxLength(36)
param entraClientId string

@minLength(36)
@maxLength(36)
param entraTenantId string

resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
}

resource webAppAuthentication 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
      excludedPaths: [
        '/health'
        '/version'
        '/demo/status'
      ]
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
        }
      }
    }
  }
}
