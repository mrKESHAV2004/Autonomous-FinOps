resource "aws_security_group" "alb" {
  name        = "finops-${var.environment}-alb-sg"
  description = "Public inbound traffic to FinOps Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Outbound to anywhere"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "finops-${var.environment}-alb-sg"
  }
}

resource "aws_security_group" "ecs" {
  name        = "finops-${var.environment}-ecs-sg"
  description = "Ingress from ALB to ECS web tasks; outbound for workers and APIs"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Inbound from ALB on web port 5000"
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Outbound to internet via NAT (for STS, cloud APIs, webhooks)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "finops-${var.environment}-ecs-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "finops-${var.environment}-rds-sg"
  description = "PostgreSQL access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "finops-${var.environment}-rds-sg"
  }
}

resource "aws_security_group" "redis" {
  name        = "finops-${var.environment}-redis-sg"
  description = "ElastiCache Redis access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis port 6379 from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "finops-${var.environment}-redis-sg"
  }
}
