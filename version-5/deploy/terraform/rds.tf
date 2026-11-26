resource "aws_db_subnet_group" "rds" {
  name        = "finops-${var.environment}-rds-subnet-group"
  subnet_ids  = aws_subnet.private[*].id
  description = "Private subnets for FinOps RDS instance"

  tags = {
    Name = "finops-${var.environment}-rds-subnet-group"
  }
}

resource "aws_db_instance" "postgres" {
  identifier                  = "finops-${var.environment}-postgres"
  engine                      = "postgres"
  engine_version              = "16.3"
  instance_class              = var.db_instance_class
  allocated_storage           = var.db_allocated_storage
  max_allocated_storage       = var.db_max_allocated_storage
  storage_type                = "gp3"
  storage_encrypted           = true
  db_subnet_group_name        = aws_db_subnet_group.rds.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  db_name                     = "finops"
  username                    = "finops_admin"
  password                    = random_password.db_password.result
  skip_final_snapshot         = var.environment != "production"
  final_snapshot_identifier   = "finops-${var.environment}-postgres-final-snapshot"
  backup_retention_period     = var.environment == "production" ? 14 : 7
  backup_window               = "03:00-04:00"
  maintenance_window          = "Sun:04:30-Sun:05:30"
  auto_minor_version_upgrade  = true
  deletion_protection         = var.environment == "production"
  allow_major_version_upgrade = false

  tags = {
    Name = "finops-${var.environment}-postgres"
  }
}
