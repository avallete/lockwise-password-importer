import csv
import logging
import sys


def save_data_to_file(output_file, csv_columns, dict_data):
    with open(output_file, 'w') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for data in dict_data:
            writer.writerow(data)
    logging.info("Passwords saved into: %s" % output_file)


def check_running_platform():
    """
    Check if the script can run on the platform, since windows encrypt password it's unsuported for now
    TODO: handle windows platform
    """
    if sys.platform == "linux" or sys.platform == "linux2" or sys.platform == "darwin":
        return
    else:
        raise OSError('Unsupported platform %s' % sys.platform)
