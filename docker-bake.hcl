# 多架构构建：docker buildx bake            （只构建，不推送）
#            docker buildx bake --push     （推送到 GHCR，需先 docker login ghcr.io）
variable "TAG" { default = "latest" }
variable "REGISTRY" { default = "ghcr.io/chenfyuan" }
group "default" { targets = ["gateway"] }
target "gateway" {
  context   = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags      = ["${REGISTRY}/autollm-gate-gateway:${TAG}"]
}
