# invest 微服务容器镜像（star 家族形态：独立进程 + 统一网关 + star JWT）
# 构建：docker build -t star-site/platform-invest:latest .
# 运行：数据目录挂载（trades.csv/invest.db/reports 是有状态资产）
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 依赖先行（层缓存）：只拷贝依赖清单
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# 数据目录由 -v 挂载
ENV INVEST_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8790
# star 形态默认 star JWT 鉴权；密钥经环境 INVEST_JWT_SECRET 注入
ENV INVEST_AUTH_MODE=star
CMD ["uv", "run", "--no-dev", "uvicorn", "invest.webapp.main:app", "--host", "0.0.0.0", "--port", "8790"]
