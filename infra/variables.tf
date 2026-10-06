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
  description = "Record name within the zone (may contain dots); the site is served at <subdomain>.<domain>. Set per environment in envs/<env>.tfvars (no default, so an environment can't silently reuse another's hostname): \"solar-map\" for prod, \"dev.solar-map\" etc. for the rest."
  type        = string
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
