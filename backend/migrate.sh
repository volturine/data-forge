#!/bin/bash
# Database migration script
# Usage: ./migrate.sh [command]
#
# Commands:
#   upgrade    - Apply all pending migrations (default)
#   downgrade  - Rollback one migration
#   current    - Show current migration version
#   history    - Show migration history
#   create     - Create a new migration (requires message: ./migrate.sh create "message")

set -e  # Exit on error

ALEMBIC_CMD="uv run alembic -c database/alembic.ini"

case "${1:-upgrade}" in
    upgrade)
        echo "Applying migrations..."
        $ALEMBIC_CMD upgrade head
        echo "✓ Migrations applied successfully"
        ;;
    downgrade)
        echo "Rolling back one migration..."
        $ALEMBIC_CMD downgrade -1
        echo "✓ Migration rolled back"
        ;;
    current)
        echo "Current migration version:"
        $ALEMBIC_CMD current
        ;;
    history)
        echo "Migration history:"
        $ALEMBIC_CMD history
        ;;
    create)
        if [ -z "$2" ]; then
            echo "Error: Migration message required"
            echo "Usage: ./migrate.sh create \"Description of changes\""
            exit 1
        fi
        echo "Creating new migration..."
        $ALEMBIC_CMD revision --autogenerate -m "$2"
        echo "✓ Migration created. Review it in database/alembic/versions/"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Available commands: upgrade, downgrade, current, history, create"
        exit 1
        ;;
esac
