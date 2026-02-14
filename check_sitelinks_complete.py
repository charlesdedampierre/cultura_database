import time
import smtplib
from email.mime.text import MIMEText
import json
import os

LOG_FILE = "data/all_humans/sitelinks_extraction.log"
OUTPUT_FILE = "data/all_humans/all_human_sitelinks.json"

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = "cdedampierre@bunka.ai"
    msg['To'] = "cdedampierre@bunka.ai"
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login("cdedampierre@bunka.ai", "pfau ippr pxpl dssd")
        server.sendmail(msg['From'], [msg['To']], msg.as_string())

while True:
    time.sleep(30)
    with open(LOG_FILE, 'r') as f:
        content = f.read()
    
    if "EXTRACTION COMPLETE" in content:
        # Get stats
        lines = content.split('\n')
        stats = '\n'.join([l for l in lines if any(x in l for x in ['Processed:', 'Total sitelinks', 'Unique individuals', 'Time:', 'Rate:'])])
        
        # Check file size
        size_mb = os.path.getsize(OUTPUT_FILE) / (1024*1024)
        
        send_email(
            "Sitelinks extraction complete",
            f"Extraction finished!\n\n{stats}\n\nFile size: {size_mb:.1f} MB"
        )
        print("Email sent!")
        break
    elif "Error" in content or "error" in content.lower():
        send_email("Sitelinks extraction ERROR", content[-2000:])
        print("Error email sent!")
        break
