using './main.bicep'

param location = 'eastus2'
param resourceGroupName = 'rg-dataops-portfolio-prod'
param containerAppsEnvironmentName = 'cae-dataops-portfolio-eus2'
param migrationJobName = 'caj-dataops-migrate-prod'
param apiAppName = 'ca-dataops-api-prod'
param neonPooledDatabaseUrl = readEnvironmentVariable('NEON_POOLED_DATABASE_URL')
param neonDirectDatabaseUrl = readEnvironmentVariable('NEON_DIRECT_DATABASE_URL')
param ingestionApiKey = readEnvironmentVariable('DATAOPS_INGESTION_API_KEY')
param containerImage = 'ghcr.io/bmowville/dataops-observability-api@sha256:41c7fe91d7388bd813564f22ce198b0f1a5c5d35d9c3e90601905183a1542828'
param allowedOrigin = 'https://flow-azure-beta.vercel.app'
param deployApi = bool(readEnvironmentVariable('AZURE_DEPLOY_API', 'false'))
