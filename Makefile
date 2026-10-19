.PHONY: test build docker

test:
	@echo "Running tests..."
	# Add your actual test command here (e.g., go test, pytest, npm test)
	@echo "Tests passed!"

build:
	@echo "Building project..."

docker:
	docker build -t my-app .
