# Streamlit AlloyDB + Gemini on Cloud Run

## 1) Secret Management (GCP Secret Manager)

Create secrets once:

```bash
gcloud secrets create alloydb-instance-uri --replication-policy=automatic
gcloud secrets create alloydb-db-user --replication-policy=automatic
gcloud secrets create alloydb-db-name --replication-policy=automatic
gcloud secrets create gemini-api-key --replication-policy=automatic
```

Add secret values:

```bash
echo -n "projects/PROJECT_ID/locations/REGION/clusters/CLUSTER/instances/INSTANCE" | gcloud secrets versions add alloydb-instance-uri --data-file=-
echo -n "DB_USER" | gcloud secrets versions add alloydb-db-user --data-file=-
echo -n "DB_NAME" | gcloud secrets versions add alloydb-db-name --data-file=-
echo -n "GEMINI_API_KEY_VALUE" | gcloud secrets versions add gemini-api-key --data-file=-
```

Optional secret (only if IAM DB auth is disabled):

```bash
gcloud secrets create alloydb-db-password --replication-policy=automatic
echo -n "DB_PASSWORD" | gcloud secrets versions add alloydb-db-password --data-file=-
```

## 2) Build and Deploy to Cloud Run

From this folder:

```bash
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT_ID/REPO/budget-copilot:latest
```

Deploy:

```bash
gcloud run deploy budget-copilot \
  --image REGION-docker.pkg.dev/PROJECT_ID/REPO/budget-copilot:latest \
  --region REGION \
  --platform managed \
  --allow-unauthenticated \
  --service-account CLOUD_RUN_SA@PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars ALLOYDB_ENABLE_IAM_AUTH=true,ALLOYDB_IP_TYPE=PRIVATE,GEMINI_MODEL=gemini-2.0-flash \
  --set-secrets ALLOYDB_INSTANCE_URI=alloydb-instance-uri:latest,ALLOYDB_DB_USER=alloydb-db-user:latest,ALLOYDB_DB_NAME=alloydb-db-name:latest,GEMINI_API_KEY=gemini-api-key:latest \
  --vpc-connector projects/PROJECT_ID/locations/REGION/connectors/CONNECTOR_NAME \
  --vpc-egress all-traffic
```

If password auth is used:

```bash
--set-env-vars ALLOYDB_ENABLE_IAM_AUTH=false,ALLOYDB_IP_TYPE=PRIVATE \
--set-secrets ALLOYDB_DB_PASSWORD=alloydb-db-password:latest
```

## 3) IAM and Connectivity

### Required IAM roles

Grant roles to your Cloud Run service account (`CLOUD_RUN_SA`):

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:CLOUD_RUN_SA@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/alloydb.client"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:CLOUD_RUN_SA@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:CLOUD_RUN_SA@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/alloydb.databaseUser"
```

For IAM DB authentication on AlloyDB, map the principal to a database user and grant read permissions in Postgres.

### Network path (recommended: private IP)

1. Ensure AlloyDB instance has private IP enabled in the same VPC.
2. Create a Serverless VPC Access connector in the same region as Cloud Run.
3. Deploy Cloud Run with the connector and `--vpc-egress all-traffic` or `private-ranges-only` depending on your policy.
4. Set `ALLOYDB_IP_TYPE=PRIVATE`.

### Direct VPC egress alternative

If your environment uses Direct VPC egress, configure Cloud Run to use direct VPC networking instead of a connector and keep `ALLOYDB_IP_TYPE=PRIVATE`.

## 4) Local Development

Create local environment variables:

```bash
export ALLOYDB_INSTANCE_URI="projects/PROJECT_ID/locations/REGION/clusters/CLUSTER/instances/INSTANCE"
export ALLOYDB_DB_USER="DB_USER"
export ALLOYDB_DB_NAME="postgres"
export ALLOYDB_ENABLE_IAM_AUTH="true"
export ALLOYDB_IP_TYPE="PUBLIC"
export GEMINI_API_KEY="YOUR_KEY"
export GEMINI_MODEL="gemini-2.0-flash"
```

Run:

```bash
pip install -r requirements.txt
streamlit run app.py
```
