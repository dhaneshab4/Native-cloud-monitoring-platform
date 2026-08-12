# The dev environment: VPC, EKS, ECR and the IAM roles the in-cluster
# controllers need. Argo CD is deliberately NOT installed here — Terraform owns
# the infrastructure, Argo CD owns everything running on it, and the handoff is
# the two kubectl commands in gitops/bootstrap/README.md.
#
#   terraform init
#   terraform plan  -var-file=terraform.tfvars
#   terraform apply -var-file=terraform.tfvars
#   aws eks update-kubeconfig --name monitoring-dev --region eu-west-1

data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  tags = {
    Environment = var.environment
    Cluster     = var.cluster_name
  }
}

# --------------------------------------------------------------------- network
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true
  enable_dns_support   = true

  # The load balancer controller discovers where to place LBs from these tags.
  # Without them, a Service of type LoadBalancer sits in pending forever.
  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }

  tags = local.tags
}

# ----------------------------------------------------------------------- eks
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.cluster_public_access_cidrs
  cluster_endpoint_private_access      = true

  # Without this the identity that ran `apply` has no cluster access and you
  # are locked out of the cluster you just created.
  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Control plane logs cost money; api and audit are the two worth paying for.
  cluster_enabled_log_types = ["api", "audit"]

  # The EBS CSI driver is deliberately NOT here. Its addon needs an IRSA role,
  # and that role needs this module's OIDC provider — declaring it inside
  # cluster_addons makes the eks module depend on a role that depends on the eks
  # module, which Terraform can resolve into a cycle. It is created as a
  # standalone aws_eks_addon below instead, after both exist.
  cluster_addons = {
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true, before_compute = true }
    eks-pod-identity-agent = { most_recent = true }
  }

  eks_managed_node_groups = {
    default = {
      instance_types = var.node_instance_types
      capacity_type  = var.node_capacity_type

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      # gp3 is cheaper and faster than the gp2 default, and encrypted at rest.
      block_device_mappings = {
        root = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 40
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }

      labels = { workload = "general" }
      tags   = local.tags
    }
  }

  tags = local.tags
}

# ---------------------------------------------------------------------- ecr
module "ecr" {
  source = "../../modules/ecr"

  name = "cloud-native-monitoring-app"
  tags = local.tags

  # The nodes pull images, so the node role needs read access on the registry.
  pull_principal_arns = [module.eks.eks_managed_node_groups["default"].iam_role_arn]
}

# ---------------------------------------------------------------------- iam
# IRSA over static keys throughout: pods assume a role through the cluster's
# OIDC provider, so there is no long-lived secret to leak or rotate.

module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name             = "${var.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.tags
}

# Created after the cluster and its node group, so the controller has somewhere
# to schedule and a role to assume the moment it starts.
resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = module.ebs_csi_irsa.iam_role_arn

  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  depends_on = [module.eks]

  tags = local.tags
}

# A gp3 StorageClass belongs here in cost terms — but it is an in-cluster object,
# and in-cluster objects are Argo CD's job. Putting it in Terraform would need a
# kubernetes provider configured from this module's own outputs, which does not
# exist on the first apply. It ships as a manifest instead.

module "external_secrets_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name                      = "${var.cluster_name}-external-secrets"
  attach_external_secrets_policy = true

  external_secrets_secrets_manager_arns = [
    "arn:aws:secretsmanager:${var.region}:*:secret:${var.environment}/monitoring/*",
  ]

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-secrets:external-secrets"]
    }
  }

  tags = local.tags
}

# The application's own role. It needs nothing today, which is exactly the
# permission set it should start with — additions become reviewable diffs.
module "app_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name = "monitoring-app-${var.environment}"

  oidc_providers = {
    main = {
      provider_arn = module.eks.oidc_provider_arn
      namespace_service_accounts = [
        "monitoring-dev:monitoring-app-dev",
        "monitoring-prod:monitoring-app-prod",
      ]
    }
  }

  tags = local.tags
}
