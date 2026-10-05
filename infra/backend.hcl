# Partial S3 backend config for the main stack (the rest is in versions.tf). Not secret. The bucket
# is created by infra/bootstrap (`task tf:bootstrap`); credentials come from AWS_PROFILE.
bucket = "solar-map-tfstate-205850614818"
region = "us-east-2"
