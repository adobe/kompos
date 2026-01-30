# HIML Interpolation Examples

This example demonstrates all HIML interpolation patterns used in Kompos.

## Directory Structure

```
02-himl-interpolation/
├── .komposconfig.yaml          # Defines composition properties for double interpolation
├── config/
│   ├── defaults.yaml           # Global defaults with all interpolation patterns
│   └── cloud=aws/
│       ├── cloud.yaml          # Cloud-specific with nested interpolation
│       └── env=prod/
│           ├── env.yaml        # Environment overrides
│           └── app.yaml        # Composition-specific with double interpolation
```

## Interpolation Patterns

### 1. Simple Interpolation: `{{key.path}}`
```yaml
cloud:
  name: aws
  full_name: "{{cloud.name}}-cloud"  # Result: aws-cloud
```

### 2. Multi-Level Interpolation
```yaml
project:
  name: myproject
  fqdn: "{{project.name}}.{{cloud.name}}.{{env.name}}.example.com"
  # Result: myproject.aws.prod.example.com
```

### 3. Nested Interpolation: `{{outer.{{inner}}}}`
Uses the result of one interpolation as a key for another:

```yaml
env:
  name: prod
  type_mapping:
    dev: development
    prod: production
  full_type: "{{env.type_mapping.{{env.name}}}}"
  # Step 1: {{env.name}} -> prod
  # Step 2: {{env.type_mapping.prod}} -> production
  # Result: production
```

### 4. Double Interpolation with Composition Type
Dynamic property lookup based on composition type:

```yaml
# In .komposconfig.yaml
compositions:
  properties:
    app:
      output_subdir: "applications"
      default_replicas: 3
    database:
      output_subdir: "databases"
      default_replicas: 5

# In config
composition:
  type: app

settings:
  output_dir: "{{komposconfig.compositions.properties.{{composition.type}}.output_subdir}}"
  # Step 1: {{composition.type}} -> app
  # Step 2: {{komposconfig.compositions.properties.app.output_subdir}} -> applications
  # Result: applications
```

### 5. Interpolation with Lists
```yaml
tags:
  - "cloud:{{cloud.name}}"
  - "env:{{env.name}}"
  - "fqdn:{{project.fqdn}}"  # Can reference already-interpolated values
```

### 6. Complex Nested Double Interpolation
Multiple levels in one expression:

```yaml
cloud:
  region: us-west-2

regions:
  us-west-2: or2
  region_code: "{{regions.{{cloud.region}}}}"  # Result: or2

project:
  full_fqdn: "{{project.name}}.{{regions.region_code}}.{{env.name}}.{{cloud.name}}.example.com"
  # Result: myproject.or2.prod.aws.example.com
```

### 7. Hierarchy Overrides Affect Interpolation
When you override a value in a more specific layer, interpolations using that value automatically update:

```yaml
# defaults.yaml
env:
  name: dev
project:
  fqdn: "{{project.name}}.{{env.name}}.example.com"  # myproject.dev.example.com

# env=prod/env.yaml
env:
  name: prod
# project.fqdn now becomes: myproject.prod.example.com (automatic!)
```

## Testing

Run tests to verify all interpolation patterns:

```bash
cd /Users/danielcoman/git/kompos
kompos examples/features/02-himl-interpolation/config/cloud=aws/env=prod config --format yaml
```

Expected results:
- Simple interpolations resolve correctly
- Nested interpolations work ({{outer.{{inner}}}})
- Double interpolations with composition.type work
- Complex multi-level interpolations resolve
- Hierarchy overrides affect interpolated values

## Key Takeaways

1. **Simple**: `{{key.path}}` - Direct value lookup
2. **Nested**: `{{outer.{{inner}}}}` - Use interpolation result as key
3. **Double**: `{{config.{{variable}}.property}}` - Dynamic property access
4. **Complex**: Multiple interpolations in one expression
5. **Hierarchy-aware**: Overrides automatically flow through interpolations
6. **Order matters**: Exclude happens before interpolation, filter happens after

