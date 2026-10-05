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
