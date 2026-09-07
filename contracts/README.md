# API contracts

The backend OpenAPI documents are the only HTTP contract source.

Generated snapshots belong under `contracts/generated/` and are recreated by the backend export command during CI. User and admin clients must be generated from the locked snapshots; handwritten duplicate DTOs are not accepted.

Compatibility policy:

- Additive fields and endpoints are released by the backend first.
- Removing a field, narrowing a type, changing a status code, or changing semantics is breaking.
- Breaking changes require a parallel compatible version and a documented migration window.
- The suite CI compares the generated snapshot with the committed release snapshot before a project-set tag is produced.

