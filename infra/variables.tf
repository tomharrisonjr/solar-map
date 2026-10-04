variable "aws_region" {
  description = "Region for Lightsail (it is regional). Route 53 is global."
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "AWS CLI profile to use; null uses the default credential chain."
  type        = string
  default     = null
}

variable "domain" {
  description = "Existing Route 53 hosted zone (apex domain)."
  type        = string
  default     = "tomharrisonjr.com"
}

variable "subdomain" {
  description = "Record name within the zone; the site is served at <subdomain>.<domain>. Set per environment in envs/<env>.tfvars (no default, so an environment can't silently reuse another's hostname)."
  type        = string
}

variable "alias" {
  description = "Optional friendlier public name (a record name in the zone, e.g. \"solar-map\"). When set it is the site's real hostname (SITE_ADDRESS) and CNAMEs to <subdomain>.<domain>, which then only redirects to it."
  type        = string
  default     = null

  validation {
    condition     = var.alias == null || var.alias != var.subdomain
    error_message = "alias can't equal subdomain: the subdomain already has the A record."
  }
}

variable "ssh_public_key_path" {
  description = "Path to the public key file allowed to SSH in as `ubuntu`."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to reach SSH (port 22), e.g. your home IP as 203.0.113.7/32."
  type        = string

  validation {
    condition     = can(cidrhost(var.ssh_allowed_cidr, 0)) && var.ssh_allowed_cidr != "0.0.0.0/0"
    error_message = "Must be a valid IPv4 CIDR and must not be 0.0.0.0/0."
  }
}

variable "bundle_id" {
  description = "Lightsail bundle. small_3_0 = 2 GB RAM, 2 vCPU, 60 GB SSD (~$12/mo, with public IPv4)."
  type        = string
  default     = "small_3_0"
}

variable "repo_url" {
  description = "Git repository cloned onto the instance (public, so no credentials are needed)."
  type        = string
  default     = "https://github.com/tomharrisonjr/solar-map.git"
}
