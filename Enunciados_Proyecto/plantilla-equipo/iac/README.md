# IaC — CloudFormation
- `main.yaml` es el punto de partida: **todo** el entorno debe poder crearse desde aquí (o desde un conjunto de templates encadenados).
- Convenciones: YAML, Parameters para todo lo variable, Outputs para lo que otras capas consuman.
- **Tags obligatorios** en TODOS los recursos: `Curso: GTN-2026-2`, `Equipo`, `Proyecto`, `Ambiente`.
- Validar antes de cada PR: `cfn-lint main.yaml` (el CI lo corre igual).
- Desplegar: `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-<equipo> --capabilities CAPABILITY_NAMED_IAM --parameter-overrides NombreEquipo=<equipo>`
- Destruir (¡siempre al terminar la sesión de trabajo!): `aws cloudformation delete-stack --stack-name gtn-<equipo>`
- Documenta aquí: costo estimado del stack y cómo reproducirlo desde cero.
