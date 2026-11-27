resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "finops/${var.environment}/app-secrets"
  recovery_window_in_days = var.environment == "production" ? 30 : 0

  tags = {
    Name = "finops-${var.environment}-secrets"
  }
}

resource "aws_secretsmanager_secret_version" "app_secrets_version" {
  secret_id = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    FINOPS_SECRET_KEY   = random_password.secret_key.result
    DB_PASSWORD         = random_password.db_password.result
    FINOPS_DATABASE_URL = "postgresql+psycopg://${aws_db_instance.postgres.username}:${random_password.db_password.result}@${aws_db_instance.postgres.endpoint}/${aws_db_instance.postgres.db_name}"
  })
}
