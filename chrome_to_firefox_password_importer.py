#
#  This is a little script to populate Firefox Sync with
#  Your passwords from google-chrome and chromium
#  Use it like so:
#
#    $> pip install -r requirements.txt
#    $> python3 chrome_to_firefox_password_importer.py
#
#  It will prompt for your Firefox Account email address and
#  password, then try to find the local Chrome/Chromium database on your machine
#  And populate Firefox Lockwise with the extracted passwords from Chrome/Chromium
#

import base64
import csv
import hashlib
import hmac
import json
import logging
import os
import uuid
from binascii import hexlify

import click
import fxa.core
import fxa.crypto
import syncclient.client
import time
import voluptuous
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tqdm import tqdm
from voluptuous import Required, Url, Optional, Any, All, Length
from voluptuous import Schema

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
CRYPTO_BACKEND = default_backend()

VALID_CSV_PASSWORD_SCHEMA = Schema({
    Required('hostname'): Url(),
    Required('formSubmitURL'): Any(str, ''),
    Optional('usernameField'): str,
    Optional('passwordField'): str,
    Optional('username'): str,
    Required('password'): All(str, Length(min=1)),
})


class KeyBundle:
    """A little helper class to hold a sync key bundle."""

    def __init__(self, enc_key, mac_key):
        self.enc_key = enc_key
        self.mac_key = mac_key

    def decrypt_bso(self, data):
        payload = json.loads(data["payload"])

        mac = hmac.new(self.mac_key, payload["ciphertext"].encode("utf-8"), hashlib.sha256)
        if mac.hexdigest() != payload["hmac"]:
            raise ValueError("hmac mismatch: %r != %r" % (mac.hexdigest(), payload["hmac"]))

        iv = base64.b64decode(payload["IV"])
        cipher = Cipher(
            algorithms.AES(self.enc_key),
            modes.CBC(iv),
            backend=CRYPTO_BACKEND
        )
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(base64.b64decode(payload["ciphertext"]))
        plaintext += decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(plaintext) + unpadder.finalize()

        return json.loads(plaintext)

    def encrypt_bso(self, data):
        plaintext = json.dumps(data)

        padder = padding.PKCS7(128).padder()
        plaintext = padder.update(plaintext.encode('utf-8')) + padder.finalize()

        iv = os.urandom(16)
        cipher = Cipher(
            algorithms.AES(self.enc_key),
            modes.CBC(iv),
            backend=CRYPTO_BACKEND
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext)
        ciphertext += encryptor.finalize()

        b64_ciphertext = base64.b64encode(ciphertext)
        mac = hmac.new(self.mac_key, b64_ciphertext, hashlib.sha256).hexdigest()

        return {
            "id": data["id"],
            "payload": json.dumps({
                "ciphertext": b64_ciphertext.decode('utf-8'),
                "IV": base64.b64encode(iv).decode('utf-8'),
                "hmac": mac,
            })
        }


def remove_invalid_records(assertion, kB):
    # Connect to sync.
    xcs = hexlify(hashlib.sha256(kB).digest()[:16])
    client = syncclient.client.SyncClient(assertion, xcs)
    # Fetch /crypto/keys.
    raw_sync_key = fxa.crypto.derive_key(kB, "oldsync", 64)
    root_key_bundle = KeyBundle(
        raw_sync_key[:32],
        raw_sync_key[32:],
    )
    keys_bso = client.get_record("crypto", "keys")
    keys = root_key_bundle.decrypt_bso(keys_bso)
    default_key_bundle = KeyBundle(
        base64.b64decode(keys["default"][0]),
        base64.b64decode(keys["default"][1]),
    )
    passwr = []
    for er in client.get_records("passwords"):
        passwr.append(default_key_bundle.decrypt_bso(er))
    to_remove = [f for f in passwr if
                 'timeCreated' in f and f['timeCreated'] >= int(time.time() * 1000) - ((3600 * 24) * 1000)]
    to_keep = [f for f in passwr if
               'timeCreated' in f and f['timeCreated'] <= int(time.time() * 1000) - ((3600 * 24) * 1000)]
    print("Will remove %s entries %s remaining" % (len(to_remove), len(to_keep)))
    if click.confirm("Continue ?"):
        for record in tqdm(to_remove):
            client.delete_record("passwords", record['id'])


def login(email, password):
    """Use fxa to get the firefox account api
    TODO: Make it work with 2fa
    """
    client = fxa.core.Client("https://api.accounts.firefox.com")
    logging.debug("Signing in as %s ..." % email)
    session = client.login(email, password, keys=True)
    try:
        status = session.get_email_status()
        while not status["verified"]:
            ret = click.prompt("Please click through the confirmation email or type 'resend' to resend the mail")
            if ret == "resend":
                session.resend_email_code()
            status = session.get_email_status()
        assertion = session.get_identity_assertion("https://token.services.mozilla.com/")
        _, kB = session.fetch_keys()
    finally:
        session.destroy_session()
    return assertion, kB


def password_file_format(filepath):
    data_rows = []
    now = int(time.time() * 1000)
    with open(filepath, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                VALID_CSV_PASSWORD_SCHEMA(row)
                data = dict(row)
                data['id'] = "{%s}" % (uuid.uuid4(),)
                data['timeCreated'] = now
                data['timePasswordChanged'] = now
                # Remove trailing / from url's since it cause troubles with autofill form if remaining
                data['hostname'] = row['hostname'].rstrip('/')
                data['formSubmitURL'] = row['formSubmitURL'].rstrip('/') or data['hostname']
                data['httpRealm'] = None
                data_rows.append(data)
            except voluptuous.Error as e:
                logging.warning("%s cannot be loaded because %s." % (row, e))
    return data_rows


def upload_passwords_data(passdata, assertion, kB):
    """
    Upload the passdata passwords to the Firefox Account
    :param passdata: The list of formated Firefox compatible password data
    :param assertion:
    :param kB:
    :return:
    """
    # Connect to sync.
    xcs = hexlify(hashlib.sha256(kB).digest()[:16])
    client = syncclient.client.SyncClient(assertion, xcs)
    # Fetch /crypto/keys.
    raw_sync_key = fxa.crypto.derive_key(kB, "oldsync", 64)
    root_key_bundle = KeyBundle(
        raw_sync_key[:32],
        raw_sync_key[32:],
    )
    keys_bso = client.get_record("crypto", "keys")
    keys = root_key_bundle.decrypt_bso(keys_bso)
    default_key_bundle = KeyBundle(
        base64.b64decode(keys["default"][0]),
        base64.b64decode(keys["default"][1]),
    )
    for data in tqdm(passdata):
        encrypted_data = default_key_bundle.encrypt_bso(data)
        assert default_key_bundle.decrypt_bso(encrypted_data) == data
        client.put_record("passwords", encrypted_data)
    logging.debug("Synced password records: %d" % len(client.get_records("passwords")))
    logging.info("Done!")


@click.command()
@click.option(
    '--email',
    prompt=True,
    type=click.STRING,
    help="Firefox account email",
)
@click.option(
    '--password',
    prompt=True,
    hide_input=True,
    type=click.STRING,
    help="Firefox account password",
)
@click.argument('password-filepath', type=click.File('r'))
def upload_passwords_to_firefox(email, password, password_filepath=None):
    try:
        absolute_filepath = os.path.realpath(os.path.expanduser(password_filepath.name))
        formated_data = password_file_format(absolute_filepath)
        if click.confirm("%d passwords will be loaded into firefox, do you confirm ? " % len(formated_data)):
            creds = login(email, password)
            upload_passwords_data(formated_data, *creds)
        return 0
    except Exception as e:
        logging.error("%s" % e)
        return 2


if __name__ == "__main__":
    exit(upload_passwords_to_firefox())
