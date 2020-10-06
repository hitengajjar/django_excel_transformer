from django.core.management.base import BaseCommand
from .django_excel_transformer.export.excel_writter import XlsWriter
from .django_excel_transformer.export.exporter import Exporter
from .django_excel_transformer.importer.excel_reader import XlsReader
from .django_excel_transformer.common import Registry
from .django_excel_transformer.parser import Parser
from .django_excel_transformer.importer.importer import Importer
import logging


class Command(BaseCommand):
    def add_arguments(self, parser):

        # parser.add_argument('opt', help='import or export', nargs='?', choices=('import','export'))
        parser.add_argument('-c', '--' + 'config', help='Config mapper file (preferred absolute path)', required=True)

        subparsers = parser.add_subparsers(help='Select from importer or exporter parser', dest='opt')

        parser_import = subparsers.add_parser('import', help='Importer options')
        parser_import.add_argument('-x', '--' + 'xls_file', help='XLS file with data for import', required=True)
        parser_import.add_argument('-l', '--' + 'lod', help='level of details',
                                   default=0)
        parser_import.add_argument('-r', '--' + 'report_name_prefix', help='report name prefix string e.g. DET',
                                   default='DET')
        group = parser_import.add_mutually_exclusive_group()
        group.add_argument('-d',
                           help='dry run. Dont import data in DB. Provides diff between DB and XLS data.',
                            dest='dry_run', action='store_true')
        group.add_argument('-u',
                           help='update database with non-conflicting entries (e.g. new xls records)',
                           dest='db_update', action='store_true')
        group.add_argument('-f',
                           help='updates database records',
                           dest='db_force_update', action='store_true')

        parser_export = subparsers.add_parser('export', help='Exporter options')
        parser_export.add_argument('-x', '--' + 'xls_file', help='Export XLS file', required=True)
        parser_export.add_argument('-o', '--overwrite', help='Overwrite existing excel file if exists',
                                   action='store_true', default=False)

    def handle(self, *args, **options):
        # Registry maintains common instance for parser, exporter, importer etc. Its used for internal processing.

        debuglevel = {0: logging.CRITICAL, 1: logging.ERROR, 2:logging.INFO, 3:logging.DEBUG}
        logging.basicConfig(
            format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(funcName)s():%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d:%H:%M:%S',
            level=debuglevel[options['verbosity']])
        Registry.parser = Parser(options['config'])
        Registry.parser.parse() # you can check for errors using parser.errors() and resolve errors in config.yml

        Registry.options = options

        if options['opt'] == 'import':
            Registry.xlreader = XlsReader(options['xls_file'])
            Registry.importer = Importer.from_registry(xls_file = options['xls_file'],
                                                       lod = options['lod'],
                                                       report_nm = options['report_name_prefix'],
                                                       dry_run=options['dry_run'],
                                                       db_update=options['db_update'],
                                                       db_force_update=options['db_force_update'])
            Registry.importer.import_sheets()
        else:
            # Now instantiate exporter by providing XlsWriter(path_to_export_xls_file, should_overwrite_yes_no)
            Registry.xlwriter = XlsWriter(options['xls_file'], options['overwrite'])
            Registry.exporter = Exporter()
            Registry.exporter.export()  # wrap this around try-except to handle any exceptions