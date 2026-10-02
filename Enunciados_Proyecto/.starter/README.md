# Starter local (gratis) — LocalStack
Practica CloudFormation y servicios AWS **en tu máquina, sin gastar**:
1. `docker compose up -d` → espera ~20s
2. `awslocal s3 ls` (endpoint local: http://localhost:4566)
3. El stack demo se creó solo: `awslocal cloudformation describe-stacks`
Ideal para probar templates antes de ir a la cuenta real de AWS Academy.
