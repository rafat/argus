# Argus --- Setup & Deployment Guide

This document explains how to clone, configure, run, and deploy
**Argus** from a clean machine and a new Google Cloud project.

Argus uses:

-   Python 3.11+
-   FastAPI
-   Google Gen AI SDK
-   Gemini 3.5 Flash through Vertex AI
-   Google ADK
-   Firestore
-   Cloud Storage
-   Pub/Sub
-   Cloud Run
-   React/Vite (frontend)
-   React Flow
-   Vertex AI Vector Search (when enabled by the application)

> **Important:** This guide assumes you are creating your own Google
> Cloud project. Do not use the author's project ID, Firestore database,
> bucket, service account, or credentials.

------------------------------------------------------------------------

## 1. Architecture

The intended deployment is:

``` text
                         ┌─────────────────────┐
                         │   React / Vite UI    │
                         │     React Flow       │
                         └──────────┬──────────┘
                                    │ HTTPS
                                    ▼
                         ┌─────────────────────┐
                         │      Cloud Run       │
                         │    Argus FastAPI     │
                         └──────┬──────┬───────┘
                                │      │
              ┌─────────────────┘      └─────────────────┐
              ▼                                          ▼
       ┌──────────────┐                           ┌──────────────┐
       │   Firestore  │                           │ Cloud Storage│
       │              │                           │              │
       │ claims       │                           │ PDF/DOCX     │
       │ conflicts    │                           │ documents    │
       │ sessions     │                           │              │
       └──────────────┘                           └──────────────┘
              │
              ▼
       ┌──────────────────┐
       │    Vertex AI     │
       │ Gemini 3.5 Flash │
       └──────────────────┘
              │
              ▼
       ┌──────────────────┐
       │ Vertex AI Vector │
       │      Search      │
       └──────────────────┘

       ┌──────────────────┐
       │     Pub/Sub      │
       │ asynchronous jobs│
       └──────────────────┘
```

Cloud Run can build and deploy directly from source using Google Cloud
Buildpacks, so Docker is not required for the standard deployment path.

------------------------------------------------------------------------

# 2. Prerequisites

You need:

-   A Google account
-   A Google Cloud project with billing enabled
-   Permission to create IAM service accounts and grant project roles
-   Git
-   Python 3.11 or newer
-   Node.js 22 LTS recommended
-   Google Cloud CLI (`gcloud`)
-   A GitHub account if cloning from GitHub

Optional:

-   Docker Desktop
-   GitHub CLI (`gh`)

Official documentation:

-   Google Cloud CLI: https://cloud.google.com/sdk/docs/install
-   Cloud Run source deployment:
    https://docs.cloud.google.com/run/docs/deploying-source-code
-   Application Default Credentials:
    https://docs.cloud.google.com/docs/authentication/provide-credentials-adc

------------------------------------------------------------------------

# 3. Clone the repository

Clone the public repository:

``` bash
git clone https://github.com/YOUR_GITHUB_USERNAME/argus.git
cd argus
```

The repository should eventually have a structure similar to:

``` text
argus/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── ...
│   ├── requirements.txt
│   └── Procfile
│
├── frontend/
│   ├── src/
│   ├── package.json
│   └── ...
│
├── docs/
├── .env.example
├── .gitignore
└── README.md
```

Never commit `.env`, service-account JSON files, API keys, or other
credentials.

------------------------------------------------------------------------

# 4. Install the Google Cloud CLI

On macOS with Homebrew:

``` bash
brew install --cask gcloud-cli
```

Verify:

``` bash
gcloud --version
```

Initialize:

``` bash
gcloud init
```

Sign in with the Google account that owns or has access to your new
project.

------------------------------------------------------------------------

# 5. Create or select a Google Cloud project

Create a project in Google Cloud Console:

https://console.cloud.google.com/

For example:

``` text
Project name: Argus
Project ID: argus-XXXXXX
```

The project ID must be globally unique.

Set it locally:

``` bash
gcloud config set project YOUR_PROJECT_ID
```

Verify:

``` bash
gcloud config get-value project
```

------------------------------------------------------------------------

# 6. Enable required APIs

From the project root:

``` bash
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  secretmanager.googleapis.com
```

Verify:

``` bash
gcloud services list --enabled
```

At minimum, the following should be enabled:

``` text
aiplatform.googleapis.com
run.googleapis.com
firestore.googleapis.com
pubsub.googleapis.com
cloudbuild.googleapis.com
artifactregistry.googleapis.com
storage.googleapis.com
```

------------------------------------------------------------------------

# 7. Set up local Application Default Credentials

Google client libraries use Application Default Credentials (ADC) when
running locally.

Run:

``` bash
gcloud auth application-default login
```

A browser window will open. Sign in with an account that has access to
the project.

Set the ADC quota project:

``` bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Verify:

``` bash
gcloud auth application-default print-access-token
```

You should receive an access token.

Do not commit or share the ADC credential file.

More information:

https://docs.cloud.google.com/docs/authentication/provide-credentials-adc

------------------------------------------------------------------------

# 8. Configure Python

Argus uses Python 3.11+.

Check:

``` bash
python3 --version
```

On macOS, Python 3.11 can be installed with:

``` bash
brew install python@3.11
```

Create a virtual environment from the project root:

``` bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Upgrade packaging tools:

``` bash
python -m pip install --upgrade pip setuptools wheel
```

Install backend dependencies:

``` bash
cd backend
pip install -r requirements.txt
```

Return to the project root when finished:

``` bash
cd ..
```

------------------------------------------------------------------------

# 9. Configure Node.js

Node.js 22 LTS is recommended.

If using `nvm`:

``` bash
nvm install 22
nvm use 22
```

Verify:

``` bash
node --version
npm --version
```

If the repository contains `.nvmrc`, simply run:

``` bash
nvm use
```

------------------------------------------------------------------------

# 10. Create the Firestore database

Argus requires Firestore in **Native mode**.

You can create it in the Google Cloud Console:

https://console.cloud.google.com/firestore

Or with the CLI:

``` bash
gcloud firestore databases create \
  --database=argus \
  --location=YOUR_FIRESTORE_LOCATION \
  --type=firestore-native
```

Choose the location deliberately. Firestore database location is a
persistent architectural decision.

Verify:

``` bash
gcloud firestore databases list
```

The database should appear as:

``` text
argus
```

The application uses the database ID through:

``` text
FIRESTORE_DATABASE=argus
```

Official documentation:

https://docs.cloud.google.com/sdk/gcloud/reference/firestore/databases/create

------------------------------------------------------------------------

# 11. Create the Cloud Storage bucket

Create a globally unique bucket name.

Example:

``` bash
export GCS_BUCKET="argus-YOUR_PROJECT_ID-documents"
```

Then:

``` bash
gcloud storage buckets create \
  "gs://$GCS_BUCKET" \
  --location=YOUR_BUCKET_LOCATION \
  --uniform-bucket-level-access
```

Verify:

``` bash
gcloud storage buckets list
```

The bucket will be used for uploaded source documents and, where
required, Vector Search staging data.

------------------------------------------------------------------------

# 12. Create Pub/Sub resources

Create the document-processing topic:

``` bash
gcloud pubsub topics create document-processed
```

Create a development subscription:

``` bash
gcloud pubsub subscriptions create \
  document-processed-dev \
  --topic=document-processed
```

Test:

``` bash
gcloud pubsub topics publish \
  document-processed \
  --message='{"document_id":"test-001"}'
```

Then:

``` bash
gcloud pubsub subscriptions pull \
  document-processed-dev \
  --auto-ack
```

------------------------------------------------------------------------

# 13. Create the Cloud Run runtime service account

Create a dedicated service account for the Argus application:

``` bash
gcloud iam service-accounts create argus-runtime \
  --project=YOUR_PROJECT_ID \
  --display-name="Argus Cloud Run Runtime"
```

The service account will be:

``` text
argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Grant Vertex AI access:

``` bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

Grant Firestore access:

``` bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

Grant Cloud Storage object access:

``` bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"
```

Grant Pub/Sub publishing access:

``` bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

Do **not** create a service-account JSON key.

The Cloud Run service will use the attached service account
automatically through Application Default Credentials.

Cloud Run service identity documentation:

https://docs.cloud.google.com/run/docs/securing/service-identity

------------------------------------------------------------------------

# 14. Environment configuration

Create a local `.env` in the project root.

Example:

``` text
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID

# Vertex AI / Gemini
VERTEX_AI_LOCATION=asia-south1

# Firestore
FIRESTORE_DATABASE=argus

# Cloud Storage
GCS_BUCKET=YOUR_BUCKET_NAME

# Pub/Sub
PUBSUB_DOCUMENT_PROCESSED_TOPIC=document-processed

# Application
ENVIRONMENT=development
LOG_LEVEL=INFO
```

Important:

-   `VERTEX_AI_LOCATION` is specifically for Vertex AI/Gemini.
-   It does not determine the location of Firestore, Cloud Run, or Cloud
    Storage.
-   Your Firestore database and Storage bucket retain the locations
    selected when they were created.

Never commit `.env`.

Commit only `.env.example` with placeholder values.

------------------------------------------------------------------------

# 15. Verify Gemini locally

From the project root:

``` bash
source .venv/bin/activate
python backend/app/gemini_test.py
```

The test should successfully return a Gemini response.

Argus currently uses:

``` text
Gemini 3.5 Flash
Vertex AI
asia-south1
```

The Python client should explicitly configure Vertex AI:

``` python
from google import genai

client = genai.Client(
    vertexai=True,
    project=project_id,
    location=location,
)
```

Do not create a Gemini API key for this setup.

------------------------------------------------------------------------

# 16. Verify Firestore locally

Run:

``` bash
python backend/app/firestore_test.py
```

The test should successfully write and read from:

``` text
Firestore database: argus
```

If the code uses an explicit database, it should resemble:

``` python
from google.cloud import firestore

db = firestore.Client(
    project=project_id,
    database="argus",
)
```

------------------------------------------------------------------------

# 17. Run FastAPI locally

From `backend/`:

``` bash
cd backend
source ../.venv/bin/activate
uvicorn app.main:app --reload --port 8080
```

Open:

``` text
http://localhost:8080/health
```

Expected response:

``` json
{
  "status": "ok",
  "service": "argus-api"
}
```

Swagger documentation should be available at:

``` text
http://localhost:8080/docs
```

------------------------------------------------------------------------

# 18. Run the frontend locally

From the project root:

``` bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite, normally:

``` text
http://localhost:5173
```

The frontend should be configured to call the local FastAPI server:

``` text
http://localhost:8080
```

------------------------------------------------------------------------

# 19. Deploy the backend to Cloud Run

Make sure you are deploying from the **backend directory**, not the
repository root:

``` bash
cd backend
```

The backend must contain:

``` text
backend/
├── app/
│   ├── __init__.py
│   └── main.py
├── requirements.txt
└── Procfile
```

The `Procfile` should contain:

``` text
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

This is important because Cloud Run provides the `PORT` environment
variable to the container.

Deploy:

``` bash
gcloud run deploy argus-api \
  --source . \
  --project YOUR_PROJECT_ID \
  --region YOUR_CLOUD_RUN_REGION \
  --service-account "argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --allow-unauthenticated
```

Cloud Run's source deployment uses Google Cloud Buildpacks and Cloud
Build to build the container automatically. Docker is therefore not
required for this deployment method.

Official documentation:

https://docs.cloud.google.com/run/docs/deploying-source-code

------------------------------------------------------------------------

# 20. Configure Cloud Run environment variables

Do not upload your local `.env` file to Cloud Run.

Instead, configure the variables explicitly:

``` bash
gcloud run services update argus-api \
  --project YOUR_PROJECT_ID \
  --region YOUR_CLOUD_RUN_REGION \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,VERTEX_AI_LOCATION=asia-south1,FIRESTORE_DATABASE=argus,GCS_BUCKET=YOUR_BUCKET_NAME,PUBSUB_DOCUMENT_PROCESSED_TOPIC=document-processed,ENVIRONMENT=production,LOG_LEVEL=INFO"
```

The Cloud Run runtime service account provides authentication to Google
Cloud APIs, so no credentials need to be placed in environment
variables.

------------------------------------------------------------------------

# 21. Test the deployed backend

After deployment, Cloud Run prints a service URL similar to:

``` text
https://argus-api-XXXXXXXXXX-uc.a.run.app
```

Test:

``` bash
curl https://YOUR_CLOUD_RUN_URL/health
```

Expected:

``` json
{
  "status": "ok",
  "service": "argus-api"
}
```

Open the API documentation:

``` text
https://YOUR_CLOUD_RUN_URL/docs
```

------------------------------------------------------------------------

# 22. Deploying the frontend

The frontend can be deployed separately from the FastAPI backend.

A production deployment should have:

``` text
React/Vite frontend
        │
        │ HTTPS
        ▼
Cloud Run / static hosting
        │
        ▼
Argus FastAPI Cloud Run service
```

For a static Vite frontend, Firebase Hosting is a good option.
Alternatively, the frontend can be containerized and deployed to Cloud
Run.

The exact production frontend deployment should be added here once the
frontend build configuration is finalized.

------------------------------------------------------------------------

# 23. Vector Search

Vector Search should be provisioned before the application depends on it
because index creation/deployment can take significant time.

The eventual architecture is:

``` text
Claim
  │
  ├── metadata → Firestore
  │
  └── embedding → Vertex AI Vector Search
                         │
                         ▼
                  nearest neighbors
                         │
                         ▼
                   Conflict Agent
```

Firestore remains the source of truth. Vector Search is the semantic
retrieval layer.

Do not create a Vector Search index until the project has finalized:

-   embedding model
-   embedding dimensions
-   index location
-   endpoint configuration
-   staging bucket
-   distance metric

------------------------------------------------------------------------

# 24. Model Armor

Model Armor is part of the later hardening phase.

The intended pipeline is:

``` text
User/document input
        │
        ▼
   Model Armor
        │
        ▼
     Argus agents
        │
        ▼
   Model response
        │
        ▼
   Model Armor
        │
        ▼
      User
```

Do not make Model Armor a prerequisite for the initial `/health`
deployment.

------------------------------------------------------------------------

# 25. Troubleshooting

## Cloud Run says the container did not listen on PORT=8080

Verify `backend/Procfile`:

``` text
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Test locally:

``` bash
export PORT=8080
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Then:

``` bash
curl http://localhost:8080/health
```

------------------------------------------------------------------------

## Firestore says database `(default)` does not exist

If the project uses a database named `argus`, make sure the application
explicitly uses:

``` python
firestore.Client(
    project=project_id,
    database="argus",
)
```

List databases:

``` bash
gcloud firestore databases list
```

------------------------------------------------------------------------

## Gemini says the model was not found

Check the Vertex AI location.

Argus currently uses:

``` text
VERTEX_AI_LOCATION=asia-south1
```

Do not use `us-central1` for the Gemini 3.5 Flash configuration if that
model is unavailable there.

Also verify that the Vertex AI API is enabled:

``` bash
gcloud services list --enabled \
  --filter="NAME:aiplatform.googleapis.com"
```

------------------------------------------------------------------------

## Cloud Run cannot access Firestore/Vertex AI/Storage

Check the Cloud Run service identity:

``` bash
gcloud run services describe argus-api \
  --project YOUR_PROJECT_ID \
  --region YOUR_CLOUD_RUN_REGION
```

Confirm it is using:

``` text
argus-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Then verify IAM roles for that service account.

------------------------------------------------------------------------

## Local Google authentication fails

Run:

``` bash
gcloud auth application-default login
```

Then:

``` bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Test:

``` bash
gcloud auth application-default print-access-token
```

Remember that `gcloud auth login` and Application Default Credentials
are separate authentication mechanisms.

------------------------------------------------------------------------

# 26. Clean deployment checklist

Before considering a fresh deployment successful:

``` text
[ ] Google Cloud project created
[ ] Billing enabled
[ ] Required APIs enabled
[ ] gcloud authenticated
[ ] ADC configured locally
[ ] Firestore Native database created
[ ] Cloud Storage bucket created
[ ] Pub/Sub topic created
[ ] Argus runtime service account created
[ ] Vertex AI role granted
[ ] Firestore role granted
[ ] Storage role granted
[ ] Pub/Sub publisher role granted
[ ] .env created locally
[ ] .env excluded from Git
[ ] Python virtual environment created
[ ] Backend dependencies installed
[ ] Gemini local test works
[ ] Firestore local test works
[ ] FastAPI /health works locally
[ ] Procfile present
[ ] Cloud Run deployment succeeds
[ ] Cloud Run environment variables configured
[ ] Cloud Run /health works
[ ] Frontend builds successfully
```

------------------------------------------------------------------------

# 27. Security rules for contributors

Never commit:

``` text
.env
*.json                 # if it contains credentials
service-account keys
API keys
access tokens
private keys
ADC credential files
```

Use:

``` text
.env.example
```

for configuration documentation.

Contributors should authenticate with their own Google account and their
own Google Cloud project.

The deployed Cloud Run service should use a dedicated runtime service
account rather than a personal user credential or downloaded
service-account key.

------------------------------------------------------------------------

# 28. Useful Google Cloud commands

Show current project:

``` bash
gcloud config get-value project
```

List enabled APIs:

``` bash
gcloud services list --enabled
```

List Firestore databases:

``` bash
gcloud firestore databases list
```

List buckets:

``` bash
gcloud storage buckets list
```

List Pub/Sub topics:

``` bash
gcloud pubsub topics list
```

List Cloud Run services:

``` bash
gcloud run services list
```

View Cloud Run logs:

``` bash
gcloud run services logs read argus-api \
  --project YOUR_PROJECT_ID \
  --region YOUR_CLOUD_RUN_REGION \
  --limit 100
```

Describe Cloud Run service:

``` bash
gcloud run services describe argus-api \
  --project YOUR_PROJECT_ID \
  --region YOUR_CLOUD_RUN_REGION
```

------------------------------------------------------------------------

# 29. Reproducibility principle

A fresh developer should be able to go from:

``` text
Git clone
    ↓
Install prerequisites
    ↓
Create GCP project
    ↓
Enable APIs
    ↓
Create Firestore
    ↓
Create Storage
    ↓
Create Pub/Sub
    ↓
Create runtime service account
    ↓
Configure .env
    ↓
Install dependencies
    ↓
Run local tests
    ↓
Deploy Cloud Run
    ↓
Test /health
```

without needing access to the original developer's Google account or
credentials.

This is an intentional design requirement of the Argus repository.
