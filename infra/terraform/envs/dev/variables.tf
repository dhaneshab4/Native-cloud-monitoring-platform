variable "region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-1" # Dublin
}

variable "environment" {
  description = "Environment name, used in resource names and tags"
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "monitoring-dev"
}

variable "kubernetes_version" {
  description = "EKS control plane version. Bump deliberately, one minor at a time."
  type        = string
  default     = "1.31"
}

variable "vpc_cidr" {
  description = "CIDR for the cluster VPC"
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be valid CIDR notation, e.g. 10.20.0.0/16."
  }
}

variable "az_count" {
  description = "Number of availability zones. Three for quorum, two to save money."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "node_instance_types" {
  description = "Instance types for the managed node group"
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_capacity_type" {
  description = "ON_DEMAND or SPOT. SPOT roughly halves the bill for a dev cluster."
  type        = string
  default     = "SPOT"

  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.node_capacity_type)
    error_message = "node_capacity_type must be ON_DEMAND or SPOT."
  }
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 4
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "cluster_public_access_cidrs" {
  description = "Who may reach the public API endpoint. Narrow this to your IP/32."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "single_nat_gateway" {
  description = "One NAT gateway instead of one per AZ. Saves ~£30/month, costs AZ redundancy."
  type        = bool
  default     = true
}
