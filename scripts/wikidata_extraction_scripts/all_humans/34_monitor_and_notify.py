#!/usr/bin/env python3
"""Monitor extraction process and send email at milestones."""

import re
import smtplib
import subprocess
import time
from email.mime.text import MIMEText

# Configuration
PROCESS_NAME = "04_extract_all_individuals_info_qlever"
EMAIL_TO = "cdedampierre@bunka.ai"
EMAIL_FROM = "cdedampierre@bunka.ai"
APP_PASSWORD = "pfau ippr pxpl dssd"
PROGRESS_FILE = "/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/extracted/individuals_qlever/extraction_progress.txt"

# Milestones to notify (in order)
MILESTONES = [1_700_000, 2_000_000, 2_500_000]

def is_process_running():
    """Check if extraction process is running."""
    result = subprocess.run(
        ["pgrep", "-f", PROCESS_NAME],
        capture_output=True,
        text=True
    )
    return result.returncode == 0

def get_last_progress():
    """Get last line from progress file."""
    try:
        with open(PROGRESS_FILE, "r") as f:
            lines = f.readlines()
            return lines[-1].strip() if lines else "No progress info"
    except:
        return "Could not read progress file"

def get_current_count():
    """Extract current count from progress file."""
    last_line = get_last_progress()
    # Parse "Progress: 1,501,400/2,810,360"
    match = re.search(r'Progress:\s*([\d,]+)/', last_line)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def send_email(subject, body):
    """Send email via Gmail SMTP."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, APP_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def main():
    print(f"Monitoring process: {PROCESS_NAME}")
    print(f"Will send email to: {EMAIL_TO}")
    print(f"Milestones: {MILESTONES}")

    notified_milestones = set()

    # Check every 30 seconds
    while is_process_running():
        current = get_current_count()
        last_progress = get_last_progress()
        print(f"Current: {current:,} - {last_progress[:60]}...")

        # Check milestones
        for milestone in MILESTONES:
            if current >= milestone and milestone not in notified_milestones:
                notified_milestones.add(milestone)
                subject = f"📊 Extraction Progress: {milestone:,} reached!"
                body = f"""Dr de Dampierre,

The QLever extraction has reached {milestone:,} individuals!

Current status:
{last_progress}

- Claude
"""
                send_email(subject, body)

        time.sleep(30)

    # Process finished
    last_progress = get_last_progress()
    final_count = get_current_count()

    subject = "✅ QLever Extraction Complete!"
    body = f"""Dr de Dampierre,

The QLever extraction has finished!

Final count: {final_count:,} individuals

Last status:
{last_progress}

Check the results in:
data/extracted/individuals_qlever/json_batches/

- Claude
"""

    send_email(subject, body)
    print("Monitoring complete.")

if __name__ == "__main__":
    main()
