resource "aws_cloudwatch_event_rule" "every_10_minutes" {
  name                = "splitcart-poll"
  schedule_expression = "rate(10 minutes)"
}

resource "aws_cloudwatch_event_target" "splitcart_lambda" {
  rule      = aws_cloudwatch_event_rule.every_10_minutes.name
  target_id = "splitcart"
  arn       = aws_lambda_function.splitcart.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.splitcart.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_10_minutes.arn
}
