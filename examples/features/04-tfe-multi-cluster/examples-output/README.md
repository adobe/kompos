# Example Generated Outputs

This directory contains example outputs to show you what `kompos tfe generate` produces.

## Dev Cluster (demo-dev-usw2-cluster-01)

### provider.tf.json

```json
{
  "provider": {
    "aws": {
      "region": "us-west-2",
      "assume_role": {
        "role_arn": "arn:aws:iam::111122223333:role/TerraformExecutionRole"
      }
    }
  },
  "terraform": {
    "backend": {
      "s3": {
        "bucket": "terraform-state-demo-account",
        "key": "demo-dev-usw2-cluster-01/terraform.tfstate",
        "region": "us-west-2",
        "encrypt": true,
        "dynamodb_table": "terraform-locks"
      }
    }
  }
}
```

### main.tf (excerpt - showing resolved versions)

```hcl
# VPC Module with versioned source
module "vpc" {
  # DEV uses latest: v5.1.2
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=v5.1.2"
  
  name = var.config.cluster.fullName
  cidr = var.config.vpc.cidr_block
  # ... rest of config
}

# EKS Module with versioned source
module "eks" {
  # DEV uses latest: v19.16.0
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-eks.git?ref=v19.16.0"
  
  cluster_name    = var.config.cluster.fullName
  cluster_version = var.config.eks.cluster_version  # "1.28"
  # ... rest of config
}
```

## Prod Cluster (demo-prod-use1-cluster-02)

### provider.tf.json

```json
{
  "provider": {
    "aws": {
      "region": "us-east-1",
      "assume_role": {
        "role_arn": "arn:aws:iam::111122223333:role/TerraformExecutionRole"
      }
    }
  },
  "terraform": {
    "backend": {
      "s3": {
        "bucket": "terraform-state-demo-account",
        "key": "demo-prod-use1-cluster-02/terraform.tfstate",
        "region": "us-east-1",
        "encrypt": true,
        "dynamodb_table": "terraform-locks"
      }
    }
  }
}
```

### main.tf (excerpt - showing resolved versions)

```hcl
# VPC Module with versioned source
module "vpc" {
  # PROD uses stable: v5.1.0 (one version behind dev)
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=v5.1.0"
  
  name = var.config.cluster.fullName
  cidr = var.config.vpc.cidr_block
  # ... rest of config
}

# EKS Module with versioned source
module "eks" {
  # PROD uses stable: v19.15.0 (one version behind dev)
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-eks.git?ref=v19.15.0"
  
  cluster_name    = var.config.cluster.fullName
  cluster_version = var.config.eks.cluster_version  # "1.27"
  # ... rest of config
}
```

## Key Differences

| Aspect          | Dev Cluster                  | Prod Cluster                  |
|-----------------|------------------------------|-------------------------------|
| **Region**      | us-west-2                    | us-east-1                     |
| **VPC Module**  | v5.1.2                       | v5.1.0                        |
| **EKS Module**  | v19.16.0                     | v19.15.0                      |
| **K8s Version** | 1.28                         | 1.27                          |
| **Backend Key** | demo-dev-usw2-cluster-01/... | demo-prod-use1-cluster-02/... |

All from the same source `main.tf.versioned` file!

## Generate These Yourself

```bash
# Dev cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=terraform tfe generate

# Prod cluster
kompos data/cloud=aws/project=demo/env=prod/region=us-east-1/cluster=demo-cluster-02/composition=terraform tfe generate

# Compare output
diff generated/clusters/demo-dev-usw2-cluster-01/main.tf \
     generated/clusters/demo-prod-use1-cluster-02/main.tf
```

You'll see:

- Different module versions (v5.1.2 vs v5.1.0, v19.16.0 vs v19.15.0)
- Different regions in provider variable values (generated.tfvars.yaml)
- Different backend state keys
- Same structure, different runtime values

