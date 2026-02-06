# Claude Code Project Configuration

## Python Environment

This project uses a Conda environment named `pacific-emis-disability-inclusive-education`.

On Windows, the Python interpreter is typically at:
- Miniconda: `C:/Users/<username>/miniconda3/envs/pacific-emis-disability-inclusive-education/python.exe`
- Anaconda: `C:/Users/<username>/anaconda3/envs/pacific-emis-disability-inclusive-education/python.exe`

When running Django commands, use the full path to the Conda environment's Python interpreter.

## Database Migrations

**IMPORTANT**: Do NOT run `makemigrations` or `migrate` commands automatically. The user runs all database migrations manually. When model changes require migrations, inform the user that they need to run migrations, but do not execute the commands yourself.

## Project Structure

- Django 5.x project
- Apps: `accounts`, `core`, `integrations`
- Templates: `templates/` (project-level) and app-specific template directories
- Static files: `static/`
