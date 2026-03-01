.PHONY: restore

# Restore production data to local docker database
restore:
	@echo "Dropping database..."
	docker compose exec -T -u postgres db dropdb --if-exists velodb
	@echo "Creating fresh database..."
	docker compose exec -T -u postgres db createdb velodb
	@echo "Restoring from Dokku..."
	dokku postgres:export velo-tracker | docker compose exec -T -u postgres db pg_restore -v -d velodb
