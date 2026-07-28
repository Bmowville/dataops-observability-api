targetScope = 'resourceGroup'

@description('Azure region for the Container App.')
param location string

@description('Public Container App name.')
param appName string

@description('Resource ID of the Container Apps managed environment.')
param environmentId string

@description('Default DNS domain of the Container Apps managed environment.')
param environmentDefaultDomain string

@description('Immutable public GHCR image pinned by digest.')
param containerImage string

@description('Production Neon pooled PostgreSQL connection URL used by the API.')
@secure()
param neonPooledDatabaseUrl string

@description('Production key required by API write and ingestion endpoints.')
@secure()
param ingestionApiKey string

@description('Only browser origin allowed by the Container App CORS policy.')
param allowedOrigin string

@description('Tags applied to the Container App.')
param tags object

resource api 'Microsoft.App/containerApps@2026-01-01' = {
  name: appName
  location: location
  tags: tags
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 10
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8000
        transport: 'auto'
        corsPolicy: {
          allowedOrigins: [
            allowedOrigin
          ]
          allowedMethods: [
            'GET'
            'HEAD'
            'OPTIONS'
          ]
          allowedHeaders: [
            'Content-Type'
          ]
          exposeHeaders: []
          allowCredentials: false
          maxAge: 3600
        }
      }
      secrets: [
        {
          name: 'database-url'
          value: neonPooledDatabaseUrl
        }
        {
          name: 'ingestion-api-key'
          value: ingestionApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          env: [
            {
              name: 'ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'INGESTION_API_KEYS'
              secretRef: 'ingestion-api-key'
            }
            {
              name: 'RUN_MIGRATIONS_ON_STARTUP'
              value: 'false'
            }
            {
              name: 'SERVER_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'SERVER_PORT'
              value: '8000'
            }
            {
              name: 'SERVER_RELOAD'
              value: 'false'
            }
            {
              name: 'PUBLIC_BASE_URL'
              value: 'https://${appName}.${environmentDefaultDomain}'
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/live'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              timeoutSeconds: 5
              failureThreshold: 10
              successThreshold: 1
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
              successThreshold: 1
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/live'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 3
              failureThreshold: 3
              successThreshold: 1
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        cooldownPeriod: 300
        rules: [
          {
            name: 'http-requests'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output apiId string = api.id
output apiFqdn string = api.properties.configuration.ingress.fqdn!
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn!}'
