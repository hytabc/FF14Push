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

# 先装依赖，充分利用镜像层缓存。
# 只装 frontend 工作区：前端镜像不需要根目录的 Capacitor 工具链，而 @capacitor/assets 会拉入
# sharp —— 它的安装脚本要从 GitHub 下载 libvips 预编译包，国内网络下会长时间卡住（甚至失败）。
# 只装本工作区可把依赖从 347 个降到 137 个，并完全避开这类下载。
# 注意：改了任何 package.json 的版本号都会让本层缓存失效、重新走一遍 npm ci，属预期行为。
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      npm ci --no-fund --no-audit --workspace frontend --registry="${NPM_REGISTRY}"; \
    else \
      npm ci --no-fund --no-audit --workspace frontend; \
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
