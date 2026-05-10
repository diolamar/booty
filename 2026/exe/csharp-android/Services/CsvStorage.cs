using System.Text;
using CsvCrudSample.Android.Models;

namespace CsvCrudSample.Android.Services;

public static class CsvStorage
{
    private static readonly string CsvFile = Path.Combine(FileSystem.AppDataDirectory, "users.csv");

    public static string FilePath => CsvFile;

    public static void EnsureCsvFile()
    {
        if (!File.Exists(CsvFile))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(CsvFile)!);
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
