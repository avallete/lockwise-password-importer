import logging
import os
import sqlite3
import subprocess
import sys
from importlib import import_module
from sys import platform

import click

from utils import check_running_platform, save_data_to_file

# build a table mapping all non-printable characters to None
NOPRINT_TRANS_TABLE = {
    i: None for i in range(0, sys.maxunicode + 1) if not chr(i).isprintable()
}


def make_printable(s):
    """Replace non-printable characters in a string."""

    # the translate method on str removes characters
    # that map to None from the string
    return s.translate(NOPRINT_TRANS_TABLE)


class LinuxDecrypter:
    def __init__(self):
        my_pass = LinuxDecrypter.get_encryption_password()  # get the key password for system
        iterations = 1
        salt = b'saltysalt'
        length = 16

        self.kdf = import_module('Crypto.Protocol.KDF')
        self.aes = import_module('Crypto.Cipher.AES')
        self.iv = b' ' * 16
        self.key = self.kdf.PBKDF2(my_pass, salt, length, iterations)

    @staticmethod
    def get_encryption_password():
        try:
            secretstorage = import_module('secretstorage')
            bus = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(bus)
            if collection.is_locked():
                collection.unlock()
            for item in collection.get_all_items():
                if item.get_label() in ['Chromium Safe Storage', 'Chrome Safe Storage']:
                    logging.info("Decryption key found in secretstorage under: %s" % item.get_label())
                    resp = click.confirm("Do you want to use this key to decrypt your passwords ?: ")
                    if resp:
                        return item.get_secret()
            raise Exception('No chrome data found into secretstorage')
        except Exception as e:
            logging.error("while trying to retrieving decryption key from secretstorage: %s" % e)
            logging.debug("Cannot retrieve decryption key from secretstorage, use default linux 'peanuts' key")
            return 'peanuts'.encode('utf-8')

    def decrypt(self, encrypted_password):
        password = encrypted_password[3:]  # Skip the v10/v11 password prefix
        cipher = self.aes.new(self.key, self.aes.MODE_CBC, IV=self.iv)
        decrypted = cipher.decrypt(password)
        return make_printable(decrypted.decode('utf8'))  # make_printable avoid \x00 \x11 and write file as plain/text


class DarwinDecrypter:
    def __init__(self):
        iterations = 1003
        salt = b'saltysalt'
        length = 16
        my_pass = DarwinDecrypter.get_encryption_password()

        self.kdf = import_module('Crypto.Protocol.KDF')
        self.aes = import_module('Crypto.Cipher.AES')
        self.iv = b' ' * 16
        self.key = self.kdf.PBKDF2(my_pass, salt, length, iterations)

    @staticmethod
    def get_encryption_password():
        for browser in ['Chrome', 'Chromium']:
            proc = subprocess.Popen(
                "security find-generic-password -wa '%s'" % browser,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True)
            stdout, _ = proc.communicate()
            result = stdout.replace(b'\n', b'')
            if len(result > 0):
                logging.info("Decryption key found in keychain for browser: %s" % browser)
                resp = click.confirm("Do you want to use this key to decrypt your passwords ?: ")
                if resp:
                    return result
        raise Exception("Cannot retrieve OSX keychain decryption password")

    def decrypt(self, encrypted_password):
        password = encrypted_password[3:]  # Skip the v10/v11 password prefix
        cipher = self.aes.new(self.key, self.aes.MODE_CBC, IV=self.iv)
        decrypted = cipher.decrypt(password)
        return make_printable(decrypted.decode('utf8'))


CHROME_DATABASE_DECRYPTER = {
    "linux": LinuxDecrypter,
    "darwin": DarwinDecrypter,
}
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

logging.basicConfig(format='%(levelname)s: %(message)s [l.%(lineno)d]', level=logging.DEBUG)


def get_defaults_paths():
    if platform == "linux" or platform == "linux2":
        return CHROME_DATABASE_DEFAULT_LOCATIONS['linux']
    elif platform == "darwin":
        return CHROME_DATABASE_DEFAULT_LOCATIONS['darwin']
    else:
        return


def get_default_decrypter():
    if platform == "linux" or platform == "linux2":
        return CHROME_DATABASE_DECRYPTER['linux']


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
    pass_decrypter = get_default_decrypter()()
    for row in cursor:
        try:
            if row['password_value'][:3] == b'v10' or row['password_value'][:3] == b'v11':  # Password is encrypted
                dict_data.append({
                    "hostname": row['signon_realm'],
                    # Use signon_realm as hostname to match with Firefox autofill behavior
                    "formSubmitURL": row['action_url'],
                    "usernameField": row['username_element'],
                    "passwordField": row['password_element'],
                    "username": row['username_value'],
                    "password": pass_decrypter.decrypt(row['password_value']),
                })
            else:  # Password isn't encrypted
                dict_data.append({
                    "hostname": row['signon_realm'],
                    # Use signon_realm as hostname to match with Firefox autofill behavior
                    "formSubmitURL": row['action_url'],
                    "usernameField": row['username_element'],
                    "passwordField": row['password_element'],
                    "username": row['username_value'],
                    "password": row['password_value'].decode('utf-8'),
                })
        except Exception as e:
            logging.error("with data for [%s]: %s" % (row['signon_realm'], e))
    return dict_data


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
