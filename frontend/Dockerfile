# 构建上下文为仓库根目录：
#   docker build -f frontend/Dockerfile --build-arg VITE_API_BASE=/api/v1 -t eorzea-frontend .
FROM node:22-alpine AS build

WORKDIR /app

# 先装依赖，充分利用镜像层缓存
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
RUN npm ci --no-fund --no-audit

COPY shared ./shared
COPY frontend ./frontend

# 默认走同源反代（nginx 把 /api 转发到后端），因此前端无需跨域配置
ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=${VITE_API_BASE}

WORKDIR /app/frontend
RUN npx vite build

FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
