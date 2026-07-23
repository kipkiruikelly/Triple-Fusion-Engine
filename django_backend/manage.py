#!/usr/bin/env python
import os
import sys

import pymysql
pymysql.install_as_MySQLdb()


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bulllogic.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError('Couldn\'t import Django.') from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
