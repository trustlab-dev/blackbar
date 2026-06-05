"""
Database Configuration

Single database: "blackbar"

All collections live in the single blackbar database.

Usage:
    from src.database import db, cases, documents, users
"""

from src.core.database import get_shared_database

# Get database
db = get_shared_database()

# User collections
users = db.users

# Domain collections
cases = db.cases
documents = db.documents
templates = db.templates
teams = db.teams
system_config = db.system_config

# Workflow collections (RFC-010)
clock_events = db.clock_events
case_messages = db.case_messages
case_contributors = db.case_contributors
case_reminders = db.case_reminders
case_transfers = db.case_transfers
