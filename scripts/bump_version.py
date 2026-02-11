
import sys
import re
import os
from datetime import datetime

VERSION_FILE = "VERSION"
README_FILE = "README.md"

def bump_version(part):
    # 1. Read current version
    if not os.path.exists(VERSION_FILE):
        print(f"❌ {VERSION_FILE} not found!")
        sys.exit(1)
        
    with open(VERSION_FILE, 'r') as f:
        current_v = f.read().strip()
        
    print(f"📉 Current Version: {current_v}")
    
    parts = current_v.split('.')
    if len(parts) != 3:
        print("❌ Invalid version format. Expected x.y.z")
        sys.exit(1)
        
    major, minor, patch = map(int, parts)
    
    # 2. Calculate new version
    if part == 'patch':
        patch += 1
    elif part == 'minor':
        minor += 1
        patch = 0
    elif part == 'major':
        major += 1
        minor = 0
        patch = 0
    else:
        print("❌ Unknown bump type. Use: patch, minor, major")
        sys.exit(1)
        
    new_v = f"{major}.{minor}.{patch}"
    print(f"📈 New Version:     {new_v}")
    
    # 3. Update VERSION file
    with open(VERSION_FILE, 'w') as f:
        f.write(new_v)
        
    # 4. Update README.md
    if os.path.exists(README_FILE):
        with open(README_FILE, 'r') as f:
            content = f.read()
            
        # Regex to find "**Version**: x.y.z"
        pattern = r"\*\*Version\*\*: \d+\.\d+\.\d+"
        replacement = f"**Version**: {new_v}"
        
        new_content = re.sub(pattern, replacement, content)
        
        # Also update date
        today = datetime.now().strftime("%Y-%m-%d")
        date_pattern = r"\*\*Last Updates\*\*: \d{4}-\d{2}-\d{2}"
        date_replacement = f"**Last Updates**: {today}"
        
        new_content = re.sub(date_pattern, date_replacement, new_content)
        
        with open(README_FILE, 'w') as f:
            f.write(new_content)
            
        print("✅ Updated README.md")
    
    print(f"🚀 Version bumped to {new_v} successfully!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 bump_version.py [patch|minor|major]")
        sys.exit(1)
        
    bump_version(sys.argv[1].lower())
