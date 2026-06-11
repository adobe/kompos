# VPC Module with versioned source
#
# This file uses {{vpc.module_version}} which will be interpolated
# at runtime with the value from hierarchical configuration.

module "vpc" {
  # Versioned module source - interpolated at runtime
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=v2.0.0-rc"

  # Regular Terraform variables from tfvars
  name = var.config.cluster
  cidr = var.config.vpc.cidr_block

  azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  enable_vpn_gateway = false

  tags = var.config.vpc.tags
}

