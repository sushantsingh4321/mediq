"""
Each file in this folder is one MODULE of mediQ (beds, schedule, ...).

A module has its own URLs (an APIRouter), its own data shapes (Pydantic
models) and its own storage. main.py plugs each one in with app.include_router().
"""
