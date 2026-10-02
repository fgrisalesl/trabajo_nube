#!/bin/bash
# Se ejecuta solo al levantar LocalStack: crea un bucket de prueba desde CloudFormation local
awslocal cloudformation create-stack --stack-name demo-local --template-body file:///etc/localstack/init/ready.d/demo-template.yaml && echo "Stack demo listo"
