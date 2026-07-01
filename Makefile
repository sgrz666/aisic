.PHONY: dev stop test e2e demo-seed

dev:
	docker compose up --build

stop:
	docker compose down

test:
	powershell -ExecutionPolicy Bypass -File scripts/test.ps1

e2e:
	powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1

demo-seed:
	powershell -ExecutionPolicy Bypass -File scripts/demo-seed.ps1

