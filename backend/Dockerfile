# Image dùng chung cho api, worker và mock-shop (docs/10 §4). Build từ thư mục backend/:
#   docker compose build   (context ./backend)
FROM python:3.12-slim

# uv bản khớp với uv.lock đang dùng khi phát triển.
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Phụ thuộc trước (lớp được cache khi chỉ mã nguồn đổi). `package = false` nên không cài dự án.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
# Dữ liệu seed hư cấu cho `python -m scripts.seed` (phần còn lại của tests/ bị .dockerignore loại).
COPY tests/fixtures/seed ./tests/fixtures/seed

# Không chạy bằng root. `data/` là nơi cache thô của Fetcher (có thể gắn volume từ máy chủ).
RUN useradd --system --create-home --uid 10001 buyer \
    && mkdir -p /app/data/raw \
    && chown -R buyer:buyer /app/data
USER buyer

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
