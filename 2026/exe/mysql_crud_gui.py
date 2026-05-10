import sys
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import mysql.connector
    from mysql.connector import Error
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: mysql-connector-python\n"
        "Install it with:\n"
        "pip install mysql-connector-python"
    ) from exc


APP_TITLE = "MySQL CRUD GUI"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "3306"
DEFAULT_USER = "root"
DEFAULT_PASSWORD = ""
DEFAULT_DATABASE = "crud_app"
TABLE_NAME = "users"
DB_EXCEPTIONS = (Error, ValueError)


def center_window(window, width, height):
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


def make_db_config(include_database=True):
    config = {
        "host": host_var.get().strip() or DEFAULT_HOST,
        "port": int(port_var.get().strip() or DEFAULT_PORT),
        "user": user_var.get().strip() or DEFAULT_USER,
        "password": password_var.get(),
    }
    if include_database:
        config["database"] = database_var.get().strip() or DEFAULT_DATABASE
    return config


def connect_mysql(include_database=True):
    return mysql.connector.connect(**make_db_config(include_database=include_database))


def initialize_database():
    database_name = database_var.get().strip() or DEFAULT_DATABASE

    connection = connect_mysql(include_database=False)
    try:
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}`")
        cursor.execute(f"USE `{database_name}`")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL,
                phone VARCHAR(50) NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def run_query(query, params=None, fetch=False):
    connection = connect_mysql(include_database=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())
        rows = cursor.fetchall() if fetch else None
        connection.commit()
        return rows
    finally:
        cursor.close()
        connection.close()


def set_status(message, error=False):
    status_var.set(message)
    status_label.config(fg="firebrick" if error else "darkgreen")


def clear_form():
    id_var.set("")
    name_var.set("")
    email_var.set("")
    phone_var.set("")
    tree.selection_remove(tree.selection())


def refresh_table():
    try:
        initialize_database()
        rows = run_query(
            f"SELECT id, name, email, phone FROM `{TABLE_NAME}` ORDER BY id ASC",
            fetch=True,
        )
    except DB_EXCEPTIONS as exc:
        set_status(f"Database error: {exc}", error=True)
        return

    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=(row["id"], row["name"], row["email"], row["phone"]))

    database_name = database_var.get().strip() or DEFAULT_DATABASE
    set_status(f"Connected to MySQL database: {database_name}")


def test_connection():
    try:
        initialize_database()
        refresh_table()
        messagebox.showinfo("Connected", "MySQL connection successful.")
    except DB_EXCEPTIONS as exc:
        set_status(f"Database error: {exc}", error=True)
        messagebox.showerror("Connection Failed", str(exc))


def add_user():
    name = name_var.get().strip()
    email = email_var.get().strip()
    phone = phone_var.get().strip()

    if not name or not email or not phone:
        messagebox.showerror("Missing Data", "Please fill in name, email, and phone.")
        return

    try:
        initialize_database()
        run_query(
            f"INSERT INTO `{TABLE_NAME}` (name, email, phone) VALUES (%s, %s, %s)",
            (name, email, phone),
        )
    except DB_EXCEPTIONS as exc:
        set_status(f"Database error: {exc}", error=True)
        messagebox.showerror("Save Failed", str(exc))
        return

    refresh_table()
    clear_form()
    messagebox.showinfo("Saved", "User added successfully.")


def on_select(_event=None):
    selected = tree.selection()
    if not selected:
        return

    values = tree.item(selected[0], "values")
    id_var.set(values[0])
    name_var.set(values[1])
    email_var.set(values[2])
    phone_var.set(values[3])


def edit_user():
    user_id = id_var.get().strip()
    name = name_var.get().strip()
    email = email_var.get().strip()
    phone = phone_var.get().strip()

    if not user_id:
        messagebox.showwarning("Select User", "Please select a user to edit.")
        return

    if not name or not email or not phone:
        messagebox.showerror("Missing Data", "Please fill in name, email, and phone.")
        return

    try:
        initialize_database()
        run_query(
            f"UPDATE `{TABLE_NAME}` SET name=%s, email=%s, phone=%s WHERE id=%s",
            (name, email, phone, user_id),
        )
    except DB_EXCEPTIONS as exc:
        set_status(f"Database error: {exc}", error=True)
        messagebox.showerror("Update Failed", str(exc))
        return

    refresh_table()
    clear_form()
    messagebox.showinfo("Updated", "User updated successfully.")


def delete_user():
    user_id = id_var.get().strip()
    if not user_id:
        messagebox.showwarning("Select User", "Please select a user to delete.")
        return

    if not messagebox.askyesno("Confirm Delete", "Delete this user?"):
        return

    try:
        initialize_database()
        run_query(f"DELETE FROM `{TABLE_NAME}` WHERE id=%s", (user_id,))
    except DB_EXCEPTIONS as exc:
        set_status(f"Database error: {exc}", error=True)
        messagebox.showerror("Delete Failed", str(exc))
        return

    refresh_table()
    clear_form()
    messagebox.showinfo("Deleted", "User deleted successfully.")


root = tk.Tk()
root.title(APP_TITLE)
center_window(root, 950, 700)

id_var = tk.StringVar()
host_var = tk.StringVar(value=DEFAULT_HOST)
port_var = tk.StringVar(value=DEFAULT_PORT)
user_var = tk.StringVar(value=DEFAULT_USER)
password_var = tk.StringVar(value=DEFAULT_PASSWORD)
database_var = tk.StringVar(value=DEFAULT_DATABASE)
name_var = tk.StringVar()
email_var = tk.StringVar()
phone_var = tk.StringVar()
status_var = tk.StringVar(value="Set your MySQL details, then click Connect.")

connection_frame = tk.LabelFrame(root, text="MySQL Connection", padx=12, pady=12)
connection_frame.pack(fill="x", padx=12, pady=12)

tk.Label(connection_frame, text="Host").grid(row=0, column=0, sticky="w", pady=4)
tk.Entry(connection_frame, textvariable=host_var, width=18).grid(row=0, column=1, sticky="ew", pady=4)

tk.Label(connection_frame, text="Port").grid(row=0, column=2, sticky="w", padx=(12, 0), pady=4)
tk.Entry(connection_frame, textvariable=port_var, width=10).grid(row=0, column=3, sticky="ew", pady=4)

tk.Label(connection_frame, text="User").grid(row=1, column=0, sticky="w", pady=4)
tk.Entry(connection_frame, textvariable=user_var, width=18).grid(row=1, column=1, sticky="ew", pady=4)

tk.Label(connection_frame, text="Password").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=4)
tk.Entry(connection_frame, textvariable=password_var, width=18, show="*").grid(row=1, column=3, sticky="ew", pady=4)

tk.Label(connection_frame, text="Database").grid(row=2, column=0, sticky="w", pady=4)
tk.Entry(connection_frame, textvariable=database_var, width=18).grid(row=2, column=1, sticky="ew", pady=4)

tk.Button(connection_frame, text="Connect", width=12, command=test_connection).grid(
    row=2, column=3, sticky="e", pady=8
)

connection_frame.columnconfigure(1, weight=1)
connection_frame.columnconfigure(3, weight=1)

form_frame = tk.LabelFrame(root, text="User Details", padx=12, pady=12)
form_frame.pack(fill="x", padx=12, pady=(0, 12))

tk.Label(form_frame, text="Name").grid(row=0, column=0, sticky="w", pady=4)
tk.Entry(form_frame, textvariable=name_var, width=35).grid(row=0, column=1, sticky="ew", pady=4)

tk.Label(form_frame, text="Email").grid(row=1, column=0, sticky="w", pady=4)
tk.Entry(form_frame, textvariable=email_var, width=35).grid(row=1, column=1, sticky="ew", pady=4)

tk.Label(form_frame, text="Phone").grid(row=2, column=0, sticky="w", pady=4)
tk.Entry(form_frame, textvariable=phone_var, width=35).grid(row=2, column=1, sticky="ew", pady=4)

button_frame = tk.Frame(form_frame)
button_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky="w")

tk.Button(button_frame, text="Add", width=12, command=add_user).pack(side="left", padx=(0, 8))
tk.Button(button_frame, text="Edit", width=12, command=edit_user).pack(side="left", padx=8)
tk.Button(button_frame, text="Delete", width=12, command=delete_user).pack(side="left", padx=8)
tk.Button(button_frame, text="Refresh", width=12, command=refresh_table).pack(side="left", padx=8)
tk.Button(button_frame, text="Clear", width=12, command=clear_form).pack(side="left", padx=8)

form_frame.columnconfigure(1, weight=1)

table_frame = tk.Frame(root)
table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

columns = ("id", "name", "email", "phone")
tree = ttk.Treeview(table_frame, columns=columns, show="headings")
for column_name, title, width in (
    ("id", "ID", 70),
    ("name", "Name", 200),
    ("email", "Email", 260),
    ("phone", "Phone", 180),
):
    tree.heading(column_name, text=title)
    tree.column(column_name, width=width, anchor="center" if column_name == "id" else "w")

tree.pack(side="left", fill="both", expand=True)
tree.bind("<<TreeviewSelect>>", on_select)

scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
scrollbar.pack(side="right", fill="y")
tree.configure(yscrollcommand=scrollbar.set)

status_label = tk.Label(root, textvariable=status_var, anchor="w", fg="darkgreen")
status_label.pack(fill="x", padx=12, pady=(0, 12))

root.mainloop()
