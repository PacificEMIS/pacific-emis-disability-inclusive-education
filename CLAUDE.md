# Claude Code Project Configuration

## Python Environment

This project uses a Conda environment named `pacific-emis-disability-inclusive-education`.

On Windows, the Python interpreter is typically at:
- Miniconda: `C:/Users/<username>/miniconda3/envs/pacific-emis-disability-inclusive-education/python.exe`
- Anaconda: `C:/Users/<username>/anaconda3/envs/pacific-emis-disability-inclusive-education/python.exe`

When running Django commands, use the full path to the Conda environment's Python interpreter.

## Database Migrations

See global `~/.claude/CLAUDE.md` — migrations are never run automatically.

## Project Structure

- Django 5.x project
- Apps: `accounts`, `core`, `integrations`
- Templates: `templates/` (project-level) and app-specific template directories
- Static files: `static/`
