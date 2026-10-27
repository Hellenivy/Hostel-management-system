# Smart Hostel Management and Automated Rent Collection System

## Project Description
The Smart Hostel Management and Automated Rent Collection System is a web-based application designed to help small, independently managed hostels in Sukari, Nairobi, manage tenants, rooms, rent payments, and complaints.

The system aims to reduce manual record-keeping, improve rent tracking, and make hostel management easier.

## Features
- Tenant registration and management
- Room management
- Rent payment recording
- Tenant rent balance tracking
- Complaint submission and resolution
- M-Pesa Daraja sandbox integration for testing rent payments

## Requirements
- Python 3.12
- Django 4.2
- XAMPP with MariaDB
- Git
- A web browser

The Python packages required by the project are listed in `requirements.txt`.

## Installation and Setup

1. Install Python 3.12, Git, and XAMPP.
2. Clone this repository from GitHub.
3. Open a terminal in the project folder.
4. Create and activate a virtual environment:

   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

5. Install the required packages:

   ```cmd
   pip install -r requirements.txt
   ```

6. Start MySQL or MariaDB from the XAMPP Control Panel.
7. Create and configure the project database using the database settings in the Django project.
8. Configure your environment variables and Daraja sandbox credentials locally. Do not upload secrets or passwords to GitHub.
9. Apply database migrations:

   ```cmd
   python manage.py migrate
   ```

10. Start the development server:

    ```cmd
    python manage.py runserver
    ```

11. Open `http://127.0.0.1:8000/` in your browser.

## Important Notes
- Database credentials and M-Pesa credentials must be configured on each computer.
- M-Pesa integration is intended for sandbox testing.
- The system is a student project developed using Django and MariaDB.
## M-Pesa Daraja Sandbox Setup

The system includes an M-Pesa STK Push integration using the Safaricom Daraja sandbox. To test this feature, configure your own sandbox credentials.

### 1. Create a Daraja Account
Register or sign in to the Safaricom Daraja developer portal and create or access a sandbox application for Lipa Na M-Pesa Online (STK Push).

### 2. Configure Environment Variables
Create a `.env` file in the Django project directory where `manage.py` is located. Add your own configuration values:

```env
MPESA_CONSUMER_KEY=your_consumer_key
MPESA_CONSUMER_SECRET=your_consumer_secret
MPESA_PASSKEY=your_passkey
```

Do not commit or share the `.env` file. Keep credentials private.

### 3. Configure the Callback URL
Install ngrok and start the Django development server on port 8000. In a separate terminal, start a tunnel:

```cmd
ngrok http 8000
```

Copy the HTTPS forwarding URL provided by ngrok. Update `ALLOWED_HOSTS` and `MPESA_CALLBACK_URL` in Django settings to use that URL. The callback path is:

`/mpesa/callback/`

The callback URL must be publicly reachable for Daraja to send payment results to the local application.

### 4. Test STK Push
Use the Daraja sandbox test environment and its supported test details to initiate an STK Push. Check the application for the transaction status and callback result.

**Note:** The sandbox is for testing, not real rent collection. Each developer should configure their own credentials and callback URL.
