locals {
  # One workspace per environment; every resource is named after it so they never collide.
  environments = ["dev", "staging", "prod"]
  env          = terraform.workspace
  name         = "solar-map-${local.env}"
  # The env-specific name always exists (A record). With an alias, the alias is the public
  # name and the env-specific one only redirects to it.
  fqdn        = "${var.subdomain}.${var.domain}"
  public_fqdn = var.alias == null ? local.fqdn : "${var.alias}.${var.domain}"
}

resource "aws_lightsail_key_pair" "this" {
  name       = local.name
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_lightsail_instance" "this" {
  name              = local.name
  availability_zone = "${var.aws_region}a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.this.name

  # Runs once on first boot. Installs Docker and clones the repo; it deliberately writes no
  # secrets (they would end up in Terraform state): create backend/.env by hand afterwards.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url = var.repo_url
  })

  # Daily snapshot, last 7 kept (Lightsail's AutoSnapshot cadence is fixed at daily). The
  # database is rebuildable from USPVDB, so this mainly protects backend/.env and Caddy's certs.
  add_on {
    type          = "AutoSnapshot"
    snapshot_time = "06:00" # UTC
    status        = "Enabled"
  }

  # Editing user_data or the blueprint would replace the box (and its data); don't do that
  # by accident. Rebuild deliberately with `terraform apply -replace=aws_lightsail_instance.this`.
  lifecycle {
    ignore_changes = [user_data, blueprint_id]

    # Refuse the implicit `default` workspace (or a typo) so nothing is ever created un-namespaced.
    precondition {
      condition     = contains(local.environments, local.env)
      error_message = "Workspace \"${local.env}\" is not one of ${join(", ", local.environments)}. Use `task tf:plan ENV=dev` (or staging/prod)."
    }
  }
}

# A static IP survives instance replacement, so DNS never needs to change.
resource "aws_lightsail_static_ip" "this" {
  name = local.name
}

resource "aws_lightsail_static_ip_attachment" "this" {
  static_ip_name = aws_lightsail_static_ip.this.name
  instance_name  = aws_lightsail_instance.this.name
}

resource "aws_lightsail_instance_public_ports" "this" {
  instance_name = aws_lightsail_instance.this.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = [var.ssh_allowed_cidr]
  }

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }
}

data "aws_route53_zone" "this" {
  name         = var.domain
  private_zone = false
}

resource "aws_route53_record" "site" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 300
  records = [aws_lightsail_static_ip.this.ip_address]
}

# Optional friendlier public name: a CNAME to the env-specific record, so the IP lives in one
# place. The app serves this name; the env-specific one redirects to it (see the Caddyfile).
resource "aws_route53_record" "alias" {
  count = var.alias == null ? 0 : 1

  zone_id = data.aws_route53_zone.this.zone_id
  name    = "${var.alias}.${var.domain}"
  type    = "CNAME"
  ttl     = 300
  records = [aws_route53_record.site.fqdn]
}
