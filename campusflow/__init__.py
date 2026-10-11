"""CampusFlow: a small text-based helpdesk for Learn2Earn campus staff.

The package is split by responsibility:

* :mod:`campusflow.tickets`  - the ticket model, validation and priority rules.
* :mod:`campusflow.workflow` - assignment, status transitions and the work queue.
* :mod:`campusflow.storage`  - atomic JSON persistence with explicit errors.
* :mod:`campusflow.reports`  - summary statistics.

Nothing in here prints or reads from the terminal; ``main.py`` owns the CLI.
"""

__version__ = "1.0.0"

__all__ = ["tickets", "workflow", "storage", "reports"]
