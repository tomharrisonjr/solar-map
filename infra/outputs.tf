output "environment" {
  value = local.env
}

output "static_ip" {
  description = "Public IPv4 of the instance."
  value       = aws_lightsail_static_ip.this.ip_address
}

output "site_url" {
  description = "The public URL people use."
  value       = "https://${local.fqdn}"
}

output "site_address" {
  description = "Value for SITE_ADDRESS in the server's backend/.env."
  value       = local.fqdn
}

output "ssm_command" {
  description = "Open a shell on the instance (needs the Session Manager plugin); same as `task ssm ENV=<env>`."
  value       = "task ssm ENV=${local.env}"
}

output "aws_region" {
  description = "Region the instance and its SSM node live in."
  value       = var.aws_region
}

output "deploy_document" {
  description = "SSM document the CI deploy role runs on this environment's instance."
  value       = aws_ssm_document.deploy.name
}

output "deploy_role_arn" {
  description = "Role the deploy workflow assumes via OIDC; stored as the AWS_DEPLOY_ROLE_ARN variable of the GitHub environment (`task gh:env`)."
  value       = aws_iam_role.github_deploy.arn
}
