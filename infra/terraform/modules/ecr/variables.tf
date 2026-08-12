variable "name" {
  description = "Repository name"
  type        = string
}

variable "keep_release_images" {
  description = "How many v-prefixed release images to retain"
  type        = number
  default     = 20
}

variable "untagged_retention_days" {
  description = "Days before untagged layers are expired"
  type        = number
  default     = 7
}

variable "pull_principal_arns" {
  description = "IAM principals granted pull access; empty means account-only via IAM"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to the repository"
  type        = map(string)
  default     = {}
}
