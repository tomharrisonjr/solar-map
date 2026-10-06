locals {
  # One workspace per environment; every resource is named after it so they never collide.
  # Lightsail names are unique across resource types within a region, hence the -ip suffix.
  environments = ["dev", "staging", "prod"]
  env          = terraform.workspace
  name         = "solar-map-${local.env}"
  # The site's one public name (SITE_ADDRESS): prod is the bare "solar-map", the others sit under
  # it ("dev.solar-map"), so a single Stadia registration of the prod name covers every env.
  fqdn = "${var.subdomain}.${var.domain}"
}

resource "aws_lightsail_instance" "this" {
  name              = local.name
  availability_zone = "${var.aws_region}a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = var.bundle_id

  # Runs once on first boot. Registers the box with SSM (the only way in: there is no SSH), then
  # installs Docker and clones the repo. It deliberately writes no app secrets (they would end up
  # in Terraform state): create backend/.env by hand afterwards. The SSM activation id/code do land
  # in state, but they only allow a machine to register against this env's role, and expire.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url        = var.repo_url
    aws_region      = var.aws_region
    activation_id   = aws_ssm_activation.this.id
    activation_code = aws_ssm_activation.this.activation_code
  })

  # Daily snapshot, last 7 kept (Lightsail's AutoSnapshot cadence is fixed at daily). The
  # database is rebuildable from USPVDB, so this mainly protects backend/.env and Caddy's certs.
  add_on {
    type          = "AutoSnapshot"
    snapshot_time = "06:00" # UTC
    status        = "Enabled"
  }

  # Editing user_data or the blueprint would replace the box (and its data); don't do that
  # by accident. Rebuild deliberately with `task tf:rebuild ENV=<env>`, which also replaces the
  # SSM activation: its code expires, so a new box needs a fresh one.
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
  name = "${local.name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "this" {
  static_ip_name = aws_lightsail_static_ip.this.name
  instance_name  = aws_lightsail_instance.this.name
}

# Web only. There is deliberately no port 22: shell access is SSM Session Manager (`task ssm`),
# authorised by IAM. Break-glass if the agent won't register: open 22 temporarily in the Lightsail
# console, then re-apply to close it again.
resource "aws_lightsail_instance_public_ports" "this" {
  instance_name = aws_lightsail_instance.this.name

  # The rules attach by instance *name*, which survives a rebuild, so Terraform would see no change
  # and leave the new box on Lightsail's default firewall (22 and 80 open, 443 closed). Re-apply
  # them whenever the instance itself is replaced.
  lifecycle {
    replace_triggered_by = [aws_lightsail_instance.this.id]
  }

  port_info {
    protocol          = "tcp"
    from_port         = 80
    to_port           = 80
    cidrs             = ["0.0.0.0/0"]
    ipv6_cidrs        = ["::/0"]
    cidr_list_aliases = []
  }

  port_info {
    protocol          = "tcp"
    from_port         = 443
    to_port           = 443
    cidrs             = ["0.0.0.0/0"]
    ipv6_cidrs        = ["::/0"]
    cidr_list_aliases = []
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

# Shell access without SSH. Lightsail instances can't take an instance profile, so they join
# Systems Manager as "hybrid" managed nodes: the activation below lets the agent on the box
# register itself against this role, after which `aws ssm start-session` works with plain IAM
# permissions and no inbound ports. Standard-tier activations are free.
data "aws_iam_policy_document" "ssm_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ssm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ssm" {
  name               = "${local.name}-ssm"
  assume_role_policy = data.aws_iam_policy_document.ssm_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# `task ssm` finds the registered node by this env's role name (SSM can't filter nodes by tag).
# Expires after 24h by default, so it must be replaced together with the instance (tf:rebuild).
resource "aws_ssm_activation" "this" {
  name               = local.name
  description        = "Registers the ${local.name} Lightsail instance with Systems Manager"
  iam_role           = aws_iam_role.ssm.id
  registration_limit = 5
  tags = {
    Name = local.name
  }
  depends_on = [aws_iam_role_policy_attachment.ssm]
}
