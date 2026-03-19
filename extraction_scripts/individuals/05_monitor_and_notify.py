"""Monitor extraction progress and send email notifications at milestones."""

import json
import random
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# Email config
GMAIL_ADDRESS = "cdedampierre@bunka.ai"
GMAIL_APP_PASSWORD = "pfau ippr pxpl dssd"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
PROGRESS_FILE = BASE_DIR / "data" / "extracted" / "individuals_qlever" / "identifiers" / "extraction_progress_identifiers.txt"
FAILURES_FILE = BASE_DIR / "data" / "extracted" / "individuals_qlever" / "identifiers" / "extraction_failures_identifiers.json"

# Milestones to notify (every 500K)
MILESTONES = [500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000, 2_810_360]

# Fun computer facts
FUN_FACTS = [
    "The first computer bug was an actual bug - a moth found in the Harvard Mark II computer in 1947.",
    "The QWERTY keyboard was designed to slow typists down to prevent jamming on early typewriters.",
    "The first 1GB hard drive, introduced in 1980, weighed 550 pounds and cost $40,000.",
    "About 90% of the world's currency exists only on computers - physical money is just 10%.",
    "The first computer mouse was made of wood by Doug Engelbart in 1964.",
    "A group of 12 engineers at IBM created the first floppy disk in 1971. It was 8 inches wide.",
    "The name 'Google' comes from 'googol', the number 1 followed by 100 zeros.",
    "The first webcam was created at Cambridge to monitor a coffee pot.",
    "More than 6,000 new computer viruses are released every month.",
    "The first computer programmer was Ada Lovelace, who wrote algorithms for Charles Babbage's Analytical Engine in 1843.",
    "NASA's computers in 1969 that sent astronauts to the moon had less processing power than a modern calculator.",
    "The original name for Windows was 'Interface Manager'.",
    "Email existed before the World Wide Web.",
    "The first domain name ever registered was Symbolics.com on March 15, 1985.",
    "A petabyte is 1,024 terabytes. Google processes about 24 petabytes of data per day.",
]

def send_email(subject: str, body: str):
    """Send an email notification."""
    msg = MIMEMultipart()
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = GMAIL_ADDRESS
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def get_current_progress():
    """Read the latest progress from the file."""
    try:
        with open(PROGRESS_FILE, 'r') as f:
            lines = f.readlines()

        # Find last line with progress format: "X/Y | rate | ETA"
        for line in reversed(lines):
            if '/' in line and '|' in line:
                parts = line.strip().split('/')
                if parts:
                    count = int(parts[0].replace(',', ''))
                    return count
        return 0
    except:
        return 0


def get_failures_count():
    """Get the number of failures."""
    try:
        with open(FAILURES_FILE, 'r') as f:
            failures = json.load(f)
        return len(failures)
    except:
        return 0


def monitor():
    """Monitor progress and send notifications at milestones."""
    import sys
    sys.stdout.flush()

    # Check current progress and skip already-passed milestones
    current = get_current_progress()
    notified_milestones = set(m for m in MILESTONES if m <= current)

    print(f"Starting extraction monitor...", flush=True)
    print(f"Current progress: {current:,}", flush=True)
    print(f"Already passed: {', '.join(f'{m:,}' for m in sorted(notified_milestones)) or 'none'}", flush=True)
    print(f"Will notify at: {', '.join(f'{m:,}' for m in MILESTONES if m not in notified_milestones)}", flush=True)
    print("-" * 50, flush=True)

    while True:
        current = get_current_progress()
        failures = get_failures_count()

        # Check each milestone
        for milestone in MILESTONES:
            if current >= milestone and milestone not in notified_milestones:
                notified_milestones.add(milestone)

                # Pick a random fun fact
                fact = random.choice(FUN_FACTS)

                # Determine if this is the final milestone
                is_final = milestone >= 2_800_000

                if is_final:
                    subject = "Extraction Complete!"
                    body = f"""Extraction has finished!

Progress: {current:,} / 2,810,360 individuals processed
Failures: {failures:,}

Fun Computer Fact:
{fact}

--
Your friendly extraction monitor
"""
                else:
                    subject = f"Extraction Milestone: {milestone:,} reached!"
                    body = f"""Great news! The extraction has reached {milestone:,} individuals.

Current progress: {current:,} / 2,810,360
Failures so far: {failures:,}
Remaining: {2_810_360 - current:,}

Fun Computer Fact:
{fact}

--
Your friendly extraction monitor
"""

                send_email(subject, body)

                if is_final:
                    print("Extraction complete! Exiting monitor.")
                    return

        # Check every 30 seconds
        time.sleep(30)


if __name__ == "__main__":
    monitor()
