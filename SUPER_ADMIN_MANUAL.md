# Aditya LMS: Super Admin Deployment & Scaling Manual

This document provides system administrators with the blueprints to deploy, secure, and scale the Aditya Learning Management System to **60,000+ active learners** using low-cost and free-tier infrastructure.

---

## 1. Free/Budget Infrastructure Decoupling

To prevent server storage exhaustion and network egress bottlenecks, storage and delivery must be decoupled from the primary application server.

### A. Free & Open-Source Storage: Self-Hosted MinIO
MinIO is a high-performance, S3-compatible object storage server that you can host on your own server hardware.
* **Why**: 100% free software. You only pay for the raw hard drives you purchase.
* **S3-Compatibility**: Aditya LMS connects to MinIO using the exact same standard S3 protocol as AWS.

#### MinIO Installation via Docker:
```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -v /mnt/data:/data \
  -e "MINIO_ROOT_USER=admin" \
  -e "MINIO_ROOT_PASSWORD=super-secret-password-2026" \
  minio/minio server /data --console-address ":9001"
```

### B. Ultra-Low Cost Storage: Backblaze B2
If you do not want to host your own storage server, Backblaze B2 is an AWS S3 alternative.
* **Why**: Gives **10 GB completely free** forever. Subsequent storage is only $0.006/GB/month (1/4 the cost of AWS S3).
* **Free Egress**: Backblaze partners with Cloudflare to offer **$0 egress fees** (bandwidth is completely free when cached/routed through Cloudflare).

### C. CDN & DDoS Defense: Cloudflare (Free Tier)
* **Why**: Cloudflare's free tier provides **unlimited CDN caching bandwidth**, free SSL/TLS certificates, and automatic DDoS mitigation.
* **Configuration**: Set your domain's nameservers to Cloudflare and toggle the DNS proxy cloud to "Proxied" (orange cloud icon). This hides your application server's real IP and caches static assets at Edge servers globally.

---

## 2. Transitioning Database from SQLite to PostgreSQL

SQLite limits writes to one concurrent transaction, which causes locks under high learner volumes. 

### Step-by-Step PostgreSQL Migration:
1. Spin up a PostgreSQL instance (e.g. self-hosted or AWS RDS).
2. Install the database driver in your environment:
   ```bash
   pip install psycopg2-binary
   ```
3. Update the `.env` file's `DATABASE_URL` variable to point to PostgreSQL:
   ```env
   DATABASE_URL=postgresql://lms_user:secure_password@localhost:5432/lms_db
   ```
4. Run DB migrations to build the tables on PostgreSQL:
   ```bash
   flask db upgrade
   ```

---

## 3. Storage Provider Environment Configuration

Configure these environment variables in your deployment `.env` file:

```env
# Storage Provider ('local' or 's3')
STORAGE_PROVIDER=s3

# S3 / MinIO Credentials
S3_ACCESS_KEY=admin
S3_SECRET_KEY=super-secret-password-2026
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=narayana-lms
```
