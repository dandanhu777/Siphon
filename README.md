# Stock Recommendation System

This system automatically fetches A-Share stock data, identifies undervalued opportunities based on PE/PEG ratios, and sends an email report.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install akshare pandas
    ```

2.  **Configuration**:
    The system uses environment variables for email configuration.
    Set the following variables (e.g., in your `.zshrc` or `.bash_profile`):
    ```bash
    export SMTP_SERVER="smtp.qq.com"  # or smtp.gmail.com
    export SMTP_PORT="465"
    export SENDER_EMAIL="your_email@example.com"
    export SENDER_PASSWORD="your_auth_code_or_password"
    ```

## Usage

Run the main script:
```bash
python3 main.py
```

## Logic

1.  **Fetch**: Real-time spot data + Quarterly performance growth data via `akshare`.
2.  **Filter**:
    *   **Profitable**: PE (TTM) > 0
    *   **Improving**: PE (TTM) < PE (Static)
    *   **Undervalued**: PEG < 1 (where PEG = PE_TTM / Growth_Rate)
3.  **Notify**: Sends an HTML email with the top candidates.

## Files

*   `main.py`: Entry point.
*   `stock_recommendation.py`: Analysis logic.
*   `email_notifier.py`: Email sending logic.
