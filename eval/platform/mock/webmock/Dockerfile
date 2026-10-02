# The mock WebExploitBench target: a tiny HTTP surface. `nginx:alpine` is
# multi-arch, so building it with DOCKER_DEFAULT_PLATFORM=linux/amd64 on the
# aarch64 eval host exercises the emulated amd64 path (D46) end to end.
FROM nginx:alpine
RUN printf 'webmock ok\n' > /usr/share/nginx/html/index.html
EXPOSE 80
