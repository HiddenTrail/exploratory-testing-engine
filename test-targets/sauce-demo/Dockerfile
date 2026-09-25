# Sauce Demo, built from a pinned commit of the Sauce Labs sample shop.
#
# There's no official or trustworthy prebuilt image, so this builds the React
# (Vite) app from github.com/saucelabs/sample-app-web and serves it with nginx.
# The commit is pinned so the target stays the same between runs.
#
# Copied from Spoor's fixtures (../ht-spoor/fixtures/sauce-demo/).
ARG SAMPLE_APP_SHA=60fdd634bb111c092282fa07977513a0a7765593

FROM node:24.9.0-alpine AS build
ARG SAMPLE_APP_SHA
# Skip husky's git hook install. There's no git repo in the build.
ENV HUSKY=0
WORKDIR /app
# ADD doesn't unpack a remote tarball, so download it and unpack it by hand.
ADD https://github.com/saucelabs/sample-app-web/archive/${SAMPLE_APP_SHA}.tar.gz /tmp/src.tar.gz
RUN tar -xzf /tmp/src.tar.gz --strip-components=1 -C /app && rm /tmp/src.tar.gz
RUN npm ci
# Vite writes to "build" here (build.outDir in vite.config.js), not "dist".
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
