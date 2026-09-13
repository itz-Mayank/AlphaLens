FROM node:22-slim AS base
WORKDIR /app
ENV NODE_ENV=development

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- production build stage (used by infra/docker-compose in prod profile) ---
FROM base AS build
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
