output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "ecr_repository_url" {
  description = "Tag and push against this; also the image.repository Helm value"
  value       = module.ecr.repository_url
}

output "app_irsa_role_arn" {
  description = "Set as eks.amazonaws.com/role-arn on the app service account"
  value       = module.app_irsa.iam_role_arn
}

output "external_secrets_irsa_role_arn" {
  value = module.external_secrets_irsa.iam_role_arn
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "kubeconfig_command" {
  description = "Run this to point kubectl at the new cluster"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}
