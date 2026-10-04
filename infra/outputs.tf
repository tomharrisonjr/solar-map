output "environment" {
  value = local.env
}

output "static_ip" {
  description = "Public IPv4 of the instance."
  value       = aws_lightsail_static_ip.this.ip_address
}

output "site_url" {
  description = "The public URL people use."
  value       = "https://${local.public_fqdn}"
}

output "site_address" {
  description = "Value for SITE_ADDRESS in the server's backend/.env."
  value       = local.public_fqdn
}

output "redirect_from" {
  description = "Value for REDIRECT_FROM in the server's backend/.env (null: no alias, so no redirect)."
  value       = var.alias == null ? null : local.fqdn
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_lightsail_static_ip.this.ip_address}"
}
