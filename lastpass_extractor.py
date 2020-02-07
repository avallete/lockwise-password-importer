import csv
import logging
import os.path
from urllib.parse import ParseResult, urlparse, urlunparse

import click

from utils import check_running_platform, save_data_to_file

logging.basicConfig(format='%(levelname)s: %(message)s [l.%(lineno)d]', level=logging.DEBUG)


def extract_lastpass_passwords_data(csv_filepath):
    data = []
    with open(csv_filepath, encoding="utf8") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            url = row['url']
            result = urlparse(url)
            hostname = urlunparse(ParseResult(result.scheme, result.netloc, '', '', '', ''))
            data.append({
                'hostname': hostname,
                'formSubmitURL': url,
                'username': row['username'],
                'password': row['password'],
            })
    return data


@click.command(
    help="""Convert data from lastpass extraction file to lockwise_importer compatible file"""
)
@click.option(
    '--output_file',
    '-o',
    type=click.File('w'),
    help="""File where the extracted password will be saved as .csv format""",
    default=os.path.join(os.path.curdir, 'passwords.csv')
)
@click.option(
    '--lastpass-export-file',
    '-i',
    type=click.File('r'),
    help="""Path of the lastpass password extraction in .cvs format to convert.""",
    required=True,
)
def lastpass_extractor(output_file, lastpass_export_file):
    try:
        check_running_platform()
        data = extract_lastpass_passwords_data(lastpass_export_file.name)
        if len(data) > 0:
            save_data_to_file(os.path.realpath(
                os.path.expanduser(output_file.name)),
                data[0].keys(),
                data
            )
    except Exception as e:
        logging.error("%s" % e)


if __name__ == "__main__":
    lastpass_extractor()
