resource "aws_ecs_cluster" "main" {
  name = "finops-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "finops-${var.environment}-cluster"
  }
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/finops-${var.environment}-web"
  retention_in_days = var.environment == "production" ? 30 : 7

  tags = {
    Name = "finops-${var.environment}-web-logs"
  }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/finops-${var.environment}-worker"
  retention_in_days = var.environment == "production" ? 30 : 7

  tags = {
    Name = "finops-${var.environment}-worker-logs"
  }
}

# --- Web Task Definition & Service ---

resource "aws_ecs_task_definition" "web" {
  family                   = "finops-${var.environment}-web"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.web_cpu
  memory                   = var.web_memory
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = var.container_image
      essential = true
      command = [
        "gunicorn",
        "--bind", "0.0.0.0:5000",
        "--workers", "4",
        "--threads", "2",
        "--timeout", "60",
        "--access-logfile", "-",
        "--error-logfile", "-",
        "finops_app:create_app()"
      ]
      portMappings = [
        {
          containerPort = 5000
          hostPort      = 5000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "FINOPS_ENV", value = var.environment },
        { name = "FINOPS_PORT", value = "5000" },
        { name = "FINOPS_STORAGE_BACKEND", value = "s3" },
        { name = "FINOPS_S3_BUCKET", value = aws_s3_bucket.storage.id },
        { name = "FINOPS_REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
        { name = "FINOPS_AUTO_MIGRATE", value = "0" },
        { name = "FINOPS_LOG_JSON", value = "1" },
        { name = "FINOPS_TRUSTED_PROXIES", value = "1" },
        { name = "FINOPS_SENTRY_DSN", value = var.sentry_dsn }
      ]
      secrets = [
        {
          name      = "FINOPS_SECRET_KEY"
          valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:FINOPS_SECRET_KEY::"
        },
        {
          name      = "FINOPS_DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:FINOPS_DATABASE_URL::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.web.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "web"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "web" {
  name            = "finops-${var.environment}-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.web_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 5000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy_attachment.ecs_execution_default
  ]
}

# --- Background Worker Task Definition & Service ---

resource "aws_ecs_task_definition" "worker" {
  family                   = "finops-${var.environment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.container_image
      essential = true
      command   = ["finops-worker"]
      environment = [
        { name = "FINOPS_ENV", value = var.environment },
        { name = "FINOPS_STORAGE_BACKEND", value = "s3" },
        { name = "FINOPS_S3_BUCKET", value = aws_s3_bucket.storage.id },
        { name = "FINOPS_REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
        { name = "FINOPS_LOG_JSON", value = "1" },
        { name = "FINOPS_SENTRY_DSN", value = var.sentry_dsn }
      ]
      secrets = [
        {
          name      = "FINOPS_SECRET_KEY"
          valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:FINOPS_SECRET_KEY::"
        },
        {
          name      = "FINOPS_DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:FINOPS_DATABASE_URL::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "finops-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_iam_role_policy_attachment.ecs_execution_default
  ]
}
