# Frontend production Dockerfile for Inspectra React app.
# This build expects the React application to live under a frontend/ directory.

FROM node:20-alpine AS build
WORKDIR /app

# Install dependencies based on package manifests.
COPY frontend/package*.json ./
RUN npm install

# Copy source and produce a production build.
COPY frontend/ .
RUN npm run build

FROM nginx:alpine AS runtime
COPY --from=build /app/build /usr/share/nginx/html
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
