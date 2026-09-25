# 构建上下文为仓库根目录：
#   docker build -f frontend/Dockerfile --build-arg VITE_API_BASE=/api/v1 -t eorzea-frontend .
#
# 基础镜像与 npm 源均可通过 --build-arg 覆盖（docker-compose.yml 已给出国内默认值）：
#   NODE_IMAGE    Node 构建镜像（可指向国内镜像站）
#   NGINX_IMAGE   运行镜像
#   NPM_REGISTRY  npm 源（默认 npmmirror，置空则用官方源）
# 注意：基础镜像的 ARG 必须声明在第一个 FROM 之前（全局作用域），
# 否则后续 FROM ${...} 取不到值，会报 "base name should not be blank"。
ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NODE_IMAGE} AS build

WORKDIR /app

ARG NPM_REGISTRY=https://registry.npmmirror.com

# 先装依赖，充分利用镜像层缓存
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      npm ci --no-fund --no-audit --registry="${NPM_REGISTRY}"; \
    else \
      npm ci --no-fund --no-audit; \
    fi

COPY shared ./shared
COPY CHANGELOG.md ./CHANGELOG.md
COPY frontend ./frontend

# 默认走同源反代（nginx 把 /api 转发到后端），因此前端无需跨域配置
ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=${VITE_API_BASE}

WORKDIR /app/frontend
RUN npx vite build

FROM ${NGINX_IMAGE}

RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
