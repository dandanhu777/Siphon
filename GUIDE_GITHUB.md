# GitHub Automation Guide for Siphon System

## 1. Initial Setup (Local)
You already have the necessary configuration files created:
- `.github/workflows/daily_report.yml`: The automation script.
- `.gitignore`: Prevents sensitive files from being uploaded.
- `requirements.txt`: List of required libraries.

## 2. Push to GitHub
Run these commands in your terminal to create the repo and upload code:

```bash
# 1. Initialize Git (if not done)
git init

# 2. Add files
git add .

# 3. Commit
git commit -m "Initial commit for Siphon Automation v6.5"

# 4. Create Repo (Go to GitHub Website -> New Repository -> "SiphonDaily")
# 5. Link and Push
git remote add origin https://github.com/YOUR_USERNAME/SiphonDaily.git
git branch -M main
git push -u origin main
```

## 3. Configure Secrets (Critical!)
For security, your email password should NOT be public. I have modified the code to read from "Secrets".

1. Go to your GitHub Repo -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret**.
3. Add the following secrets:

| Name | Value |
|------|-------|
| `MAIL_USER` | `leavertondrozdowskisu239@gmail.com` |
| `MAIL_PASS` | `saimfxiilntucmph` |

*(Optional: If you use Gemini/DeepSeek API in the future, add `LLM_API_KEY` here too)*

## 4. Run & Test
1. Go to the **Actions** tab in your repo.
2. Select **Daily Siphon Report** on the left.
3. Click **Run workflow** (Manual Trigger) to test it immediately.
4. If successful, it will run automatically every weekday at 16:30 Beijing Time.
