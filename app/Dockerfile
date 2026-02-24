# multi-stage build for Angular -> nginx
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install --legacy-peer-deps
COPY . .
RUN npm run build -- --configuration production || npm run build

FROM nginx:stable-alpine
RUN mkdir -p /opt/datagerry/frontend
COPY --from=build /app/dist /opt/datagerry/frontend/dist
RUN if [ -d /opt/datagerry/frontend/dist ]; then \
      mv /opt/datagerry/frontend/dist/* /opt/datagerry/frontend/ 2>/dev/null || true; \
      rm -rf /opt/datagerry/frontend/dist || true; \
    fi
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
