Note that you need the `.komposconfig.yaml` file (which is already present in this folder) for this to work.

1. Run 'terraform plan' for all compositions for a given cluster:
```sh
# generates config and runs terraform
kompos config/env=dev/cluster=cluster1 terraform plan
```

2. Run 'terraform apply' for all compositions for a given cluster:
```sh
kompos config/env=dev/cluster=cluster1 terraform apply --skip-plan
```

3. Run a single composition:
```sh
kompos config/env=dev/cluster=cluster1/composition=network terraform apply --skip-plan
```

4. If you only want to generate and view the config you can run:
```sh
kompos config/env=dev/cluster=cluster1/composition=network config
```
