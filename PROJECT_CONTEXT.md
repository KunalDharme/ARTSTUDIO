# Art Studio

## Overview

Art Studio is a FastAPI web application that was developed incrementally using VS Code and GitHub Copilot.

The project is currently functional and starts with:

python -m uvicorn fastapi_app.main:app --reload

The application uses:

* FastAPI
* SQLAlchemy
* SQLite
* Jinja2 templates
* Static CSS and JavaScript assets

## Project Structure

fastapi_app/

* main.py
* models.py
* schemas.py
* crud.py
* database.py
* templates/
* static/

## Current Status

The application runs successfully and loads in the browser.

I am continuing development after separating this project from another repository.

I do not have complete documentation of all implemented features.

## Instructions For AI Assistant

1. First analyze the existing codebase.
2. Build an understanding of implemented features from the source code.
3. Do not redesign the project structure unless necessary.
4. Before making major changes, explain your understanding of the current architecture.
5. Ask for additional files only when required.
