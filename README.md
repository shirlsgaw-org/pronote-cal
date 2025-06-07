# Pronote to Google Calendar Sync

A Python AWS Lambda function that automatically syncs homework assignments from Pronote (French school management system) to Google Calendar.

## Features

- **Content-based idempotency**: Uses SHA256 hashes to prevent duplicate events
- **Smart duplicate detection**: Updates existing events when content changes
- **Assignment type classification**: Automatically categorizes homework vs tests/exams
- **Secure credential management**: Uses AWS Secrets Manager for sensitive data
- **Robust error handling**: Comprehensive logging and error recovery

## Files

- `lambda_function.py` - Main Lambda handler
- `pronote_client.py` - Pronote API wrapper with content hashing
- `calendar_client.py` - Google Calendar API wrapper with hash-based lookup
- `config.py` - Configuration management from environment variables
- `requirements.txt` - Python dependencies

## Setup

### 1. Create AWS Secrets Manager Secrets

#### Pronote Credentials
Create a secret named `pronote-credentials` with this JSON format:
```json
{
  "url": "https://your-pronote-instance.com",
  "username": "your_username", 
  "password": "your_password"
}
```

#### Google Calendar Credentials  
Create a secret named `google-calendar-credentials` with your Google service account JSON:
```json
{
  "type": "service_account",
  "project_id": "your-project",
  "private_key_id": "key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "service-account@your-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

### 2. Deploy to AWS Lambda

1. **Create a deployment package:**
   ```bash
   # Install dependencies
   pip install -r requirements.txt -t .
   
   # Create ZIP file
   zip -r pronote-calendar-sync.zip *.py
   ```

2. **Create Lambda function in AWS Console:**
   - Runtime: Python 3.11
   - Handler: `lambda_function.lambda_handler`
   - Timeout: 5 minutes
   - Memory: 256 MB

3. **Set environment variables:**
   ```
   PRONOTE_CREDENTIALS_SECRET_NAME=pronote-credentials
   GOOGLE_CREDENTIALS_SECRET_NAME=google-calendar-credentials
   GOOGLE_CALENDAR_ID=your-calendar-id@gmail.com
   AWS_REGION=us-east-1
   SYNC_DAYS_AHEAD=30
   EVENT_DURATION_HOURS=2
   TIMEZONE=Europe/Paris
   LOG_LEVEL=INFO
   ```

4. **Add IAM permissions:**
   The Lambda execution role needs:
   - `secretsmanager:GetSecretValue` for both secrets
   - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

### 3. Schedule Execution (Optional)

Create an EventBridge rule to run the function automatically:
- Schedule: `rate(12 hours)` or `cron(0 6,18 * * ? *)`
- Target: Your Lambda function

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRONOTE_CREDENTIALS_SECRET_NAME` | Yes | - | AWS Secrets Manager secret for Pronote |
| `GOOGLE_CREDENTIALS_SECRET_NAME` | Yes | - | AWS Secrets Manager secret for Google |
| `GOOGLE_CALENDAR_ID` | Yes | - | Google Calendar ID |
| `AWS_REGION` | No | us-east-1 | AWS region |
| `SYNC_DAYS_AHEAD` | No | 30 | Days ahead to sync |
| `EVENT_DURATION_HOURS` | No | 2 | Default event duration |
| `TIMEZONE` | No | Europe/Paris | Event timezone |
| `LOG_LEVEL` | No | INFO | Logging level |
| `DRY_RUN` | No | false | Test mode (no events created) |

## How It Works

1. **Fetch homework**: Connects to Pronote and retrieves assignments
2. **Generate hashes**: Creates SHA256 hashes for each assignment based on subject + due date + description
3. **Check duplicates**: Searches existing calendar events by hash
4. **Create/update events**: 
   - Creates new events for new assignments
   - Updates existing events if content changed
   - Skips unchanged assignments (idempotent)

## Event Structure

Calendar events include metadata in `extendedProperties`:
```json
{
  "summary": "Math: Chapter 5 exercises",
  "start": {"dateTime": "2025-06-10T18:00:00"},
  "extendedProperties": {
    "private": {
      "pronote_hash": "abc123def456789",
      "source": "pronote",
      "assignment_type": "homework",
      "subject": "Math",
      "sync_version": "2.0"
    }
  }
}
```

## Testing

Test the function manually in AWS Lambda console with this event:
```json
{
  "source": "manual-test"
}
```

Check CloudWatch logs for execution details and any errors.

## Troubleshooting

- **Authentication errors**: Verify Secrets Manager secrets are correct
- **Calendar permissions**: Ensure service account has calendar access
- **Missing events**: Check CloudWatch logs for API errors
- **Duplicates**: Hash-based system should prevent duplicates automatically

## Security

- Credentials stored securely in AWS Secrets Manager
- No sensitive data in environment variables
- Content hashes are one-way (cannot reverse to get original content)
- Service account has minimal required permissions