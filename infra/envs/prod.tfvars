# Per-environment settings (non-secret, committed). Selected by `ENV=<env>` in the tf:* tasks.
subdomain = "solar-map-prod"

# The public name: a CNAME to the one above. The app serves it; the env-specific name redirects.
alias = "solar-map"
