## Rendering pipeline (last wins)

```
  configs/ hierarchy          tfe-outputs.yaml
         |                          |
         v                          v
  +--------------+    +----------------+    +-----------------------+
  | 1. Hierarchy |--->| 2. TFE Outputs |--->| 3. Bridge             |
  |    walk      |    |    merge       |    |    {bridge_filename:<20}|
  +--------------+    +----------------+    +-----------+-----------+
                                                        |
                                            +-----------+-----------+
                                            | 4. Cross-env defaults |
                                            |    {overrides_subdir}/default.yaml
                                            +-----------+-----------+
                                                        |
                                            +-----------+-----------+
                                            | 5. Env override       |
                                            |    {overrides_subdir}/{{env}}.yaml
                                            +-----------+-----------+
                                                        |
                                            +-----------+-----------+
                                            | 6. Cluster override   |
                                            |    {overrides_subdir}/{cluster_override_label}
                                            |    (WINS on conflict) |
                                            +-----------+-----------+
                                                        |
                                                        v
                                                   OUTPUT
```

Each step merges on top of the previous — last value for a key wins.
Missing files are skipped (each override layer is optional).
