# TLDR

Notes of how I got Google Cloud Storage integration working

##

- Go to https://console.cloud.google.com/
- Go to the IAM & Admin > Service Accounts Page
  - https://console.cloud.google.com/iam-admin/serviceaccounts?project=command-labs
  - Create a Service Account called `multi-step-ai-agent-pipeline`

##

- https://console.cloud.google.com/storage/browser/social-media-content-for-distribution;tab=objects?prefix=&forceOnObjectsSortingFiltering=false
- Grant the Service Account permissions on the bucket
  - Add "Storage Object Admin` permissions

##

- Download a JSON key associated with the Service Account

## 