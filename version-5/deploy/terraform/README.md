# Production AWS Infrastructure Deployment (ECS Fargate + RDS + Redis + S3)

Production-grade Infrastructure-as-Code for Autonomous FinOps using Terraform.

## Architecture

```
                       Internet
                          │
                          ▼
            Application Load Balancer (ALB)
                 [Healthcheck: /healthz]
                 ┌────────┴────────┐
                 ▼                 ▼
          ECS Web Fargate    ECS Web Fargate
           (Gunicorn :5000)   (Gunicorn :5000)
                 │                 │
                 └────────┬────────┘
                          ▼
         ┌────────────────┼────────────────┐
         │                │                │
         ▼                ▼                ▼
   RDS PostgreSQL   ElastiCache Redis    S3 Storage
   (gp3 encrypted)    (RQ Worker Queue)   (AES256, 90d lifecycle)
         ▲                ▲                ▲
         │                │                │
         └────────┬───────┴────────────────┘
                  ▼
          ECS Worker Fargate
          (finops-worker)
```

## Resources Provisioned

1. **VPC & Networking (`vpc.tf`):** Dedicated `/16` VPC, 2 public subnets (ALB & NAT Gateway), 2 private subnets (ECS, RDS, Redis), Elastic IP & NAT Gateway.
2. **Security Groups (`security_groups.tf`):** Least-privilege rules (ALB accepts 80/443; ECS only accepts 5000 from ALB; RDS accepts 5432 only from ECS; Redis accepts 6379 only from ECS).
3. **Application Load Balancer (`alb.tf`):** Public ALB with HTTP/HTTPS listeners, Target Group with `/healthz` health checking.
4. **ECS Cluster & Services (`ecs.tf`):**
   - Container Insights enabled.
   - `web`: Gunicorn WSGI server (`workers: 4`, `threads: 2`, `desired_count: 2`). Circuit breaker with auto-rollback.
   - `worker`: Background RQ worker (`desired_count: 2`) processing uploads, CUR ingestion, and model forecasting.
5. **RDS PostgreSQL (`rds.tf`):** Version 16, encrypted storage with auto-scaling (20GB up to 100GB), automated backup retention (14 days), automated snapshot windows.
6. **ElastiCache Redis (`elasticache.tf`):** Redis 7 cluster for asynchronous RQ queue jobs.
7. **S3 Object Storage (`s3.tf`):** Server-side encryption (AES256), public access blocked, bucket versioning enabled, 90-day automatic expiration lifecycle rule for raw billing uploads.
8. **Secrets Manager (`secrets.tf`):** Manages `FINOPS_SECRET_KEY` and RDS master database credentials.
9. **IAM Roles (`iam.tf`):**
   - Execution Role: ECR image pulls, CloudWatch logs, Secrets Manager secret retrieval.
   - Task Role: Read/Write to FinOps S3 bucket, `sts:AssumeRole` for customer AWS CUR connectors, `ses:SendRawEmail` for email alerts.

---

## Deployment Instructions

### Prerequisites
- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.5.0
- [AWS CLI](https://aws.amazon.com/cli/) configured with deployment credentials
- Docker image pushed to AWS ECR

### 1. Initialize Terraform
```bash
cd version-5/deploy/terraform
terraform init
```

### 2. Plan Infrastructure
```bash
terraform plan \
  -var="environment=production" \
  -var="container_image=<YOUR_ECR_REPO>/finops-app:latest" \
  -out=tfplan
```

### 3. Apply
```bash
terraform apply tfplan
```

### 4. Run Initial Database Migrations
Run an ad-hoc ECS Fargate one-off task using the AWS CLI:
```bash
aws ecs run-task \
  --cluster finops-production-cluster \
  --task-definition finops-production-web \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PRIVATE_SUBNET_ID>],securityGroups=[<ECS_SG_ID>],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides": [{"name": "web", "command": ["finops-db", "upgrade"]}]}'
```

---

## Rolling Deployments & Updates

Zero-downtime rolling deploys can be triggered upon new image pushes:
```bash
aws ecs update-service \
  --cluster finops-production-cluster \
  --service finops-production-web \
  --force-new-deployment

aws ecs update-service \
  --cluster finops-production-cluster \
  --service finops-production-worker \
  --force-new-deployment
```

---

## Backup & Restore Drill

### 1. Automated Backups
RDS automatically creates daily snapshots and preserves write-ahead logs for Point-in-Time Recovery (PITR) within the retention window (14 days).

### 2. Manual Backup Snapshot
Before making major schema changes or upgrades:
```bash
aws rds create-db-snapshot \
  --db-instance-identifier finops-production-postgres \
  --db-snapshot-identifier finops-pre-migration-$(date +%Y%m%d%H%M%S)
```

### 3. Restore Drill (Testing Recovery)
Restore a snapshot into a drill instance to verify backup integrity:
```bash
# Restore to a drill instance
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier finops-restore-drill \
  --db-snapshot-identifier <SNAPSHOT_IDENTIFIER> \
  --db-instance-class db.t4g.small \
  --db-subnet-group-name finops-production-rds-subnet-group \
  --vpc-security-group-ids <RDS_SG_ID>

# Verify connection & schema integrity
psql -h <RESTORED_ENDPOINT> -U finops_admin -d finops -c "\dt"

# Clean up drill instance
aws rds delete-db-instance \
  --db-instance-identifier finops-restore-drill \
  --skip-final-snapshot
```
