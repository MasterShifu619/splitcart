variable "splitwise_consumer_key" { sensitive = true }
variable "splitwise_consumer_secret" { sensitive = true }
variable "splitwise_bearer_token" { sensitive = true }
variable "splitwise_group_id" {}
variable "splitwise_user_ids" {}
variable "card_to_user" { sensitive = true }
variable "gmail_shared_inbox" { default = "groceries.split@gmail.com" }
variable "aws_region" { default = "us-east-1" }
