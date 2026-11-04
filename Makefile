QS = docker compose -f docker-compose.quickstart.yml
.PHONY: env up down logs upgrade reset images images-multiarch test
env:              ## 生成带随机密钥的 .env
	sh scripts/gen-env.sh
up:               ## 拉取镜像并启动
	$(QS) up -d
down:             ## 停止（保留数据）
	$(QS) down
logs:
	$(QS) logs -f gate
upgrade:          ## 升级到最新镜像
	$(QS) pull && $(QS) up -d
reset:            ## 停止并删除全部数据（不可恢复）
	$(QS) down -v
images:           ## 本机架构本地构建
	$(QS) build
images-multiarch: ## amd64 + arm64 多架构构建（需 buildx）
	docker buildx bake
test:
	python -m pytest -q
