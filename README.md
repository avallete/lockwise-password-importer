# Lockwise-password-importer

Actually, with Firefox V70.0 and greater, there is no easy way to import your password from existing password manager or other browser.

This repo contain some scripts to fill this gap, and especially to migrate from Chrome/Chromium passwords manager to Firefox Lockwise. 

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Examples](#examples)
- [FAQ](#faq)


## Requirements:
The minimum installed requirements to do the installation procedure:
- python3
- pip
- virtualenv
- Linux/OSX
- No 2FA on your Firefox Account (you need to disable it, you will be able to re-enable it later)

## Installation

```sh
git clone https://github.com/avallete/lockwise-password-importer.git
cd lockwise-password-importer
# Create virtualenv to install scripts dependencies
virtualenv -p python3 venv && source venv/bin/activate
# Install dependencies
pip install -r requirements.txt
```

## Usage

##### lockwise_password_importer.py:
```bash
Usage: lockwise_password_importer.py [OPTIONS] PASSWORD_FILEPATH

  Get a csvfile containing passwords informations and feed your Firefox
  Lockwise account with it.

Options:
  --email TEXT     Firefox account email
  --password TEXT  Firefox account password
  --help           Show this message and exit.
```

##### chrome_login_database_extractor.py:
```bash
Usage: chrome_login_database_extractor.py [OPTIONS]

  Search and extract passwords informations to .csv file from Chrome 'Login
  Data' sqlite database

Options:
  -o, --output_file FILENAME      File where the extracted password will be
                                  saved as .csv format
  -i, --login-data-file FILENAME  Path where the 'Login Data' Chrome sqlite
                                  database can be found
                                  If not provided, the
                                  command will try to search it from default
                                  Chrome/Chromium locations and stop for each
                                  one
                                  founded to ask if it must be use for
                                  extraction
  --help                          Show this message and exit.

```

## Examples:

### Chrome to Firefox migration example:
```bash
$ python3 chrome_login_database_extractor.py -o ./outfile.csv
INFO: Login Data found on here: /home/user/.config/google-chrome/Default
Do you want to extract passwords from this file ?:  [y/N]: y
INFO: Try to connect to /home/user/.config/google-chrome/Default/Login Data database
INFO: Connected successfully to database, 120 passwords found
INFO: Passwords saved into: /home/user/Documents/lockwise-password-importer/outfile.csv
$ python3 lockwise_password_importer.py ./outfile.csv
Email: useraccount@gmail.com
Password:
... # Some warnings may appear if you have some incompatibles passwords for Firefox (missing password, invalid hostname url...) 
101 passwords will be loaded into firefox, do you confirm ?  [y/N]: y
# Check your mail for new Firefox Sign In mail
Please click through the confirmation email or type 'resend' to resend the mail or 'c' to continue: c
100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 101/101 [00:00<00:00,  1.01it/s]INFO: Passwords saved into: /home/user/Documents/lockwise-password-importer/outfile.csv
INFO: Done !
``` 

## FAQ:

### I didnt received the Firefox Signin mail:
Please check you don't have 2FA activated on your Sync account.

### Can I import any csvfile containing passwords to firefox ?
Yes, your csvfile must just have a valid csv header file with the following columns:
```csv
"hostname","formSubmitURL","usernameField","passwordField","username","password"
```

With data matching the following schema:
```text
{
    Required('hostname'): Url(),
    Required('formSubmitURL'): Any(str, ''),
    Optional('usernameField'): str,
    Optional('passwordField'): str,
    Optional('username'): str,
    Required('password'): All(str, Length(min=1)),
}
```