resource "null_resource" "install_deps" {
  triggers = {
    requirements = filemd5("${path.module}/../requirements.txt")
  }
  provisioner "local-exec" {
    command = <<-EOT
      rm -rf ${path.module}/build
      pip install -r ${path.module}/../requirements.txt -t ${path.module}/build/ --quiet
      cp ${path.module}/../*.py ${path.module}/build/
      [ -f ${path.module}/../credentials.json ] && cp ${path.module}/../credentials.json ${path.module}/build/ || true
      [ -f ${path.module}/../token.json ] && cp ${path.module}/../token.json ${path.module}/build/ || true
      mkdir -p ${path.module}/build/profiles && cp ${path.module}/../profiles/*.json ${path.module}/build/profiles/
    EOT
  }
}

data "archive_file" "splitcart" {
  depends_on  = [null_resource.install_deps]
  type        = "zip"
  source_dir  = "${path.module}/build/"
  output_path = "${path.module}/splitcart.zip"
}

resource "aws_iam_role" "splitcart_lambda" {
  name = "splitcart-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "splitcart_dynamo" {
  name = "splitcart-dynamo"
  role = aws_iam_role.splitcart_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
      Resource = aws_dynamodb_table.processed_orders.arn
    }]
  })
}

resource "aws_iam_role_policy" "splitcart_bedrock" {
  name = "splitcart-bedrock"
  role = aws_iam_role.splitcart_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.splitcart_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "splitcart" {
  function_name    = "splitcart"
  role             = aws_iam_role.splitcart_lambda.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.splitcart.output_path
  source_code_hash = data.archive_file.splitcart.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      SPLITWISE_CONSUMER_KEY    = var.splitwise_consumer_key
      SPLITWISE_CONSUMER_SECRET = var.splitwise_consumer_secret
      SPLITWISE_BEARER_TOKEN    = var.splitwise_bearer_token
      SPLITWISE_GROUP_ID        = var.splitwise_group_id
      SPLITWISE_USER_IDS     = var.splitwise_user_ids
      CARD_TO_USER           = var.card_to_user
      GMAIL_SHARED_INBOX     = var.gmail_shared_inbox
      GMAIL_CREDENTIALS_JSON = "/var/task/credentials.json"
      GMAIL_TOKEN_JSON       = "/tmp/token.json"
      DYNAMODB_TABLE         = aws_dynamodb_table.processed_orders.name
      VOYAGE_API_KEY         = var.voyage_api_key
      PINECONE_API_KEY       = var.pinecone_api_key
      PINECONE_INDEX         = var.pinecone_index
      AWS_REGION_NAME        = var.aws_region
    }
  }

  tags = {
    Project = "splitcart"
  }
}
