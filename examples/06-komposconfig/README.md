# Feature: TFE Nested Output Path (`nested_subdir`)

## What This Shows

By default, `tfe generate` writes terraform files directly into the composition instance directory:

```
generated/
  clusters/
    my-cluster-dev-usw2/
      main.tf
      generated.tfvars.yaml
```

With `nested_subdir: "tfe"` in `.komposconfig.yaml`, all TFE-generated files are nested one level deeper:

```
generated/
  clusters/
    my-cluster-dev-usw2/
      tfe/               ← all TFE files go here
        main.tf
        generated.tfvars.yaml
  workspaces/
    my-cluster-dev-usw2.workspace.yaml
```

## Why

This is useful when the cluster's `generated/` directory is shared between multiple generators (e.g., kompos also writes `argoapps/` and `outputs/` subdirectories for helm and infra outputs). Isolating terraform files under `tfe/` keeps each generator's output cleanly separated.

The TFE workspace `working_directory` must match — it tells Terraform Cloud/Enterprise where to find the `.tf` files in the git repo:

```yaml
# composition.yaml
workspace:
  working_directory: "generated/clusters/{{cluster.fullName}}/tfe"
```

## How It Works

`.komposconfig.yaml`:
```yaml
tfe:
  generation_config:
    nested_subdir: "tfe"   # ← adds /tfe after the instance dir
```

## Try It

```bash
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=my-cluster/composition=cluster \
    tfe generate
```

Expected output:
```
Target: ./generated/clusters/my-cluster-dev-usw2/tfe
✓ Composition files copied
✓ tfvars: ./generated/clusters/my-cluster-dev-usw2/tfe/generated.tfvars.yaml
```
