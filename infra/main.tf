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

# The one thing the CI deploy role may run on the box (see the deploy workflow): check out a commit
# and run its scripts/deploy.sh. A fixed command with validated parameters, rather than letting CI
# send arbitrary shell. The parameters are checked against allowedPattern before SSM substitutes
# them, so nothing but 40 hex digits and a hostname ever reaches the shell. Fetching first means
# the deploy script that runs is the one from the commit being deployed. Runs as root, drops to
# `ubuntu` (a login shell, so the docker group applies).
resource "aws_ssm_document" "deploy" {
  name            = "${local.name}-deploy"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Deploy a commit of solar-map to ${local.name}"
    parameters = {
      sha = {
        type           = "String"
        description    = "Full git commit sha to deploy (its image must already be in GHCR)."
        allowedPattern = "^[0-9a-f]{40}$"
      }
      siteAddress = {
        type           = "String"
        description    = "Public hostname (SITE_ADDRESS); only used when creating backend/.env."
        default        = local.fqdn
        allowedPattern = "^[a-z0-9.-]+$"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = {
        timeoutSeconds = "1800"
        runCommand = [
          "set -eu",
          "su - ubuntu -c 'cd /home/ubuntu/solar-map && git fetch --quiet origin && git checkout --quiet --detach {{sha}} && scripts/deploy.sh {{sha}} {{siteAddress}}'",
        ]
      }
    }]
  })
}

# --- CI deploys --------------------------------------------------------------------------------
# GitHub Actions deploys by assuming this role with its OIDC token (no stored credentials) and
# sending the deploy document above to this environment's instance. The OIDC provider itself is
# account-wide and created once by infra/bootstrap: apply that first (`task tf:bootstrap`).

data "aws_caller_identity" "current" {}

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# Only workflow runs that target this environment's GitHub Environment (deploy.yml sets
# `environment: <env>`) can assume the role, so a dev job can never act on prod.
data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:environment:${local.env}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name}-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

data "aws_iam_policy_document" "github_deploy" {
  # Run this environment's deploy document, and only on this environment's node: registered nodes
  # carry the activation's tags, which is what scopes the second statement.
  statement {
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:document/${aws_ssm_document.deploy.name}"]
  }
  statement {
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:managed-instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Environment"
      values   = [local.env]
    }
  }
  # Read-only: find the node, follow the command it sent and read its output. These actions don't
  # support resource-level scoping.
  statement {
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands",
      "ssm:DescribeInstanceInformation",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
