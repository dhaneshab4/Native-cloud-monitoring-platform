// Jenkins runs the same gates as .github/workflows/ci.yml, then does the one
// thing GitHub Actions deliberately does not: it writes the promotion commit.
//
// The split matters. CI builds and proves an artifact; it never talks to the
// cluster. Delivery happens because Argo CD notices a commit changed the image
// tag in Git. Jenkins' deploy stage is therefore a `git commit`, not a
// `kubectl apply` — so the cluster state is always what main says it is, even
// if Jenkins is offline.
//
// Credentials expected in Jenkins:
//   aws-ecr           — AWS credentials (or use an IRSA-annotated agent)
//   github-token      — write access, for the promotion commit
//   argocd-auth-token — Argo CD API token, for the sync/wait

pipeline {
  agent {
    kubernetes {
      yaml '''
        apiVersion: v1
        kind: Pod
        spec:
          serviceAccountName: jenkins-agent
          containers:
            - name: python
              image: python:3.12-slim
              command: ["cat"]
              tty: true
            - name: buildkit
              image: moby/buildkit:v0.17.2-rootless
              securityContext:
                seccompProfile: {type: Unconfined}
                appArmorProfile: {type: Unconfined}
                runAsUser: 1000
                runAsGroup: 1000
              command: ["cat"]
              tty: true
            - name: tools
              image: alpine/k8s:1.31.3
              command: ["cat"]
              tty: true
      '''
    }
  }

  options {
    timeout(time: 45, unit: 'MINUTES')
    disableConcurrentBuilds(abortPrevious: true)
    buildDiscarder(logRotator(numToKeepStr: '30'))
    timestamps()
  }

  environment {
    AWS_REGION  = 'eu-west-1'
    ECR_REGISTRY = credentials('ecr-registry-url')   // <acct>.dkr.ecr.eu-west-1.amazonaws.com
    IMAGE_NAME  = 'cloud-native-monitoring-app'
    // Immutable, traceable tag. `latest` tells you nothing six weeks later.
    IMAGE_TAG   = "v${env.BUILD_NUMBER}-${env.GIT_COMMIT?.take(7)}"
  }

  stages {

    stage('Lint') {
      steps {
        container('python') {
          sh '''
            pip install --quiet -r requirements-dev.txt
            ruff check app tests
            ruff format --check app tests
          '''
        }
      }
    }

    stage('Test') {
      // The same four interpreters the GitHub matrix covers. Running them in
      // parallel keeps this stage at the cost of the slowest, not the sum.
      matrix {
        axes {
          axis {
            name 'PY'
            values '3.11', '3.12', '3.13', '3.14'
          }
        }
        stages {
          stage('pytest') {
            steps {
              container('python') {
                sh """
                  python -m venv /tmp/venv-${PY}
                  /tmp/venv-${PY}/bin/pip install --quiet -r requirements-dev.txt
                  /tmp/venv-${PY}/bin/pytest -q \
                    --cov=app --cov-report=xml:coverage-${PY}.xml \
                    --cov-fail-under=90 \
                    --junitxml=junit-${PY}.xml
                """
              }
            }
            post {
              always {
                junit allowEmptyResults: true, testResults: "junit-${PY}.xml"
              }
            }
          }
        }
      }
    }

    stage('Validate manifests') {
      steps {
        container('tools') {
          sh '''
            helm lint charts/monitoring-app \
              --values charts/monitoring-app/values.yaml \
              --values charts/monitoring-app/values-prod.yaml

            # Render both environments and validate the actual output, not the
            # templates. A chart can lint clean and still emit invalid objects.
            for env in dev prod; do
              helm template monitoring-app-$env charts/monitoring-app \
                --api-versions monitoring.coreos.com/v1 --api-versions argoproj.io/v1alpha1 \
                --values charts/monitoring-app/values.yaml \
                --values charts/monitoring-app/values-$env.yaml \
                > /tmp/rendered-$env.yaml
            done

            kubeconform -strict -summary -ignore-missing-schemas \
              -schema-location default \
              -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
              /tmp/rendered-dev.yaml /tmp/rendered-prod.yaml
          '''
        }
      }
    }

    stage('Build and push') {
      when { branch 'main' }
      steps {
        container('buildkit') {
          withCredentials([usernamePassword(
            credentialsId: 'aws-ecr',
            usernameVariable: 'AWS_ACCESS_KEY_ID',
            passwordVariable: 'AWS_SECRET_ACCESS_KEY')]) {
            sh '''
              mkdir -p ~/.docker
              buildctl-daemonless.sh build \
                --frontend dockerfile.v0 \
                --local context=. \
                --local dockerfile=. \
                --opt target=runtime \
                --opt platform=linux/amd64,linux/arm64 \
                --output type=image,name=${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG},push=true \
                --export-cache type=inline
            '''
          }
        }
      }
    }

    stage('Scan') {
      when { branch 'main' }
      steps {
        container('tools') {
          // Fails the build on a fixable HIGH or CRITICAL. Unfixed findings are
          // reported but do not block — there is nothing to upgrade to.
          sh '''
            trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed \
              --format table ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
          '''
        }
      }
    }

    stage('Sign and attest') {
      when { branch 'main' }
      steps {
        container('tools') {
          sh '''
            DIGEST=$(crane digest ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG})
            # Sign the digest, never the tag — tags are mutable and can be
            # repointed at a different image after the signature is made.
            cosign sign --yes "${ECR_REGISTRY}/${IMAGE_NAME}@${DIGEST}"
            syft "${ECR_REGISTRY}/${IMAGE_NAME}@${DIGEST}" -o spdx-json > sbom.spdx.json
            cosign attest --yes --predicate sbom.spdx.json --type spdxjson \
              "${ECR_REGISTRY}/${IMAGE_NAME}@${DIGEST}"
            echo "${DIGEST}" > image-digest.txt
          '''
          archiveArtifacts artifacts: 'sbom.spdx.json,image-digest.txt', fingerprint: true
        }
      }
    }

    stage('Promote to dev') {
      when { branch 'main' }
      steps {
        container('tools') {
          withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
            // The deploy IS this commit. Argo CD is watching main and will pick
            // it up within its reconcile interval — nothing here touches the cluster.
            sh '''
              yq -i '.image.tag = strenv(IMAGE_TAG)' charts/monitoring-app/values-dev.yaml
              git config user.email "jenkins@ci.local"
              git config user.name  "jenkins"
              git add charts/monitoring-app/values-dev.yaml
              git commit -m "chore(dev): promote ${IMAGE_TAG} [skip ci]" || exit 0
              git push https://${GH_TOKEN}@github.com/dhaneshab4/cloud-native-monitoring-platform.git HEAD:main
            '''
          }
        }
      }
    }

    stage('Verify dev converged') {
      when { branch 'main' }
      steps {
        container('tools') {
          withCredentials([string(credentialsId: 'argocd-auth-token', variable: 'ARGOCD_AUTH_TOKEN')]) {
            sh '''
              argocd app wait monitoring-app-dev \
                --server argocd.argocd.svc.cluster.local \
                --grpc-web --health --sync --timeout 300
            '''
          }
        }
      }
    }

    stage('Promote to production') {
      when { branch 'main' }
      steps {
        // The gate is a person. Everything below is still declarative — the
        // approval produces a commit, and Argo CD does the rest.
        timeout(time: 24, unit: 'HOURS') {
          input message: "Promote ${env.IMAGE_TAG} to production?", ok: 'Promote'
        }
        container('tools') {
          withCredentials([
            string(credentialsId: 'github-token', variable: 'GH_TOKEN'),
            string(credentialsId: 'argocd-auth-token', variable: 'ARGOCD_AUTH_TOKEN')]) {
            sh '''
              # The approval gate can sit for hours; main may have moved on.
              git pull --rebase https://${GH_TOKEN}@github.com/dhaneshab4/cloud-native-monitoring-platform.git main
              yq -i '.image.tag = strenv(IMAGE_TAG)' charts/monitoring-app/values-prod.yaml
              git add charts/monitoring-app/values-prod.yaml
              git commit -m "chore(prod): promote ${IMAGE_TAG}"
              git push https://${GH_TOKEN}@github.com/dhaneshab4/cloud-native-monitoring-platform.git HEAD:main

              argocd app sync monitoring-app-prod --grpc-web --timeout 600
              # Canary steps take minutes; wait for the Rollout to finish rather
              # than declaring success the moment the sync is accepted.
              argocd app wait monitoring-app-prod --grpc-web --health --timeout 1800
            '''
          }
        }
      }
    }
  }

  post {
    failure {
      echo "Failed at ${env.STAGE_NAME}. Image ${env.IMAGE_TAG} was not promoted."
    }
    cleanup {
      cleanWs()
    }
  }
}
