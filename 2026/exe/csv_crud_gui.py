import csv
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk


FIELDNAMES = ["id", "name", "email", "phone"]


def get_app_folder():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CSV_FILE = get_app_folder() / "users.csv"


def ensure_csv_file():
    if not CSV_FILE.exists():
        with CSV_FILE.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
            writer.writeheader()


def load_users():
    ensure_csv_file()
    with CSV_FILE.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def save_users(users):
    with CSV_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(users)


def get_next_id(users):
    if not users:
        return 1
    return max(int(user["id"]) for user in users) + 1


def clear_form():
    id_var.set("")
    name_var.set("")
    email_var.set("")
    phone_var.set("")
    tree.selection_remove(tree.selection())


def refresh_table():
    tree.delete(*tree.get_children())
    for user in load_users():
        tree.insert("", "end", values=(user["id"], user["name"], user["email"], user["phone"]))
    location_var.set(f"CSV file: {CSV_FILE}")


def add_user():
    name = name_var.get().strip()
    email = email_var.get().strip()
    phone = phone_var.get().strip()

    if not name or not email or not phone:
        messagebox.showerror("Missing Data", "Please fill in name, email, and phone.")
        return

    users = load_users()
    users.append(
        {
            "id": str(get_next_id(users)),
            "name": name,
            "email": email,
            "phone": phone,
        }
    )
    save_users(users)
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
    if not user_id:
        messagebox.showwarning("Select User", "Please select a user to edit.")
        return

    name = name_var.get().strip()
    email = email_var.get().strip()
    phone = phone_var.get().strip()

    if not name or not email or not phone:
        messagebox.showerror("Missing Data", "Please fill in name, email, and phone.")
        return

    users = load_users()
    for user in users:
        if user["id"] == user_id:
            user["name"] = name
            user["email"] = email
            user["phone"] = phone
            save_users(users)
            refresh_table()
            clear_form()
            messagebox.showinfo("Updated", "User updated successfully.")
            return

    messagebox.showerror("Not Found", "Selected user was not found.")


def delete_user():
    user_id = id_var.get().strip()
    if not user_id:
        messagebox.showwarning("Select User", "Please select a user to delete.")
        return

    if not messagebox.askyesno("Confirm Delete", "Delete this user?"):
        return

    users = load_users()
    updated_users = [user for user in users if user["id"] != user_id]

    if len(updated_users) == len(users):
        messagebox.showerror("Not Found", "Selected user was not found.")
        return

    save_users(updated_users)
    refresh_table()
    clear_form()
    messagebox.showinfo("Deleted", "User deleted successfully.")


def center_window(window, width, height):
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


root = tk.Tk()
root.title("CSV CRUD GUI")
center_window(root, 850, 650)

id_var = tk.StringVar()
name_var = tk.StringVar()
email_var = tk.StringVar()
phone_var = tk.StringVar()
location_var = tk.StringVar()

form_frame = tk.LabelFrame(root, text="User Details", padx=12, pady=12)
form_frame.pack(fill="x", padx=12, pady=12)

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
tk.Button(button_frame, text="Clear", width=12, command=clear_form).pack(side="left", padx=8)

form_frame.columnconfigure(1, weight=1)

table_frame = tk.Frame(root)
table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

columns = ("id", "name", "email", "phone")
tree = ttk.Treeview(table_frame, columns=columns, show="headings")
tree.heading("id", text="ID")
tree.heading("name", text="Name")
tree.heading("email", text="Email")
tree.heading("phone", text="Phone")
tree.column("id", width=60, anchor="center")
tree.column("name", width=180)
tree.column("email", width=220)
tree.column("phone", width=160)
tree.pack(side="left", fill="both", expand=True)
tree.bind("<<TreeviewSelect>>", on_select)

scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
scrollbar.pack(side="right", fill="y")
tree.configure(yscrollcommand=scrollbar.set)

tk.Label(root, textvariable=location_var, anchor="w").pack(fill="x", padx=12, pady=(0, 12))

refresh_table()
root.mainloop()
