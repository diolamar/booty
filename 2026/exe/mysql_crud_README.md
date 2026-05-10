# MySQL CRUD GUI

This is a Tkinter CRUD app that stores data in MySQL instead of CSV.

## XAMPP defaults

- Host: `localhost`
- Port: `3306`
- User: `root`
- Password: blank

## Install dependency

```powershell
pip install -r 2026\exe\mysql_crud_requirements.txt
```

## Run

```powershell
python 2026\exe\mysql_crud_gui.py
```

## Notes

- Start Apache and MySQL in XAMPP first.
- The app creates the database and `users` table automatically.
- Default database name: `crud_app`
- You can also run the SQL manually from `2026\exe\mysql_crud_setup.sql`.
