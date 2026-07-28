targetScope = 'resourceGroup'

@description('Azure region for the Container Apps resources.')
param location string

@description('Container Apps managed environment name.')
param environmentName string

@description('Manual Container Apps migration job name.')
param migrationJobName string

@description('Immutable public GHCR image pinned by digest.')
param containerImage string

@description('Production Neon direct PostgreSQL connection URL used only by the migration job.')
@secure()
param neonDirectDatabaseUrl string

@description('Tags applied to the environment and migration job.')
param tags object

resource environment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    publicNetworkAccess: 'Enabled'
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource migrationJob 'Microsoft.App/jobs@2026-01-01' = {
  name: migrationJobName
  location: location
  tags: tags
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url-direct'
          value: neonDirectDatabaseUrl
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: containerImage
          command: [
            'alembic'
          ]
          args: [
            'upgrade'
            'head'
          ]
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url-direct'
            }
            {
              name: 'ENVIRONMENT'
              value: 'migration'
            }
            {
              name: 'RUN_MIGRATIONS_ON_STARTUP'
              value: 'false'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
}

output environmentId string = environment.id
output environmentDefaultDomain string = environment.properties.defaultDomain!
output migrationJobId string = migrationJob.id
output migrationJobName string = migrationJob.name
