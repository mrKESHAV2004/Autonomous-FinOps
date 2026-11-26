resource "aws_elasticache_subnet_group" "redis" {
  name        = "finops-${var.environment}-redis-subnet-group"
  subnet_ids  = aws_subnet.private[*].id
  description = "Private subnets for FinOps ElastiCache Redis"
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "finops-${var.environment}-redis"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  engine_version       = "7.1"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis.id]

  tags = {
    Name = "finops-${var.environment}-redis"
  }
}
