#!/usr/bin/env bash
# SAIMON-DB-CRED-SCOPE-1 (#221): per-service DB roles for the MCP containers.
#
# Executed by docker-entrypoint-initdb.d on first init (sorted after
# 01-schema.sql). Creates one LOGIN role per MCP service and grants full access
# to the shared saimon database so no service authenticates with the shared
# admin POSTGRES_PASSWORD. Passwords are read from the per-service env vars
# that docker-compose passes into the postgres container.
set -e

create_role() {
    role="$1"
    password="$2"

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role}') THEN
                CREATE ROLE ${role} LOGIN PASSWORD '${password}';
            END IF;
        END
        \$\$;
        GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${role};
        GRANT USAGE ON SCHEMA public TO ${role};
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${role};
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ${role};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${role};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ${role};
EOSQL
}

create_role search_mcp   "${SEARCH_DB_PASSWORD}"
create_role generate_mcp "${GENERATE_DB_PASSWORD}"
create_role export_mcp   "${EXPORT_DB_PASSWORD}"
create_role evaluate_mcp "${EVALUATE_DB_PASSWORD}"
create_role verify_mcp   "${VERIFY_DB_PASSWORD}"
create_role explore_mcp  "${EXPLORE_DB_PASSWORD}"
create_role api_mcp      "${API_DB_PASSWORD}"
create_role domain_mcp   "${DOMAIN_DB_PASSWORD}"
create_role crew_mcp     "${CREW_DB_PASSWORD}"
