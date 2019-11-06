import csv
import logging
import os
import sqlite3
from sys import platform

import click

# List of defaults possible paths where Login Data chrome file can be found
CHROME_DATABASE_DEFAULT_LOCATIONS = {
    "linux": [
        "~/.config/chromium/",
        "~/.config/google-chrome/",
    ],
    "darwin": [
        "~/Library/Application Support/Google/Chrome/",
        "~/Library/Application Support/Google/Chromium/",
    ]
}
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)


def check_running_platform():
    """
    Check if the script can run on the platform, since windows encrypt password it's unsuported for now
    TODO: handle windows platform
    """
    if platform == "linux" or platform == "linux2" or platform == "darwin":
        return
    else:
        raise OSError('Unsupported platform %s' % platform)


def get_defaults_paths():
    if platform == "linux" or platform == "linux2":
        return CHROME_DATABASE_DEFAULT_LOCATIONS['linux']
    elif platform == "darwin":
        return CHROME_DATABASE_DEFAULT_LOCATIONS['darwin']
    else:
        return


def find_chrome_login_data(default_paths):
    """
    Explore the list of default_paths directories and search for Login Data file, then ask the user if he want to use it.
    Raise FileNotFoundError if no Login Data file found.
    :param default_paths: A list of the default paths for Login Data location
    :return: string: Return the full path of the choosen Login Data file
    """
    paths_to_explore = default_paths
    while len(paths_to_explore) > 0:
        current_path = os.path.realpath(os.path.expanduser(paths_to_explore.pop()))
        for root, _, filenames in os.walk(current_path, topdown=False):
            if 'Login Data' in filenames:
                logging.info("Login Data found on here: %s" % root)
                resp = click.confirm("Do you want to extract passwords from this file ?: ")
                if resp:
                    return os.path.join(root, 'Login Data')
    raise FileNotFoundError('Login Data file not found anywhere, please provide it using --login-data-file argument')


def get_chrome_database_path(login_data_file):
    if login_data_file:
        db_location = login_data_file.name
        login_data_file.close()
    else:
        default_db_locations = get_defaults_paths()
        db_location = find_chrome_login_data(default_db_locations)
    return db_location


def get_chrome_login_database_connection(db_location):
    try:
        logging.info("Try to connect to %s database" % db_location)
        conn = sqlite3.connect(db_location)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT COUNT(*) AS Cnt from main.logins')
        result = cursor.fetchall()
        logging.info("Connected successfully to database, %s passwords found" % result[0]['Cnt'])
        return conn
    except sqlite3.Error as e:
        logging.error("while trying to connect database, please ensure no other Chrome process is using it")
        raise e


def extract_chrome_passwords_data(conn):
    dict_data = []
    cursor = conn.execute('SELECT * FROM main.logins')
    for row in cursor:
        dict_data.append({
            "hostname": row['signon_realm'],  # Use signon_realm as hostname to match with Firefox autofill behavior
            "formSubmitURL": row['action_url'],
            "usernameField": row['username_element'],
            "passwordField": row['password_element'],
            "username": row['username_value'],
            "password": row['password_value'].decode('utf-8'),
        })
    return dict_data


def save_data_to_file(output_file, csv_columns, dict_data):
    with open(output_file, 'w') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for data in dict_data:
            writer.writerow(data)
    logging.info("Passwords saved into: %s" % output_file)


@click.command(
    help="""Search and extract passwords informations to .csv file from Chrome 'Login Data' sqlite database"""
)
@click.option(
    '--output_file',
    '-o',
    type=click.File('w'),
    help="""File where the extracted password will be saved as .csv format""",
    default=os.path.join(os.path.curdir, 'passwords.csv')
)
@click.option(
    '--login-data-file',
    '-i',
    type=click.File('r'),
    help="""Path where the 'Login Data' Chrome sqlite database can be found
    If not provided, the command will try to search it from default Chrome/Chromium locations and stop for each one
    founded to ask if it must be use for extraction
    """,
)
def chrome_password_database_extractor(output_file, login_data_file):
    try:
        check_running_platform()
        chrome_db_path = get_chrome_database_path(login_data_file)
        conn = get_chrome_login_database_connection(chrome_db_path)
        data = extract_chrome_passwords_data(conn)
        if len(data) > 0:
            save_data_to_file(os.path.realpath(os.path.expanduser(output_file.name)), data[0].keys(), data)
    except Exception as e:
        logging.error("%s" % e)


if __name__ == "__main__":
    chrome_password_database_extractor()
