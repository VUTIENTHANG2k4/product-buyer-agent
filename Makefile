# Lệnh dự án (docs/09 §6, docs/10 §3). Chạy bằng Git Bash/WSL2 trên Windows.
# Target có dòng `## mô tả` hiện trong `make help`. Target chưa có mã thực thi (thuộc task sau)
# dừng với "Chưa khả dụng" (mã 1/2) thay vì giả vờ thành công.
#
# Ghi chú: thông báo tiếng Việt dùng $(error)/$(info) (make tự in) chứ không dùng `echo` trong recipe,
# vì make bản Windows truyền recipe qua code page ANSI làm hỏng dấu. Các thông báo này được mở rộng
# trước khi recipe chạy, nên thông báo "Bỏ qua ..." xuất hiện ngay đầu lệnh.
SHELL := bash
.DEFAULT_GOAL := help

BE := cd backend &&
FE := cd frontend &&

# $(call require,<đường dẫn>,<task cung cấp>): dừng nếu đường dẫn chưa tồn tại.
require = $(if $(wildcard $(1)),,$(error Chưa khả dụng: thiếu $(1) (làm ở $(2))))

.PHONY: help db-up db-down demo-up demo-seed demo-price-drop setup dev dev-api dev-web dev-mock worker \
	mock-shop check test-be test-fe e2e eval test-live scrape seed gen-api migrate

help: ## Liệt kê mọi lệnh
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

db-up: ## Bật PostgreSQL (Docker Compose, service db) và chờ healthcheck
	docker compose up -d --wait db

db-down: ## Tắt PostgreSQL (giữ dữ liệu trong volume pgdata)
	docker compose down

demo-up: ## Build và chạy cả hệ thống bằng Docker (web :8080, api :8000, mock-shop :8100)
	docker compose up -d --build

demo-seed: ## Nạp dữ liệu hư cấu `dev` vào DB của hệ thống Docker (cần demo-up)
	docker compose run --rm api python -m scripts.seed --fixture dev

demo-price-drop: ## Demo: nâng giá một offer mock-shop + tạo cảnh báo, lượt Mock Shop kế tiếp sẽ báo giảm giá
	docker compose run --rm api python -m scripts.demo_price_drop

setup: db-up ## Bật DB, cài phụ thuộc, migrate, seed dev
	$(BE) uv sync --locked
	$(FE) npm ci
	$(if $(wildcard backend/alembic.ini),@$(MAKE) --no-print-directory migrate,$(info Bỏ qua migrate: chưa có backend/alembic.ini (T1.2)))
	$(if $(wildcard backend/scripts/seed.py),@$(MAKE) --no-print-directory seed FIXTURE=dev,$(info Bỏ qua seed: chưa có backend/scripts/seed.py (T1.5)))

dev: ## API :8000 + frontend :5173 + mock-shop :8100
	@$(MAKE) --no-print-directory -j3 dev-api dev-web dev-mock

dev-api:
	$(BE) uv run uvicorn app.main:app --reload --port 8000

dev-web:
	$(FE) npm run dev

dev-mock:
	$(if $(wildcard backend/app/mock_shop/main.py),@$(MAKE) --no-print-directory mock-shop,$(info Bỏ qua mock-shop: chưa có backend/app/mock_shop/main.py (T2.3)))

worker: ## Chạy bộ lập lịch (APScheduler)
	$(call require,backend/app/worker.py,T9.3)
	$(BE) uv run python -m app.worker

mock-shop: ## Chạy riêng mock-shop :8100
	$(call require,backend/app/mock_shop/main.py,T2.3)
	$(BE) uv run uvicorn app.mock_shop.main:app --port 8100

check: test-be test-fe ## Cổng chất lượng: ruff, mypy, pytest, eslint, tsc, vitest

test-be: ## Backend: ruff, mypy, pytest + coverage (>= 80%)
	$(BE) uv run ruff check .
	$(BE) uv run ruff format --check .
	$(BE) uv run mypy app scripts
	$(BE) uv run pytest --cov=app --cov-fail-under=80 --cov-report=term-missing:skip-covered --cov-report=xml

test-fe: ## Frontend: eslint, prettier, tsc, vitest
	$(FE) npm run lint
	$(FE) npm run format:check
	$(FE) npx tsc --noEmit
	$(FE) npm run typecheck
	$(FE) npm test

e2e: ## Playwright E2E (LLM giả)
	$(call require,frontend/e2e,T8.8)
	$(FE) npm run e2e

eval: ## Eval agent với LLM thật (CASES="L01 C02", SLEEP=giây nghỉ giữa các câu; tùy chọn)
	$(call require,backend/scripts/run_eval.py,T6.6)
	$(BE) uv run python -m scripts.run_eval $(if $(CASES),--cases $(CASES)) $(if $(SLEEP),--sleep $(SLEEP))

# pytest thoát mã 5 khi không thu thập được test nào: coi là bình thường khi chưa có test live.
test-live: ## Test với trang thật (thủ công, cần người dùng cho phép)
	@$(BE) uv run pytest -m live; rc=$$?; if [ $$rc -eq 5 ]; then echo "Chua co test live nao."; exit 0; fi; exit $$rc

scrape: ## Một lượt thu thập: make scrape SITE=mockshop CAT=laptop [PAGES=1]
	$(if $(and $(SITE),$(CAT)),,$(error Cú pháp: make scrape SITE=mockshop CAT=laptop [PAGES=1]))
	$(call require,backend/scripts/scrape.py,T2.6)
	$(BE) uv run python -m scripts.scrape --site $(SITE) --category $(CAT) $(if $(PAGES),--pages $(PAGES))

FIXTURE ?= dev
seed: ## Nạp dữ liệu hư cấu: make seed FIXTURE=dev|eval|e2e [RESET=1: xóa sạch DB trước]
	$(if $(filter dev eval e2e,$(FIXTURE)),,$(error FIXTURE phải là dev, eval hoặc e2e (nhận '$(FIXTURE)')))
	$(call require,backend/scripts/seed.py,T1.5)
	$(BE) uv run python -m scripts.seed --fixture $(FIXTURE) $(if $(RESET),--reset --yes)

gen-api: ## Sinh kiểu TypeScript từ OpenAPI (frontend/openapi.json -> src/api/types.gen.ts)
	$(BE) uv run python -m scripts.dump_openapi
	$(FE) npm run gen:api

migrate: ## alembic upgrade head
	$(call require,backend/alembic.ini,T1.2)
	$(BE) uv run alembic upgrade head
