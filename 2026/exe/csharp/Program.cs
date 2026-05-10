using System.Text;
using System.Windows.Forms;

ApplicationConfiguration.Initialize();
Application.Run(new CsvCrudForm());

static class CsvStorage
{
    private static readonly string CsvFile = Path.Combine(AppContext.BaseDirectory, "users.csv");

    public static string FilePath => CsvFile;

    public static void EnsureCsvFile()
    {
        if (!File.Exists(CsvFile))
        {
            File.WriteAllText(CsvFile, "id,name,email,phone" + Environment.NewLine, Encoding.UTF8);
        }
    }

    public static List<UserRecord> LoadUsers()
    {
        EnsureCsvFile();
        var lines = File.ReadAllLines(CsvFile);
        var users = new List<UserRecord>();

        foreach (var line in lines.Skip(1))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            var parts = line.Split(',');
            if (parts.Length < 4 || !int.TryParse(parts[0], out var id))
            {
                continue;
            }

            users.Add(new UserRecord
            {
                Id = id,
                Name = parts[1],
                Email = parts[2],
                Phone = parts[3]
            });
        }

        return users;
    }

    public static void SaveUsers(List<UserRecord> users)
    {
        EnsureCsvFile();
        var lines = new List<string> { "id,name,email,phone" };
        lines.AddRange(users.Select(user => $"{user.Id},{Escape(user.Name)},{Escape(user.Email)},{Escape(user.Phone)}"));
        File.WriteAllLines(CsvFile, lines, Encoding.UTF8);
    }

    public static int GetNextId(List<UserRecord> users)
    {
        return users.Count == 0 ? 1 : users.Max(user => user.Id) + 1;
    }

    private static string Escape(string value)
    {
        return value.Replace(",", " ").Trim();
    }
}

sealed class CsvCrudForm : Form
{
    private readonly TextBox _nameTextBox = new() { Width = 320 };
    private readonly TextBox _emailTextBox = new() { Width = 320 };
    private readonly TextBox _phoneTextBox = new() { Width = 320 };
    private readonly Label _fileLabel = new() { AutoSize = true };
    private readonly DataGridView _grid = new()
    {
        Dock = DockStyle.Fill,
        ReadOnly = true,
        AllowUserToAddRows = false,
        AllowUserToDeleteRows = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect,
        MultiSelect = false,
        AutoGenerateColumns = false
    };

    private int? _selectedUserId;

    public CsvCrudForm()
    {
        Text = "C# CSV CRUD GUI";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(900, 650);
        Size = new Size(900, 650);

        CsvStorage.EnsureCsvFile();
        BuildLayout();
        RefreshGrid();
    }

    private void BuildLayout()
    {
        var mainLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12)
        };
        mainLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        mainLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var formGroup = new GroupBox
        {
            Text = "User Details",
            Dock = DockStyle.Fill,
            Padding = new Padding(12),
            AutoSize = true
        };

        var formLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 4,
            AutoSize = true
        };
        formLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90F));
        formLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));

        formLayout.Controls.Add(new Label { Text = "Name", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
        formLayout.Controls.Add(_nameTextBox, 1, 0);
        formLayout.Controls.Add(new Label { Text = "Email", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
        formLayout.Controls.Add(_emailTextBox, 1, 1);
        formLayout.Controls.Add(new Label { Text = "Phone", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2);
        formLayout.Controls.Add(_phoneTextBox, 1, 2);

        var buttonPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false
        };

        buttonPanel.Controls.Add(CreateButton("Add", (_, _) => AddUser()));
        buttonPanel.Controls.Add(CreateButton("Edit", (_, _) => EditUser()));
        buttonPanel.Controls.Add(CreateButton("Delete", (_, _) => DeleteUser()));
        buttonPanel.Controls.Add(CreateButton("Clear", (_, _) => ClearForm()));
        buttonPanel.Controls.Add(CreateButton("Refresh", (_, _) => RefreshGrid()));

        formLayout.Controls.Add(buttonPanel, 0, 3);
        formLayout.SetColumnSpan(buttonPanel, 2);
        formGroup.Controls.Add(formLayout);

        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Id", HeaderText = "ID", DataPropertyName = "Id", Width = 60 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Name", HeaderText = "Name", DataPropertyName = "Name", Width = 180 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Email", HeaderText = "Email", DataPropertyName = "Email", Width = 240 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Phone", HeaderText = "Phone", DataPropertyName = "Phone", Width = 180 });
        _grid.SelectionChanged += Grid_SelectionChanged;

        _fileLabel.Text = $"CSV file: {CsvStorage.FilePath}";

        mainLayout.Controls.Add(formGroup, 0, 0);
        mainLayout.Controls.Add(_grid, 0, 1);
        mainLayout.Controls.Add(_fileLabel, 0, 2);
        Controls.Add(mainLayout);
    }

    private static Button CreateButton(string text, EventHandler onClick)
    {
        var button = new Button
        {
            Text = text,
            Width = 100,
            Height = 34,
            Margin = new Padding(0, 0, 8, 0)
        };
        button.Click += onClick;
        return button;
    }

    private void RefreshGrid()
    {
        var users = CsvStorage.LoadUsers();
        _grid.DataSource = users;
        _fileLabel.Text = $"CSV file: {CsvStorage.FilePath}";
    }

    private void AddUser()
    {
        var name = _nameTextBox.Text.Trim();
        var email = _emailTextBox.Text.Trim();
        var phone = _phoneTextBox.Text.Trim();

        if (!ValidateFields(name, email, phone))
        {
            return;
        }

        var users = CsvStorage.LoadUsers();
        users.Add(new UserRecord
        {
            Id = CsvStorage.GetNextId(users),
            Name = name,
            Email = email,
            Phone = phone
        });

        CsvStorage.SaveUsers(users);
        RefreshGrid();
        ClearForm();
        MessageBox.Show("User added successfully.", "Saved", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void EditUser()
    {
        if (_selectedUserId is null)
        {
            MessageBox.Show("Please select a user to edit.", "Select User", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var name = _nameTextBox.Text.Trim();
        var email = _emailTextBox.Text.Trim();
        var phone = _phoneTextBox.Text.Trim();

        if (!ValidateFields(name, email, phone))
        {
            return;
        }

        var users = CsvStorage.LoadUsers();
        var user = users.FirstOrDefault(x => x.Id == _selectedUserId.Value);
        if (user is null)
        {
            MessageBox.Show("Selected user was not found.", "Not Found", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        user.Name = name;
        user.Email = email;
        user.Phone = phone;

        CsvStorage.SaveUsers(users);
        RefreshGrid();
        ClearForm();
        MessageBox.Show("User updated successfully.", "Updated", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void DeleteUser()
    {
        if (_selectedUserId is null)
        {
            MessageBox.Show("Please select a user to delete.", "Select User", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var confirm = MessageBox.Show(
            "Delete this user?",
            "Confirm Delete",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question);

        if (confirm != DialogResult.Yes)
        {
            return;
        }

        var users = CsvStorage.LoadUsers();
        var removed = users.RemoveAll(user => user.Id == _selectedUserId.Value);
        if (removed == 0)
        {
            MessageBox.Show("Selected user was not found.", "Not Found", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        CsvStorage.SaveUsers(users);
        RefreshGrid();
        ClearForm();
        MessageBox.Show("User deleted successfully.", "Deleted", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private bool ValidateFields(string name, string email, string phone)
    {
        if (!string.IsNullOrWhiteSpace(name) && !string.IsNullOrWhiteSpace(email) && !string.IsNullOrWhiteSpace(phone))
        {
            return true;
        }

        MessageBox.Show("Please fill in name, email, and phone.", "Missing Data", MessageBoxButtons.OK, MessageBoxIcon.Error);
        return false;
    }

    private void ClearForm()
    {
        _selectedUserId = null;
        _nameTextBox.Clear();
        _emailTextBox.Clear();
        _phoneTextBox.Clear();
        _grid.ClearSelection();
    }

    private void Grid_SelectionChanged(object? sender, EventArgs e)
    {
        if (_grid.CurrentRow?.DataBoundItem is not UserRecord user)
        {
            return;
        }

        _selectedUserId = user.Id;
        _nameTextBox.Text = user.Name;
        _emailTextBox.Text = user.Email;
        _phoneTextBox.Text = user.Phone;
    }
}

sealed class UserRecord
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string Email { get; set; } = "";
    public string Phone { get; set; } = "";
}
