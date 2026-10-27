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
