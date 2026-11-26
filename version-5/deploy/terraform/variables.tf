variable "aws_region" {
  type        = string
  description = "AWS region for all provisioned resources"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Deployment environment (production, staging, dev)"
  default     = "production"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the dedicated VPC"
  default     = "10.0.0.0/16"
}

variable "container_image" {
  type        = string
  description = "ECR image URI for the FinOps web & worker containers"
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/finops-app:latest"
}

variable "web_cpu" {
  type        = number
  description = "CPU units for ECS web task (1024 = 1 vCPU)"
  default     = 1024
}

variable "web_memory" {
  type        = number
  description = "Memory (MiB) for ECS web task"
  default     = 2048
}

variable "web_count" {
  type        = number
  description = "Desired count of web container instances behind the ALB"
  default     = 2
}

variable "worker_cpu" {
  type        = number
  description = "CPU units for ECS background worker task"
  default     = 2048
}

variable "worker_memory" {
  type        = number
  description = "Memory (MiB) for ECS background worker task"
  default     = 4096
}

variable "worker_count" {
  type        = number
  description = "Desired count of worker container instances"
  default     = 2
}

variable "db_instance_class" {
  type        = string
  description = "RDS PostgreSQL instance type"
  default     = "db.t4g.small"
}

variable "db_allocated_storage" {
  type        = number
  description = "Initial allocated storage in GB for RDS"
  default     = 20
}

variable "db_max_allocated_storage" {
  type        = number
  description = "Max auto-scaling storage in GB for RDS"
  default     = 100
}

variable "redis_node_type" {
  type        = string
  description = "ElastiCache Redis node type"
  default     = "cache.t4g.micro"
}

variable "certificate_arn" {
  type        = string
  description = "Optional ACM certificate ARN for HTTPS listener on the ALB"
  default     = ""
}

variable "sentry_dsn" {
  type        = string
  description = "Optional Sentry DSN for error monitoring"
  default     = ""
}
