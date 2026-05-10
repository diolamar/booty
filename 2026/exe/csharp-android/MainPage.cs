using System.Collections.ObjectModel;
using CsvCrudSample.Android.Models;
using CsvCrudSample.Android.Services;
using Microsoft.Maui.Controls.Shapes;

namespace CsvCrudSample.Android;

public sealed class MainPage : ContentPage
{
    private readonly ObservableCollection<UserRecord> _users = new();
    private readonly Entry _nameEntry = new() { Placeholder = "Name" };
    private readonly Entry _emailEntry = new() { Placeholder = "Email", Keyboard = Keyboard.Email };
    private readonly Entry _phoneEntry = new() { Placeholder = "Phone", Keyboard = Keyboard.Telephone };
    private readonly Label _fileLabel = new() { FontSize = 12, TextColor = Colors.Gray };
    private readonly CollectionView _collectionView;

    private int? _selectedUserId;

    public MainPage()
    {
        Title = "CSV CRUD";
        BackgroundColor = Color.FromArgb("#F7F4ED");

        _collectionView = new CollectionView
        {
            SelectionMode = SelectionMode.Single,
            ItemsSource = _users,
            ItemTemplate = new DataTemplate(() =>
            {
                var idLabel = new Label { FontAttributes = FontAttributes.Bold, WidthRequest = 48 };
                idLabel.SetBinding(Label.TextProperty, nameof(UserRecord.Id));

                var nameLabel = new Label { FontAttributes = FontAttributes.Bold, TextColor = Color.FromArgb("#1F2937") };
                nameLabel.SetBinding(Label.TextProperty, nameof(UserRecord.Name));

                var emailLabel = new Label { TextColor = Color.FromArgb("#475569") };
                emailLabel.SetBinding(Label.TextProperty, nameof(UserRecord.Email));

                var phoneLabel = new Label { TextColor = Color.FromArgb("#475569") };
                phoneLabel.SetBinding(Label.TextProperty, nameof(UserRecord.Phone));

                return new Border
                {
                    StrokeShape = new RoundRectangle { CornerRadius = 16 },
                    Stroke = Color.FromArgb("#D6D3D1"),
                    BackgroundColor = Colors.White,
                    Padding = 14,
                    Margin = new Thickness(0, 0, 0, 12),
                    Content = new HorizontalStackLayout
                    {
                        Spacing = 12,
                        Children =
                        {
                            idLabel,
                            new VerticalStackLayout
                            {
                                Spacing = 4,
                                Children = { nameLabel, emailLabel, phoneLabel }
                            }
                        }
                    }
                };
            })
        };

        _collectionView.SelectionChanged += OnSelectionChanged;

        var addButton = CreateButton("Add", async () => await AddUserAsync(), "#2563EB");
        var updateButton = CreateButton("Update", async () => await EditUserAsync(), "#0F766E");
        var deleteButton = CreateButton("Delete", async () => await DeleteUserAsync(), "#DC2626");
        var clearButton = CreateButton("Clear", ClearForm, "#78716C");
        var refreshButton = CreateButton("Refresh", RefreshUsers, "#7C3AED");
        var buttonGrid = CreateButtonGrid(addButton, updateButton, deleteButton, clearButton, refreshButton);

        Content = new ScrollView
        {
            Content = new VerticalStackLayout
            {
                Padding = new Thickness(18, 20),
                Spacing = 18,
                Children =
                {
                    new Border
                    {
                        StrokeThickness = 0,
                        Background = new LinearGradientBrush(
                            new GradientStopCollection
                            {
                                new(Color.FromArgb("#0F172A"), 0F),
                                new(Color.FromArgb("#334155"), 1F)
                            },
                            new Point(0, 0),
                            new Point(1, 1)),
                        StrokeShape = new RoundRectangle { CornerRadius = 24 },
                        Padding = 20,
                        Content = new VerticalStackLayout
                        {
                            Spacing = 8,
                            Children =
                            {
                                new Label
                                {
                                    Text = "Android CSV CRUD",
                                    FontSize = 28,
                                    FontAttributes = FontAttributes.Bold,
                                    TextColor = Colors.White
                                },
                                new Label
                                {
                                    Text = "Add, update, and delete users stored in a local CSV file.",
                                    TextColor = Color.FromArgb("#CBD5E1")
                                }
                            }
                        }
                    },
                    new Border
                    {
                        Stroke = Color.FromArgb("#D6D3D1"),
                        BackgroundColor = Colors.White,
                        StrokeShape = new RoundRectangle { CornerRadius = 24 },
                        Padding = 18,
                        Content = new VerticalStackLayout
                        {
                            Spacing = 12,
                            Children =
                            {
                                new Label { Text = "User Details", FontSize = 20, FontAttributes = FontAttributes.Bold },
                                _nameEntry,
                                _emailEntry,
                                _phoneEntry,
                                buttonGrid
                            }
                        }
                    },
                    new VerticalStackLayout
                    {
                        Spacing = 10,
                        Children =
                        {
                            new Label { Text = "Saved Users", FontSize = 20, FontAttributes = FontAttributes.Bold },
                            _collectionView,
                            _fileLabel
                        }
                    }
                }
            }
        };

        CsvStorage.EnsureCsvFile();
        RefreshUsers();
    }

    private Button CreateButton(string text, Action onClick, string backgroundHex)
    {
        var button = new Button
        {
            Text = text,
            BackgroundColor = Color.FromArgb(backgroundHex),
            TextColor = Colors.White,
            CornerRadius = 14,
            HeightRequest = 48
        };
        button.Clicked += (_, _) => onClick();
        return button;
    }

    private static Grid CreateButtonGrid(
        Button addButton,
        Button updateButton,
        Button deleteButton,
        Button clearButton,
        Button refreshButton)
    {
        var grid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star)
            },
            RowDefinitions =
            {
                new RowDefinition(GridLength.Auto),
                new RowDefinition(GridLength.Auto),
                new RowDefinition(GridLength.Auto)
            },
            ColumnSpacing = 12,
            RowSpacing = 12
        };

        grid.Add(addButton);
        Grid.SetColumn(addButton, 0);
        Grid.SetRow(addButton, 0);

        grid.Add(updateButton);
        Grid.SetColumn(updateButton, 1);
        Grid.SetRow(updateButton, 0);

        grid.Add(deleteButton);
        Grid.SetColumn(deleteButton, 0);
        Grid.SetRow(deleteButton, 1);

        grid.Add(clearButton);
        Grid.SetColumn(clearButton, 1);
        Grid.SetRow(clearButton, 1);

        grid.Add(refreshButton);
        Grid.SetColumn(refreshButton, 0);
        Grid.SetRow(refreshButton, 2);
        Grid.SetColumnSpan(refreshButton, 2);

        return grid;
    }

    private async Task AddUserAsync()
    {
        if (!await ValidateFieldsAsync())
        {
            return;
        }

        var name = _nameEntry.Text!.Trim();
        var email = _emailEntry.Text!.Trim();
        var phone = _phoneEntry.Text!.Trim();

        var users = CsvStorage.LoadUsers();
        users.Add(new UserRecord
        {
            Id = CsvStorage.GetNextId(users),
            Name = name,
            Email = email,
            Phone = phone
        });

        CsvStorage.SaveUsers(users);
        RefreshUsers();
        ClearForm();
        await DisplayAlert("Saved", "User added successfully.", "OK");
    }

    private async Task EditUserAsync()
    {
        if (_selectedUserId is null)
        {
            await DisplayAlert("Select User", "Please select a user to update.", "OK");
            return;
        }

        if (!await ValidateFieldsAsync())
        {
            return;
        }

        var name = _nameEntry.Text!.Trim();
        var email = _emailEntry.Text!.Trim();
        var phone = _phoneEntry.Text!.Trim();

        var users = CsvStorage.LoadUsers();
        var user = users.FirstOrDefault(item => item.Id == _selectedUserId.Value);
        if (user is null)
        {
            await DisplayAlert("Not Found", "Selected user was not found.", "OK");
            return;
        }

        user.Name = name;
        user.Email = email;
        user.Phone = phone;

        CsvStorage.SaveUsers(users);
        RefreshUsers();
        ClearForm();
        await DisplayAlert("Updated", "User updated successfully.", "OK");
    }

    private async Task DeleteUserAsync()
    {
        if (_selectedUserId is null)
        {
            await DisplayAlert("Select User", "Please select a user to delete.", "OK");
            return;
        }

        var confirm = await DisplayAlert("Confirm Delete", "Delete this user?", "Yes", "No");
        if (!confirm)
        {
            return;
        }

        var users = CsvStorage.LoadUsers();
        var removed = users.RemoveAll(item => item.Id == _selectedUserId.Value);
        if (removed == 0)
        {
            await DisplayAlert("Not Found", "Selected user was not found.", "OK");
            return;
        }

        CsvStorage.SaveUsers(users);
        RefreshUsers();
        ClearForm();
        await DisplayAlert("Deleted", "User deleted successfully.", "OK");
    }

    private async Task<bool> ValidateFieldsAsync()
    {
        var name = _nameEntry.Text?.Trim() ?? string.Empty;
        var email = _emailEntry.Text?.Trim() ?? string.Empty;
        var phone = _phoneEntry.Text?.Trim() ?? string.Empty;

        if (!string.IsNullOrWhiteSpace(name) &&
            !string.IsNullOrWhiteSpace(email) &&
            !string.IsNullOrWhiteSpace(phone))
        {
            return true;
        }

        await DisplayAlert("Missing Data", "Please fill in name, email, and phone.", "OK");
        return false;
    }

    private void RefreshUsers()
    {
        var users = CsvStorage.LoadUsers();
        _users.Clear();

        foreach (var user in users.OrderBy(item => item.Id))
        {
            _users.Add(user);
        }

        _fileLabel.Text = $"CSV file: {CsvStorage.FilePath}";
    }

    private void ClearForm()
    {
        _selectedUserId = null;
        _nameEntry.Text = string.Empty;
        _emailEntry.Text = string.Empty;
        _phoneEntry.Text = string.Empty;
        _collectionView.SelectedItem = null;
    }

    private void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (e.CurrentSelection.FirstOrDefault() is not UserRecord user)
        {
            return;
        }

        _selectedUserId = user.Id;
        _nameEntry.Text = user.Name;
        _emailEntry.Text = user.Email;
        _phoneEntry.Text = user.Phone;
    }
}
