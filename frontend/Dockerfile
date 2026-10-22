# Giao diện web: build Vite rồi phục vụ bằng nginx, proxy /api tới service api (docs/10 §4).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Chuỗi rỗng = cùng origin (đường dẫn tương đối /api/...); nginx chuyển tiếp tới api.
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
