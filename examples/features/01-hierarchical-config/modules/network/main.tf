variable "config" {}

locals {
  env     = var.config["env"]
  region  = var.config["region"]["location"]
  project = var.config["project"]["prefix"]
}
