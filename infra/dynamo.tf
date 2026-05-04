resource "aws_dynamodb_table" "processed_orders" {
  name         = "processed_orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "email_id"

  attribute {
    name = "email_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Project = "splitcart"
  }
}
