targetScope = 'subscription'

@description('Azure region for the DataOps portfolio resources.')
param location string = 'eastus2'

@description('Resource group that contains the Container Apps resources.')
param resourceGroupName string = 'rg-dataops-portfolio-prod'

@description('Container Apps managed environment name.')
param containerAppsEnvironmentName string = 'cae-dataops-portfolio-eus2'

@description('Manual Container Apps migration job name.')
param migrationJobName string = 'caj-dataops-migrate-prod'

@description('Public Container App name.')
param apiAppName string = 'ca-dataops-api-prod'

@description('Monthly Azure Cost Management budget name.')
param budgetName string = 'budget-dataops-portfolio-5-usd'

@description('First day of the current budget month as an ISO 8601 timestamp, for example 2026-08-01T00:00:00Z. Keep this value stable on redeployments.')
param budgetStartDate string

@description('Email address that receives Azure budget notifications. Supply at deployment time; do not commit a personal address.')
param budgetContactEmail string

@description('Production Neon pooled PostgreSQL connection URL used by the API.')
@secure()
param neonPooledDatabaseUrl string

@description('Production Neon direct PostgreSQL connection URL used only by the migration job.')
@secure()
param neonDirectDatabaseUrl string

@description('Production key required by API write and ingestion endpoints.')
@secure()
param ingestionApiKey string

@description('Immutable public GHCR image pinned by digest.')
param containerImage string = 'ghcr.io/bmowville/dataops-observability-api@sha256:41c7fe91d7388bd813564f22ce198b0f1a5c5d35d9c3e90601905183a1542828'

@description('Only browser origin allowed by the Container App CORS policy.')
param allowedOrigin string = 'https://flow-azure-beta.vercel.app'

@description('Safety gate. Leave false until the migration job execution has reached Succeeded.')
param deployApi bool = false

@description('Tags applied to all taggable resources.')
param tags object = {
  project: 'dataops-observability'
  environment: 'prod'
  'managed-by': 'bicep'
  'cost-owner': 'portfolio'
}

resource rg 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

resource monthlyBudget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: budgetName
  properties: {
    amount: 5
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [
          rg.name
        ]
      }
    }
    notifications: {
      Actual50Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [
          budgetContactEmail
        ]
        contactGroups: []
        contactRoles: []
      }
      Actual80Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [
          budgetContactEmail
        ]
        contactGroups: []
        contactRoles: []
      }
      Actual100Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [
          budgetContactEmail
        ]
        contactGroups: []
        contactRoles: []
      }
      Forecasted100Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [
          budgetContactEmail
        ]
        contactGroups: []
        contactRoles: []
      }
    }
  }
}

module containerAppsPlatform './modules/container-apps-platform.bicep' = {
  name: 'dataops-container-apps-platform'
  scope: rg
  params: {
    location: location
    environmentName: containerAppsEnvironmentName
    migrationJobName: migrationJobName
    containerImage: containerImage
    neonDirectDatabaseUrl: neonDirectDatabaseUrl
    tags: tags
  }
}

module api './modules/api.bicep' = if (deployApi) {
  name: 'dataops-api'
  scope: rg
  params: {
    location: location
    appName: apiAppName
    environmentId: containerAppsPlatform.outputs.environmentId
    environmentDefaultDomain: containerAppsPlatform.outputs.environmentDefaultDomain
    containerImage: containerImage
    neonPooledDatabaseUrl: neonPooledDatabaseUrl
    ingestionApiKey: ingestionApiKey
    allowedOrigin: allowedOrigin
    tags: tags
  }
}

output resourceGroupId string = rg.id
output deployedResourceGroupName string = rg.name
output budgetId string = monthlyBudget.id
output environmentId string = containerAppsPlatform.outputs.environmentId
output migrationJobId string = containerAppsPlatform.outputs.migrationJobId
output deployedMigrationJobName string = containerAppsPlatform.outputs.migrationJobName
output deployedApiAppName string = apiAppName
output apiFqdn string = deployApi ? api!.outputs.apiFqdn : ''
output apiUrl string = deployApi ? api!.outputs.apiUrl : ''
