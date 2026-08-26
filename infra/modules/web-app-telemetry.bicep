targetScope = 'resourceGroup'

@minLength(2)
@maxLength(60)
param webAppName string

@minLength(1)
@maxLength(260)
param applicationInsightsName string

resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource webAppAppSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: webApp
  name: 'appsettings'
  properties: union(
    list('${webApp.id}/config/appsettings', '2024-04-01').properties,
    {
      TELEMETRY_PROVIDER: 'azure-monitor'
      APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
    }
  )
}
