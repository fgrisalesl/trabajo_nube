pipeline {
  agent any
  tools { } // Jenkins sobre la EC2 del proyecto: docker y pip disponibles ahí
  environment { IMAGEN = "gtn-app" }
  stages {
    stage('Validar IaC') {
      steps {
        sh 'pip install cfn-lint 2>/dev/null || pip3 install cfn-lint'
        sh 'cfn-lint iac/*.yaml'
      }
    }
    stage('Construir imagen') {
      steps { sh 'docker build -t $IMAGEN app/' }
    }
    stage('Desplegar') {
      steps { sh 'cd app && docker compose up -d --build' }
    }
  }
  post {
    success { echo 'Despliegue OK — verificar puerto 80' }
    failure { echo 'Pipeline falló — revisar logs' }
  }
}
